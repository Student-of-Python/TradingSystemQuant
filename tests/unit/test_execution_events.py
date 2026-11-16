'''
tests/unit/test_execution_events.py
'''

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.core.base_event import BaseEvent
from src.execution.domain.enums import OrderSide, OrderStatus, OrderType
from src.execution.domain.events import (
    OrderCancelRequestedEvent,
    FillEvent,
    OrderCanceledEvent,
    OrderRejectedEvent,
    OrderSubmittedEvent,
)
from src.execution.domain.fill import Fill
from src.execution.domain.order import Order

ORDER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
NOW = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)
BLANKS = ["", " ", "\t\n"]


def make_order(quantity: str = "10") -> Order:
    return Order(
        client_order_id=ORDER_ID,
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        created_at=NOW,
    )


def make_fill(fill_id: str = "f-1", price: str = "100", quantity: str = "4") -> Fill:
    return Fill(
        fill_id=fill_id,
        client_order_id=ORDER_ID,
        price=Decimal(price),
        quantity=Decimal(quantity),
        timestamp=NOW,
    )


def submitted(**overrides: object) -> OrderSubmittedEvent:
    kwargs: dict[str, object] = {
        "client_order_id": ORDER_ID,
        "broker_order_id": "B-1",
        "symbol": "AAPL",
        "side": OrderSide.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
    }
    kwargs.update(overrides)
    return OrderSubmittedEvent(**kwargs)  # pyright: ignore[reportArgumentType]


def filled(**overrides: object) -> FillEvent:
    kwargs: dict[str, object] = {
        "fill": make_fill(),
        "symbol": "AAPL",
        "side": OrderSide.BUY,
        "order_status": OrderStatus.PARTIALLY_FILLED,
        "filled_quantity": Decimal("4"),
        "remaining_quantity": Decimal("6"),
        "avg_fill_price": Decimal("100"),
    }
    kwargs.update(overrides)
    return FillEvent(**kwargs)  # pyright: ignore[reportArgumentType]


def rejected(**overrides: object) -> OrderRejectedEvent:
    kwargs: dict[str, object] = {"client_order_id": ORDER_ID, "symbol": "AAPL", "reason": "no"}
    kwargs.update(overrides)
    return OrderRejectedEvent(**kwargs)  # pyright: ignore[reportArgumentType]


def canceled(**overrides: object) -> OrderCanceledEvent:
    kwargs: dict[str, object] = {
        "client_order_id": ORDER_ID,
        "broker_order_id": "B-1",
        "symbol": "AAPL",
        "filled_quantity": Decimal("0"),
    }
    kwargs.update(overrides)
    return OrderCanceledEvent(**kwargs)  # pyright: ignore[reportArgumentType]


def cancel_requested(**overrides: object) -> OrderCancelRequestedEvent:
    kwargs: dict[str, object] = {
        "client_order_id": ORDER_ID,
        "broker_order_id": "B-1",
        "symbol": "AAPL",
        "reason": "timeout",
    }
    kwargs.update(overrides)
    return OrderCancelRequestedEvent(**kwargs)  # pyright: ignore[reportArgumentType]


FACTORIES = [submitted, filled, rejected, canceled, cancel_requested]
IDS = ["submitted", "fill", "rejected", "canceled", "cancel_requested"]


# --- Shared behavior ---

@pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
def test_is_a_base_event_with_id_and_utc_timestamp(factory):
    event = factory()

    assert isinstance(event, BaseEvent)
    assert isinstance(event.event_id, uuid.UUID)
    assert event.created_at.tzinfo is timezone.utc


@pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
def test_fields_cannot_be_reassigned(factory):
    event = factory()

    with pytest.raises(FrozenInstanceError):
        event.symbol = "MSFT"


@pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
def test_two_events_with_same_payload_have_different_ids(factory):
    assert factory().event_id != factory().event_id


@pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
@pytest.mark.parametrize("blank", BLANKS)
def test_blank_symbol_is_refused(factory, blank):
    with pytest.raises(ValueError, match="symbol"):
        factory(symbol=blank)


@pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
def test_positional_arguments_are_refused(factory):
    with pytest.raises(TypeError):
        type(factory())(ORDER_ID)


# --- OrderSubmittedEvent ---

@pytest.mark.parametrize("field, bad, error", [
    ("client_order_id", str(ORDER_ID), TypeError),
    ("broker_order_id", 1, TypeError),
    ("broker_order_id", " ", ValueError),
    ("side", "BUY", TypeError),
    ("quantity", 10, TypeError),
    ("quantity", Decimal("0"), ValueError),
    ("order_type", "MARKET", TypeError),
])
def test_submitted_refuses_bad_fields(field, bad, error):
    with pytest.raises(error, match=field):
        submitted(**{field: bad})


def test_submitted_from_order_copies_the_order():
    order = make_order()
    order.mark_submitted("B-9")

    event = OrderSubmittedEvent.from_order(order)

    assert (event.client_order_id, event.broker_order_id, event.symbol) == (ORDER_ID, "B-9", "AAPL")
    assert (event.side, event.quantity, event.order_type) == (OrderSide.BUY, Decimal("10"), OrderType.MARKET)


def test_submitted_from_unsubmitted_order_is_refused():
    with pytest.raises(ValueError, match="never submitted"):
        OrderSubmittedEvent.from_order(make_order())


# --- FillEvent ---

@pytest.mark.parametrize("field, bad, error", [
    ("fill", "f-1", TypeError),
    ("side", "BUY", TypeError),
    ("order_status", "FILLED", TypeError),
    ("filled_quantity", Decimal("0"), ValueError),
    ("remaining_quantity", Decimal("-1"), ValueError),
    ("avg_fill_price", Decimal("0"), ValueError),
    ("avg_fill_price", 100.0, TypeError),
])
def test_fill_refuses_bad_fields(field, bad, error):
    with pytest.raises(error, match=field):
        filled(**{field: bad})


@pytest.mark.parametrize("status", [OrderStatus.PENDING_SUBMIT, OrderStatus.SUBMITTED,
                                    OrderStatus.CANCELED, OrderStatus.REJECTED])
def test_fill_refuses_non_fill_status(status):
    with pytest.raises(ValueError, match="PARTIALLY_FILLED or FILLED"):
        filled(order_status=status)


def test_fill_refuses_total_smaller_than_this_fill():
    with pytest.raises(ValueError, match="cannot be less"):
        filled(filled_quantity=Decimal("3"))


def test_fill_refuses_filled_status_with_quantity_remaining():
    with pytest.raises(ValueError, match="remaining_quantity must be 0"):
        filled(order_status=OrderStatus.FILLED, remaining_quantity=Decimal("6"))


def test_fill_refuses_partial_status_with_nothing_remaining():
    with pytest.raises(ValueError, match="remaining_quantity must be 0"):
        filled(remaining_quantity=Decimal("0"))


def test_fill_exposes_client_order_id_from_its_fill():
    assert filled().client_order_id == ORDER_ID


def test_fill_from_order_snapshots_partial_then_filled():
    order = make_order()
    order.mark_submitted("B-1")
    first, second = make_fill("f-1", "100", "4"), make_fill("f-2", "110", "6")

    order.apply_fill(first)
    partial = FillEvent.from_order(order, first)
    order.apply_fill(second)
    done = FillEvent.from_order(order, second)

    assert (partial.order_status, partial.filled_quantity, partial.remaining_quantity) == (
        OrderStatus.PARTIALLY_FILLED, Decimal("4"), Decimal("6"))
    assert partial.avg_fill_price == Decimal("100")
    assert (done.order_status, done.filled_quantity, done.remaining_quantity) == (
        OrderStatus.FILLED, Decimal("10"), Decimal("0"))
    assert done.avg_fill_price == Decimal("106")


def test_fill_from_order_refuses_fill_not_applied():
    order = make_order()
    order.mark_submitted("B-1")

    with pytest.raises(ValueError, match="has not been applied"):
        FillEvent.from_order(order, make_fill())


# --- OrderRejectedEvent ---

@pytest.mark.parametrize("field, bad, error", [
    ("client_order_id", None, TypeError),
    ("reason", None, TypeError),
    ("reason", "  ", ValueError),
])
def test_rejected_refuses_bad_fields(field, bad, error):
    with pytest.raises(error, match=field):
        rejected(**{field: bad})


def test_rejected_from_order_carries_the_reason():
    order = make_order()
    order.mark_rejected("BROKER_REJECTED: no buying power")

    event = OrderRejectedEvent.from_order(order)

    assert (event.client_order_id, event.symbol, event.reason) == (
        ORDER_ID, "AAPL", "BROKER_REJECTED: no buying power")


def test_rejected_from_order_that_was_not_rejected_is_refused():
    with pytest.raises(ValueError, match="has not been rejected"):
        OrderRejectedEvent.from_order(make_order())


# --- OrderCanceledEvent ---

@pytest.mark.parametrize("field, bad, error", [
    ("broker_order_id", "", ValueError),
    ("filled_quantity", Decimal("-1"), ValueError),
    ("filled_quantity", 0, TypeError),
])
def test_canceled_refuses_bad_fields(field, bad, error):
    with pytest.raises(error, match=field):
        canceled(**{field: bad})


def test_canceled_from_order_keeps_partial_fills():
    order = make_order()
    order.mark_submitted("B-1")
    order.apply_fill(make_fill())
    order.mark_canceled()

    event = OrderCanceledEvent.from_order(order)

    assert (event.broker_order_id, event.filled_quantity) == ("B-1", Decimal("4"))


def test_canceled_from_order_that_is_not_canceled_is_refused():
    order = make_order()
    order.mark_submitted("B-1")

    with pytest.raises(ValueError, match="not CANCELED"):
        OrderCanceledEvent.from_order(order)


# --- OrderCancelRequestedEvent ---

@pytest.mark.parametrize("field, bad, error", [
    ("client_order_id", str(ORDER_ID), TypeError),
    ("broker_order_id", " ", ValueError),
    ("reason", "", ValueError),
    ("reason", None, TypeError),
])
def test_cancel_requested_refuses_bad_fields(field, bad, error):
    with pytest.raises(error):
        cancel_requested(**{field: bad})


def test_cancel_requested_from_order_copies_the_order():
    order = make_order()
    order.mark_submitted("B-7")

    event = OrderCancelRequestedEvent.from_order(order, "kill switch")

    assert (event.client_order_id, event.broker_order_id, event.symbol, event.reason) == (
        ORDER_ID, "B-7", "AAPL", "kill switch")


def test_cancel_requested_from_unsubmitted_order_is_refused():
    with pytest.raises(ValueError, match="no broker_order_id"):
        OrderCancelRequestedEvent.from_order(make_order(), "timeout")


# --- Slippage ---

def test_fill_without_expected_price_has_no_slippage():
    event = filled()

    assert event.expected_price is None
    assert event.slippage is None and event.slippage_bps is None


@pytest.mark.parametrize("side, avg, expected, slippage, bps", [
    (OrderSide.BUY, "101", "100", "1", "100"),     # paid more: worse
    (OrderSide.BUY, "99.5", "100", "-0.5", "-50"),  # paid less: better
    (OrderSide.SELL, "99", "100", "1", "100"),      # received less: worse
    (OrderSide.SELL, "100.25", "100", "-0.25", "-25"),
])
def test_slippage_is_positive_when_worse_than_expected(side, avg, expected, slippage, bps):
    event = filled(side=side, avg_fill_price=Decimal(avg), expected_price=Decimal(expected))

    assert event.slippage == Decimal(slippage)
    assert event.slippage_bps == Decimal(bps)


@pytest.mark.parametrize("bad, error", [(Decimal("0"), ValueError), (100, TypeError), (Decimal("NaN"), ValueError)])
def test_fill_refuses_bad_expected_price(bad, error):
    with pytest.raises(error):
        filled(expected_price=bad)


def test_fill_from_order_carries_the_orders_expected_price():
    order = Order(client_order_id=ORDER_ID, symbol="AAPL", side=OrderSide.BUY, quantity=Decimal("10"),
                  created_at=NOW, expected_price=Decimal("99"))
    order.mark_submitted("B-1")
    fill = make_fill()
    order.apply_fill(fill)

    event = FillEvent.from_order(order, fill)

    assert event.expected_price == Decimal("99") and event.slippage == Decimal("1")
