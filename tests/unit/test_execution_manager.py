'''
tests/unit/test_execution_manager.py

ExecutionManager with the FakeBroker, a real EventRouter, and real RiskApprovedEvents.
'''

import importlib
from dataclasses import dataclass
import sys
import uuid
from datetime import datetime, timedelta, timezone
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
    OrderCancelRequestedEvent,
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
EXECUTION_EVENTS = (OrderSubmittedEvent, FillEvent, OrderRejectedEvent, OrderCanceledEvent, OrderCancelRequestedEvent)


def make_signal(action: StrategyAction = StrategyAction.BUY, units: object = Decimal("10"),
                symbol: str = "AAPL") -> SignalEvent:
    return SignalEvent(symbol=symbol, action=action, units=units,  # pyright: ignore[reportArgumentType]
                       confidence=Decimal("0.8"), strategy_name="test_strategy")


def approve(signal: SignalEvent | None = None) -> RiskApprovedEvent:
    return RiskApprovedEvent(signal=signal or make_signal(), rules_checked=(RULE,))


class Clock:
    '''A clock tests can move forward.'''

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


class Harness:
    '''Router + manager + fake broker, recording every execution event published.'''

    def __init__(self, broker: object | None = None, *, manager_kwargs: dict[str, object] | None = None,
                 **broker_kwargs: object) -> None:
        self.clock = Clock()
        self.broker = broker or FakeBroker(clock=self.clock, **broker_kwargs)  # pyright: ignore[reportArgumentType]
        self.router = EventRouter()
        self.manager = ExecutionManager(self.broker, clock=self.clock, **(manager_kwargs or {}))  # pyright: ignore[reportArgumentType]
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


# --- In-doubt submits (connection lost during submit) ---

def test_connection_failure_on_submit_leaves_the_order_in_doubt_without_events():
    h = Harness()
    h.broker.disconnect()
    signal = make_signal()

    h.send(approve(signal))

    assert h.published == []
    order = h.manager.orders[make_client_order_id(signal.event_id)]
    assert order.status is OrderStatus.PENDING_SUBMIT
    assert h.manager.in_doubt_orders == (order,)
    assert h.manager.open_orders == ()


def test_in_doubt_order_the_broker_never_received_is_rejected_on_poll():
    h = Harness()
    h.broker.disconnect()
    h.send(approve())
    h.broker.reconnect()

    h.poll()

    (event,) = h.published
    assert isinstance(event, OrderRejectedEvent) and "never received" in event.reason
    assert h.manager.in_doubt_orders == ()
    assert len(h.broker.submitted) == 1  # never re-submitted


def test_in_doubt_order_the_broker_did_receive_is_submitted_then_filled():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.broker.drop_next_submit_ack()
    h.send(approve())
    assert h.published == []

    h.poll()
    h.broker.fill("FAKE-1", Decimal("10"))
    h.poll()

    assert [type(e) for e in h.published] == [OrderSubmittedEvent, FillEvent]
    assert h.of_type(OrderSubmittedEvent)[0].broker_order_id == "FAKE-1"
    assert len(h.broker.submitted) == 1


def test_found_in_doubt_order_applies_fills_it_already_has():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.broker.drop_next_submit_ack()
    h.send(approve())
    h.broker.fill("FAKE-1", Decimal("4"))

    h.poll()

    assert [type(e) for e in h.published] == [OrderSubmittedEvent, FillEvent]


def test_in_doubt_order_is_retried_while_the_broker_is_unreachable():
    h = Harness()
    h.broker.disconnect()
    h.send(approve())

    h.poll()
    h.poll()

    assert h.published == []
    assert len(h.broker.find_requests) == 2
    assert len(h.manager.in_doubt_orders) == 1


def test_in_doubt_order_is_rejected_after_the_in_doubt_timeout(caplog):
    h = Harness(manager_kwargs={"in_doubt_timeout": timedelta(minutes=1)})
    h.broker.disconnect()
    h.send(approve())
    h.poll()
    h.clock.advance(minutes=1)

    with caplog.at_level("ERROR"):
        h.poll()

    (event,) = h.published
    assert isinstance(event, OrderRejectedEvent) and "unknown after" in event.reason
    assert "check it by hand" in caplog.text


def test_approval_again_while_in_doubt_does_not_resubmit():
    h = Harness()
    signal = make_signal()
    h.broker.disconnect()
    h.send(approve(signal))
    h.broker.reconnect()

    h.send(approve(signal))

    assert len(h.broker.submitted) == 1


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


# --- Cancels (manual and kill switch) ---

def test_cancel_order_requests_once_then_reports_the_broker_cancel():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.send(approve())
    (submitted,) = h.of_type(OrderSubmittedEvent)

    h.manager.cancel_order(submitted.client_order_id, "manual")
    h.manager.cancel_order(submitted.client_order_id, "manual again")
    h.drain()
    h.poll()

    (requested,) = h.of_type(OrderCancelRequestedEvent)
    assert (requested.client_order_id, requested.broker_order_id, requested.reason) == (
        submitted.client_order_id, "FAKE-1", "manual")
    assert h.broker.cancel_requests == ["FAKE-1"]
    assert len(h.of_type(OrderCanceledEvent)) == 1


def test_cancel_unknown_or_finished_order_does_nothing():
    h = Harness()
    h.send(approve())
    h.poll()  # filled
    (submitted,) = h.of_type(OrderSubmittedEvent)

    assert h.manager.request_cancel(submitted.client_order_id, "late") == ()
    assert h.manager.request_cancel(uuid.uuid4(), "unknown") == ()
    assert h.broker.cancel_requests == []


def test_refused_cancel_publishes_nothing_and_can_be_retried():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.send(approve())
    (submitted,) = h.of_type(OrderSubmittedEvent)
    h.broker.disconnect()

    assert h.manager.request_cancel(submitted.client_order_id, "x") == ()
    h.broker.reconnect()
    (event,) = h.manager.request_cancel(submitted.client_order_id, "x")

    assert isinstance(event, OrderCancelRequestedEvent)


def test_cancel_all_open_orders_cancels_every_open_order_and_skips_finished_ones():
    h = Harness(fill_mode=FillMode.MANUAL)
    for _ in range(3):
        h.send(approve())
    h.broker.fill("FAKE-3", Decimal("10"))
    h.poll()

    h.manager.cancel_all_open_orders("kill switch")
    h.drain()
    h.poll()

    assert sorted(h.broker.cancel_requests) == ["FAKE-1", "FAKE-2"]
    assert {e.reason for e in h.of_type(OrderCancelRequestedEvent)} == {"kill switch"}
    assert len(h.of_type(OrderCanceledEvent)) == 2
    assert h.manager.open_orders == ()


def test_cancel_of_an_in_doubt_order_is_sent_once_the_broker_confirms_it():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.broker.drop_next_submit_ack()
    h.send(approve())

    h.manager.cancel_all_open_orders("kill switch")
    h.drain()
    assert h.broker.cancel_requests == []
    h.poll()

    # Found, cancel sent, then the same poll's status check already sees CANCELED.
    assert [type(e) for e in h.published] == [OrderSubmittedEvent, OrderCancelRequestedEvent, OrderCanceledEvent]
    assert h.broker.cancel_requests == ["FAKE-1"]


# --- Timeouts ---

def test_order_open_past_the_timeout_is_canceled_once():
    h = Harness(fill_mode=FillMode.MANUAL, manager_kwargs={"order_timeout": timedelta(minutes=10)})
    h.send(approve())

    h.clock.advance(minutes=9)
    h.poll()
    assert h.broker.cancel_requests == []

    h.clock.advance(minutes=1)
    h.broker.disconnect()
    h.poll()  # cancel refused while disconnected: retried next poll
    h.broker.reconnect()
    h.poll()
    h.poll()

    (requested,) = h.of_type(OrderCancelRequestedEvent)
    assert requested.reason.startswith("Timed out")
    assert len(h.of_type(OrderCanceledEvent)) == 1


def test_no_timeout_by_default():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.send(approve())
    h.clock.advance(days=3)

    h.poll()

    assert h.broker.cancel_requests == []


@pytest.mark.parametrize("kwargs", [
    {"order_timeout": timedelta(0)},
    {"in_doubt_timeout": timedelta(seconds=-1)},
    {"order_timeout": 60},
])
def test_bad_timeouts_are_refused(kwargs):
    with pytest.raises(ValueError):
        ExecutionManager(FakeBroker(), **kwargs)


# --- Audit log ---

def test_every_published_event_is_logged(caplog):
    h = Harness()

    with caplog.at_level("INFO", logger="src.execution.manager"):
        h.send(approve())
        h.poll()

    assert "execution event OrderSubmittedEvent" in caplog.text
    assert "execution event FillEvent" in caplog.text


# --- Startup reconciliation (start / stop) ---

def restarted(h: Harness) -> Harness:
    '''A fresh manager (empty memory) on the same broker, like after a process restart.'''
    return Harness(h.broker)


def test_start_adopts_open_broker_orders_after_a_restart():
    before = Harness(fill_mode=FillMode.MANUAL)
    signal = make_signal()
    before.send(approve(signal))
    before.broker.fill("FAKE-1", Decimal("4"), Decimal("50"))
    before.poll()

    after = restarted(before)
    after.manager.start()

    order = after.manager.orders[make_client_order_id(signal.event_id)]
    assert (order.status, order.broker_order_id, order.filled_quantity) == (
        OrderStatus.PARTIALLY_FILLED, "FAKE-1", Decimal("4"))
    assert (order.symbol, order.side, order.quantity) == ("AAPL", OrderSide.BUY, Decimal("10"))
    assert after.published == []  # earlier fills were published before the restart


def test_after_start_only_new_fills_are_published():
    before = Harness(fill_mode=FillMode.MANUAL)
    before.send(approve())
    before.broker.fill("FAKE-1", Decimal("4"))
    after = restarted(before)
    after.manager.start()

    after.broker.fill("FAKE-1", Decimal("6"))
    after.poll()

    (fill,) = after.of_type(FillEvent)
    assert (fill.fill.quantity, fill.order_status) == (Decimal("6"), OrderStatus.FILLED)


def test_signal_approved_again_after_restart_is_not_resubmitted():
    before = Harness(fill_mode=FillMode.MANUAL)
    signal = make_signal()
    before.send(approve(signal))
    after = restarted(before)
    after.manager.start()

    after.send(approve(signal))

    assert len(after.broker.submitted) == 1
    assert after.published == []


def test_start_ignores_finished_orders_and_orders_already_known():
    h = Harness(fill_mode=FillMode.MANUAL)
    h.send(approve(), approve())
    h.broker.fill("FAKE-2", Decimal("10"))

    h.manager.start()  # FAKE-1 is known, FAKE-2 is finished at the broker

    assert h.manager.reconcile() == ()
    assert len(h.manager.orders) == 2


def test_start_fails_loudly_when_the_broker_is_unreachable():
    h = Harness()
    h.broker.disconnect()

    with pytest.raises(RuntimeError, match="reconciliation failed"):
        h.manager.start()


def test_stop_logs_orders_still_open(caplog):
    h = Harness(fill_mode=FillMode.MANUAL)
    h.send(approve())

    with caplog.at_level("WARNING"):
        h.manager.stop()

    assert "1 order(s) still open" in caplog.text


# --- Slippage (expected price from the signal) ---

@dataclass(frozen=True)
class PricedSignal(SignalEvent):
    '''SignalEvent as on feature/strategy-context, which adds `price`. Remove once it lands here.'''
    price: object = None


def priced_signal(price: object) -> PricedSignal:
    return PricedSignal(symbol="AAPL", action=StrategyAction.BUY, units=Decimal("10"),  # pyright: ignore[reportArgumentType]
                        confidence=Decimal("0.8"), strategy_name="test_strategy", price=price)


def test_signal_price_becomes_expected_price_and_fill_reports_slippage():
    h = Harness(fill_price=Decimal("100.5"))

    h.send(approve(priced_signal(Decimal("100"))))
    h.poll()

    (fill,) = h.of_type(FillEvent)
    assert fill.expected_price == Decimal("100")
    assert (fill.slippage, fill.slippage_bps) == (Decimal("0.5"), Decimal("50"))


@pytest.mark.parametrize("price", [None, Decimal("0"), Decimal("NaN"), 100.0, "100"])
def test_missing_or_unusable_signal_price_only_disables_slippage(price):
    h = Harness()

    h.send(approve(priced_signal(price)))
    h.poll()

    (fill,) = h.of_type(FillEvent)
    assert fill.expected_price is None and fill.slippage is None


def test_signal_without_a_price_field_has_no_slippage():
    h = Harness()

    h.send(approve())
    h.poll()

    assert h.of_type(FillEvent)[0].expected_price is None
