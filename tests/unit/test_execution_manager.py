'''
tests/unit/test_execution_manager.py

ExecutionManager with the FakeBroker, a real EventRouter, and real RiskApprovedEvents.
'''

import importlib
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

# TEMPORARY test-only shim, remove once strategy fixes it (owned by the strategy context):
# src/strategy/domain/events.py does `from enums import StrategyAction`, which only resolves
# if `enums` is importable. Point that name at the real module so SignalEvent (and therefore
# RiskApprovedEvent and the manager) can be imported. No source file outside execution is changed.
sys.modules.setdefault("enums", importlib.import_module("src.strategy.domain.enums"))

from src.core import BaseEvent  # noqa: E402
from src.core.results import Result
from src.core.router import EventRouter
from src.execution.adapters.fake_broker import FakeBroker, FillMode
from src.execution.domain.enums import OrderSide, OrderStatus
from src.execution.domain.events import (
    FillEvent,
    OrderCanceledEvent,
    OrderRejectedEvent,
    OrderSubmittedEvent,
)
from src.execution.domain.fill import Fill
from src.execution.domain.order import Order, make_client_order_id
from src.execution.manager import ExecutionManager
from src.execution.ports import BrokerErrorCode, BrokerOrderUpdate, broker_error
from src.risk.domain.events import RiskApprovedEvent
from src.risk.domain.rules import MaxUnitSizeRule
from src.strategy.domain.enums import StrategyAction
from src.strategy.domain.events import SignalEvent

NOW = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)
RULE = MaxUnitSizeRule(Decimal("100"))
EXECUTION_EVENTS = (OrderSubmittedEvent, FillEvent, OrderRejectedEvent, OrderCanceledEvent)


def make_signal(action: StrategyAction = StrategyAction.BUY, units: object = Decimal("10"),
                symbol: str = "AAPL") -> SignalEvent:
    return SignalEvent(symbol=symbol, action=action, units=units,  # pyright: ignore[reportArgumentType]
                       confidence=Decimal("0.8"), strategy_name="test_strategy")


def approve(signal: SignalEvent | None = None) -> RiskApprovedEvent:
    return RiskApprovedEvent(signal=signal or make_signal(), rules_checked=(RULE,))


class Harness:
    '''Router + manager + fake broker, recording every execution event published.'''

    def __init__(self, broker: object | None = None, **broker_kwargs: object) -> None:
        self.broker = broker or FakeBroker(clock=lambda: NOW, **broker_kwargs)  # pyright: ignore[reportArgumentType]
        self.router = EventRouter()
        self.manager = ExecutionManager(self.broker, clock=lambda: NOW)  # pyright: ignore[reportArgumentType]
        self.manager.register_subscriptions(self.router)
        self.published: list[BaseEvent] = []
        self.router.subscribe(EXECUTION_EVENTS, self.published.append)

    def drain(self) -> None:
        # The router has no run/drain loop yet (asked Gleb); dispatch until the queue is empty.
        while self.router._queue:  # pyright: ignore[reportPrivateUsage]
            self.router.dispatch_next()

    def send(self, *events: BaseEvent) -> None:
        self.router.publish(*events)
        self.drain()

    def poll(self) -> None:
        self.manager.poll()
        self.drain()

    def of_type[T](self, cls: type[T]) -> list[T]:
        return [e for e in self.published if isinstance(e, cls)]


# --- Happy path ---

def test_approval_is_submitted_then_filled_on_poll():
    h = Harness(fill_price=Decimal("190.15"))
    signal = make_signal()

    h.send(approve(signal))
    h.poll()

    submitted, fill = h.published
    assert isinstance(submitted, OrderSubmittedEvent)
    assert submitted.client_order_id == make_client_order_id(signal.event_id)
    assert (submitted.broker_order_id, submitted.symbol, submitted.side, submitted.quantity) == (
        "FAKE-1", "AAPL", OrderSide.BUY, Decimal("10"))
    assert isinstance(fill, FillEvent)
    assert (fill.order_status, fill.filled_quantity, fill.avg_fill_price) == (
        OrderStatus.FILLED, Decimal("10"), Decimal("190.15"))
    assert h.manager.orders[submitted.client_order_id].status is OrderStatus.FILLED


def test_sell_becomes_a_sell_order():
    h = Harness()

    h.send(approve(make_signal(StrategyAction.SELL)))

    assert h.of_type(OrderSubmittedEvent)[0].side is OrderSide.SELL


def test_order_is_built_from_the_signal_with_the_manager_clock():
    h = Harness()
    signal = make_signal(units=Decimal("2.5"), symbol="MSFT")

    h.send(approve(signal))

    order = h.manager.orders[make_client_order_id(signal.event_id)]
    assert (order.symbol, order.quantity, order.created_at) == ("MSFT", Decimal("2.5"), NOW)


def test_full_pipeline_signal_through_risk_into_execution():
    # RiskManager imports src.core.protocols, which raises NameError on Python < 3.14
    # (EventRouter annotation without deferred annotations). Owned by core; skip until fixed.
    try:
        from src.risk.manager import RiskManager
    except NameError as error:
        pytest.skip(f"src.core.protocols does not import on this Python: {error}")
    h = Harness()
    RiskManager([RULE]).register_subscriptions(h.router)

    h.send(make_signal())
    h.poll()

    assert [type(e) for e in h.published] == [OrderSubmittedEvent, FillEvent]


# --- Idempotency ---

def test_same_approval_published_twice_submits_once():
    h = Harness()
    approval = approve()

    h.send(approval, approval)

    assert len(h.broker.submitted) == 1
    assert len(h.of_type(OrderSubmittedEvent)) == 1


def test_two_approvals_of_the_same_signal_submit_once():
    h = Harness()
    signal = make_signal()

    h.send(approve(signal), approve(signal))

    assert len(h.broker.submitted) == 1
    assert len(h.manager.orders) == 1


def test_different_signals_become_different_orders():
    h = Harness()

    h.send(approve(), approve())

    assert len(h.broker.submitted) == 2
    assert len({e.client_order_id for e in h.of_type(OrderSubmittedEvent)}) == 2


def test_signal_rejected_by_broker_is_not_retried_when_approved_again():
    h = Harness()
    h.broker.fail_submits_with(broker_error(BrokerErrorCode.INSUFFICIENT_FUNDS, "no cash"))
    signal = make_signal()

    h.send(approve(signal))
    h.broker.fail_submits_with(None)
    h.send(approve(signal))

    assert len(h.broker.submitted) == 1
    assert [type(e) for e in h.published] == [OrderRejectedEvent]


# --- Refused before the broker ---

@pytest.mark.parametrize("action", [StrategyAction.HOLD, StrategyAction.LIQUIDATE])
def test_unsupported_action_is_rejected_without_calling_the_broker(action):
    h = Harness()
    signal = make_signal(action)

    h.send(approve(signal))

    (event,) = h.published
    assert isinstance(event, OrderRejectedEvent)
    assert event.client_order_id == make_client_order_id(signal.event_id)
    assert "Unsupported action" in event.reason and str(action) in event.reason
    assert h.broker.submitted == []
    assert h.manager.orders == {}


@pytest.mark.parametrize("units", [Decimal("0"), Decimal("-5"), Decimal("NaN"), 10, 1.5])
def test_invalid_units_are_rejected_without_calling_the_broker(units):
    h = Harness()

    h.send(approve(make_signal(units=units)))

    (event,) = h.published
    assert isinstance(event, OrderRejectedEvent)
    assert event.reason.startswith("Invalid signal") and "quantity" in event.reason
    assert h.broker.submitted == []


# --- Broker failures on submit ---

def test_broker_rejection_becomes_order_rejected_event():
    h = Harness()
    h.broker.fail_submits_with(broker_error(BrokerErrorCode.INSUFFICIENT_FUNDS, "no cash"))

    h.send(approve())

    (event,) = h.published
    assert isinstance(event, OrderRejectedEvent)
    assert event.reason == "INSUFFICIENT_FUNDS: no cash"
    assert h.manager.orders[event.client_order_id].status is OrderStatus.REJECTED


def test_connection_failure_on_submit_becomes_order_rejected_event():
    h = Harness()
    h.broker.disconnect()

    h.send(approve())

    (event,) = h.published
    assert isinstance(event, OrderRejectedEvent)
    assert event.reason.startswith("CONNECTION_FAILURE")


class RaisingBroker(FakeBroker):
    def submit_order(self, order: Order) -> Result[str]:
        raise RuntimeError("boom")


def test_adapter_that_raises_is_contained_and_rejects_the_order():
    h = Harness(broker=RaisingBroker())

    h.send(approve())

    (event,) = h.published
    assert isinstance(event, OrderRejectedEvent)
    assert event.reason == "UNKNOWN_ERROR: RuntimeError: boom"


class BlankIdBroker(FakeBroker):
    def submit_order(self, order: Order) -> Result[str]:
        return Result.successful(" ")


def test_success_without_a_usable_broker_id_rejects_the_order():
    h = Harness(broker=BlankIdBroker())

    h.send(approve())

    (event,) = h.published
    assert isinstance(event, OrderRejectedEvent)
    assert "invalid order id" in event.reason


def test_rejected_orders_are_never_polled():
    h = Harness()
    h.broker.disconnect()
    h.send(approve())
    h.broker.reconnect()

    h.poll()

    assert h.broker.status_requests == []


# --- Polling ---

def test_partial_fills_arrive_across_several_polls():
    h = Harness(fill_mode=FillMode.PARTIAL, partial_steps=3)
    h.send(approve(make_signal(units=Decimal("9"))))

    for _ in range(5):  # the extra polls must not repeat fills
        h.poll()

    fills = h.of_type(FillEvent)
    assert [f.order_status for f in fills] == [
        OrderStatus.PARTIALLY_FILLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED]
    assert [f.filled_quantity for f in fills] == [Decimal("3"), Decimal("6"), Decimal("9")]
    assert [f.remaining_quantity for f in fills] == [Decimal("6"), Decimal("3"), Decimal("0")]
    assert len(h.broker.status_requests) == 3  # stops asking once FILLED


def test_poll_with_nothing_open_publishes_nothing():
    h = Harness()

    h.poll()

    assert h.published == []


def test_status_failure_is_retried_on_the_next_poll():
    h = Harness()
    h.send(approve())
    h.broker.disconnect()

    h.poll()
    assert h.of_type(FillEvent) == []

    h.broker.reconnect()
    h.poll()
    assert len(h.of_type(FillEvent)) == 1


def test_each_open_order_is_polled():
    h = Harness()
    h.send(approve(), approve())

    h.poll()

    assert len(h.of_type(FillEvent)) == 2


def test_cancel_at_the_broker_keeps_earlier_partial_fills():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.send(approve())
    (submitted,) = h.of_type(OrderSubmittedEvent)
    h.broker.fill(submitted.broker_order_id, Decimal("4"))
    h.broker.cancel_order(submitted.broker_order_id)

    h.poll()

    fill, canceled = h.published[1:]
    assert isinstance(fill, FillEvent) and fill.order_status is OrderStatus.PARTIALLY_FILLED
    assert isinstance(canceled, OrderCanceledEvent) and canceled.filled_quantity == Decimal("4")
    assert h.manager.orders[submitted.client_order_id].status is OrderStatus.CANCELED


def test_broker_reject_after_acknowledging_becomes_order_rejected_event():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.send(approve())
    (submitted,) = h.of_type(OrderSubmittedEvent)
    h.broker.reject(submitted.broker_order_id, "symbol halted")

    h.poll()

    rejected = h.of_type(OrderRejectedEvent)
    assert [e.reason for e in rejected] == ["symbol halted"]


def test_broker_reporting_filled_before_sending_fills_waits_for_them():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.send(approve())
    (submitted,) = h.of_type(OrderSubmittedEvent)
    h.broker._orders[submitted.broker_order_id].status = OrderStatus.FILLED  # pyright: ignore[reportPrivateUsage]

    h.poll()

    assert h.of_type(FillEvent) == []
    assert h.manager.orders[submitted.client_order_id].status is OrderStatus.SUBMITTED


class OverfillingBroker(FakeBroker):
    '''Reports a fill bigger than the order, which the Order must refuse.'''

    def get_order_status(self, broker_order_id: str) -> Result[BrokerOrderUpdate]:
        client_order_id = self._orders[broker_order_id].client_order_id  # pyright: ignore[reportPrivateUsage]
        bad = Fill(fill_id="x", client_order_id=client_order_id, price=Decimal("1"),
                   quantity=Decimal("1000"), timestamp=NOW)
        return Result.successful(BrokerOrderUpdate(
            broker_order_id=broker_order_id, status=OrderStatus.FILLED, fills=(bad,)))


def test_bad_fill_from_broker_is_skipped_without_crashing():
    h = Harness(broker=OverfillingBroker(clock=lambda: NOW))
    h.send(approve())

    h.poll()

    order = next(iter(h.manager.orders.values()))
    assert h.of_type(FillEvent) == []
    assert (order.status, order.filled_quantity) == (OrderStatus.SUBMITTED, Decimal("0"))


# --- Wiring ---

def test_registering_twice_with_the_same_router_subscribes_once():
    h = Harness()
    h.manager.register_subscriptions(h.router)

    h.send(approve())

    assert len(h.of_type(OrderSubmittedEvent)) == 1


def test_registering_with_a_second_router_is_refused():
    h = Harness()

    with pytest.raises(RuntimeError, match="different router"):
        h.manager.register_subscriptions(EventRouter())


def test_poll_before_registering_is_refused():
    manager = ExecutionManager(FakeBroker())

    with pytest.raises(RuntimeError, match="register_subscriptions"):
        manager.poll()


def test_handle_approval_returns_events_without_a_router():
    manager = ExecutionManager(FakeBroker())

    (event,) = manager.handle_approval(approve())

    assert isinstance(event, OrderSubmittedEvent)


def test_orders_view_is_read_only():
    h = Harness()
    h.send(approve())

    with pytest.raises(TypeError):
        h.manager.orders[uuid.uuid4()] = None  # pyright: ignore[reportIndexIssue]
