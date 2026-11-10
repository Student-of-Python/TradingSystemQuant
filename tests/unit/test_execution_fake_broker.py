'''
tests/unit/test_execution_fake_broker.py

Also covers BrokerOrderUpdate (ports.py) and checks FakeBroker satisfies BrokerPort.
'''

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.core.results import ErrorCode
from src.execution.adapters.fake_broker import FakeBroker, FillMode
from src.execution.domain.enums import OrderSide, OrderStatus
from src.execution.domain.fill import Fill
from src.execution.domain.order import Order
from src.execution.ports import (
    BrokerErrorCode,
    BrokerOrderUpdate,
    BrokerPort,
    broker_error,
    broker_error_code,
)

NOW = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)


def make_order(quantity: str = "10", n: int = 1) -> Order:
    return Order(
        client_order_id=uuid.UUID(int=n),
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        created_at=NOW,
    )


def make_broker(**kwargs: object) -> FakeBroker:
    return FakeBroker(clock=lambda: NOW, **kwargs)  # pyright: ignore[reportArgumentType]


def submit(broker: FakeBroker, order: Order) -> str:
    result = broker.submit_order(order)
    assert result.is_success, result.error
    assert result.value is not None
    return result.value


def status(broker: FakeBroker, broker_order_id: str) -> BrokerOrderUpdate:
    result = broker.get_order_status(broker_order_id)
    assert result.is_success, result.error
    assert result.value is not None
    return result.value


def test_satisfies_the_broker_port():
    port: BrokerPort = make_broker()  # checked by the type checker

    assert all(callable(getattr(port, name)) for name in ("submit_order", "cancel_order", "get_order_status"))


# --- BrokerOrderUpdate ---

def test_update_defaults_to_no_fills_and_no_reason():
    update = BrokerOrderUpdate(broker_order_id="B-1", status=OrderStatus.SUBMITTED)

    assert (update.fills, update.reason) == ((), None)


@pytest.mark.parametrize("field, bad, error", [
    ("broker_order_id", " ", ValueError),
    ("status", "FILLED", TypeError),
    ("fills", [], TypeError),
    ("fills", ("f-1",), TypeError),
    ("reason", "", ValueError),
])
def test_update_refuses_bad_fields(field, bad, error):
    kwargs: dict[str, object] = {"broker_order_id": "B-1", "status": OrderStatus.SUBMITTED, field: bad}

    with pytest.raises(error, match=field):
        BrokerOrderUpdate(**kwargs)  # pyright: ignore[reportArgumentType]


def test_update_refuses_pending_submit():
    with pytest.raises(ValueError, match="PENDING_SUBMIT"):
        BrokerOrderUpdate(broker_order_id="B-1", status=OrderStatus.PENDING_SUBMIT)


# --- Broker error helpers ---

def test_broker_error_keeps_extra_details_and_carries_the_code():
    error = broker_error(BrokerErrorCode.DUPLICATE_ORDER, "dup", {"broker_order_id": "B-1"})

    assert error.code is ErrorCode.UNKNOWN_ERROR  # until core has broker codes
    assert error.details is not None and error.details["broker_order_id"] == "B-1"
    assert broker_error_code(error) is BrokerErrorCode.DUPLICATE_ORDER


def test_broker_error_code_of_a_plain_error_is_none():
    from src.core.results import Error

    assert broker_error_code(None) is None
    assert broker_error_code(Error.connection_failed("down", None)) is None
    assert broker_error_code(Error.unknown_error("?", {"broker_code": "DUPLICATE_ORDER"})) is None


# --- Submit ---

def test_submit_returns_a_new_broker_id_per_order_and_records_the_call():
    broker = make_broker()
    first, second = make_order(n=1), make_order(n=2)

    ids = submit(broker, first), submit(broker, second)

    assert ids == ("FAKE-1", "FAKE-2")
    assert broker.submitted == [first, second]


def test_submit_does_not_change_the_order():
    order = make_order()

    submit(make_broker(), order)

    assert order.status is OrderStatus.PENDING_SUBMIT


def test_same_client_order_id_twice_is_a_duplicate():
    broker = make_broker()
    submit(broker, make_order(n=7))

    result = broker.submit_order(make_order(n=7))

    assert not result.is_success
    assert broker_error_code(result.error) is BrokerErrorCode.DUPLICATE_ORDER


def test_configured_submit_error_is_returned_until_cleared():
    broker = make_broker()
    error = broker_error(BrokerErrorCode.INSUFFICIENT_FUNDS, "no cash")
    broker.fail_submits_with(error)

    failed = broker.submit_order(make_order(n=1))
    broker.fail_submits_with(None)
    ok = broker.submit_order(make_order(n=2))

    assert failed.error is error
    assert ok.is_success


def test_disconnected_broker_fails_every_call_with_connection_failure():
    broker = make_broker()
    broker_id = submit(broker, make_order(n=1))
    broker.disconnect()

    results = [broker.submit_order(make_order(n=2)), broker.cancel_order(broker_id), broker.get_order_status(broker_id)]

    assert all(r.error is not None and r.error.code is ErrorCode.CONNECTION_FAILURE for r in results)


def test_reconnect_restores_service():
    broker = make_broker()
    broker.disconnect()
    broker.reconnect()

    assert broker.submit_order(make_order()).is_success


# --- Fill modes ---

def test_immediate_mode_fills_everything_on_first_poll():
    broker = make_broker(fill_price=Decimal("190.5"))
    order = make_order("10")
    broker_id = submit(broker, order)

    update = status(broker, broker_id)

    assert update.status is OrderStatus.FILLED
    assert update.fills == (Fill(fill_id="FAKE-1-fill-1", client_order_id=order.client_order_id,
                                 price=Decimal("190.5"), quantity=Decimal("10"), timestamp=NOW),)


def test_partial_mode_fills_one_chunk_per_poll_and_repeats_earlier_fills():
    broker = make_broker(fill_mode=FillMode.PARTIAL, partial_steps=3)
    broker_id = submit(broker, make_order("10"))

    updates = [status(broker, broker_id) for _ in range(4)]

    assert [u.status for u in updates] == [OrderStatus.PARTIALLY_FILLED, OrderStatus.PARTIALLY_FILLED,
                                           OrderStatus.FILLED, OrderStatus.FILLED]
    assert [len(u.fills) for u in updates] == [1, 2, 3, 3]
    assert sum(f.quantity for f in updates[-1].fills) == Decimal("10")  # exact, despite 10 / 3
    assert updates[1].fills[0] == updates[0].fills[0]


def test_manual_mode_never_fills_on_its_own():
    broker = make_broker(fill_mode=FillMode.MANUAL)
    broker_id = submit(broker, make_order())

    update = status(broker, broker_id)

    assert (update.status, update.fills) == (OrderStatus.SUBMITTED, ())


def test_manual_fill_is_reported_on_next_poll():
    broker = make_broker(fill_mode=FillMode.MANUAL)
    broker_id = submit(broker, make_order("10"))

    fill = broker.fill(broker_id, Decimal("4"), Decimal("99"))

    assert status(broker, broker_id) == BrokerOrderUpdate(
        broker_order_id=broker_id, status=OrderStatus.PARTIALLY_FILLED, fills=(fill,))


def test_partial_mode_after_a_manual_fill_never_overfills():
    broker = make_broker(fill_mode=FillMode.PARTIAL, partial_steps=2)
    broker_id = submit(broker, make_order("10"))
    broker.fill(broker_id, Decimal("8"))

    update = status(broker, broker_id)

    assert update.status is OrderStatus.FILLED
    assert sum(f.quantity for f in update.fills) == Decimal("10")


def test_manual_fill_beyond_remaining_is_refused():
    broker = make_broker(fill_mode=FillMode.MANUAL)
    broker_id = submit(broker, make_order("10"))

    with pytest.raises(ValueError, match="exceeds"):
        broker.fill(broker_id, Decimal("11"))


def test_broker_side_reject_is_reported_with_reason():
    broker = make_broker(fill_mode=FillMode.MANUAL)
    broker_id = submit(broker, make_order())

    broker.reject(broker_id, "halted")

    update = status(broker, broker_id)
    assert (update.status, update.reason) == (OrderStatus.REJECTED, "halted")


# --- Cancel and lookup ---

def test_cancel_open_order_is_reported_as_canceled_and_stops_fills():
    broker = make_broker(fill_mode=FillMode.PARTIAL)
    broker_id = submit(broker, make_order("10"))
    status(broker, broker_id)  # first chunk fills

    assert broker.cancel_order(broker_id).is_success
    update = status(broker, broker_id)

    assert update.status is OrderStatus.CANCELED
    assert len(update.fills) == 1
    assert broker.cancel_requests == [broker_id]


def test_cancel_filled_order_is_refused():
    broker = make_broker()
    broker_id = submit(broker, make_order())
    status(broker, broker_id)

    result = broker.cancel_order(broker_id)

    assert broker_error_code(result.error) is BrokerErrorCode.BROKER_REJECTED


@pytest.mark.parametrize("call", ["cancel_order", "get_order_status"])
def test_unknown_broker_id_is_not_found(call):
    result = getattr(make_broker(), call)("nope")

    assert broker_error_code(result.error) is BrokerErrorCode.ORDER_NOT_FOUND


@pytest.mark.parametrize("kwargs, error", [
    ({"fill_mode": "IMMEDIATE"}, TypeError),
    ({"partial_steps": 1}, ValueError),
])
def test_bad_configuration_is_refused(kwargs, error):
    with pytest.raises(error):
        make_broker(**kwargs)
