'''
tests/unit/test_execution_order.py
'''

import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

import pytest

from src.execution.domain.enums import OrderSide, OrderStatus, OrderType
from src.execution.domain.errors import (
    DuplicateFillError,
    FillOrderMismatchError,
    IllegalTransitionError,
    OverfillError,
)
from src.execution.domain.fill import Fill
from src.execution.domain.order import ALLOWED_TRANSITIONS, Order, make_client_order_id

S = OrderStatus
BLANKS = ["", " ", "\t\n"]
SIGNAL_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
OTHER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
NOW = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)

_fill_counter = itertools.count()


def make_order(**overrides: object) -> Order:
    kwargs: dict[str, object] = {
        "client_order_id": make_client_order_id(SIGNAL_ID),
        "symbol": "AAPL",
        "side": OrderSide.BUY,
        "quantity": Decimal("10"),
        "created_at": NOW,
    }
    kwargs.update(overrides)
    return Order(**kwargs)  # pyright: ignore[reportArgumentType]


def make_fill(order: Order, quantity: str, price: str = "100", fill_id: str | None = None) -> Fill:
    return Fill(
        fill_id=fill_id or f"fill-{next(_fill_counter)}",
        client_order_id=order.client_order_id,
        price=Decimal(price),
        quantity=Decimal(quantity),
        timestamp=NOW,
    )


def submitted_order(**overrides: object) -> Order:
    order = make_order(**overrides)
    order.mark_submitted("broker-1")
    return order


# =====================================================================
# make_client_order_id
# =====================================================================

def test_client_order_id_is_deterministic():
    assert make_client_order_id(SIGNAL_ID) == make_client_order_id(SIGNAL_ID)


def test_different_signals_get_different_client_order_ids():
    assert make_client_order_id(SIGNAL_ID) != make_client_order_id(OTHER_ID)


def test_client_order_id_is_a_uuid5():
    assert make_client_order_id(SIGNAL_ID).version == 5


def test_client_order_id_value_is_pinned():
    # If this changes, orders created before the change can no longer be matched
    # after a restart. Never change the namespace.
    assert make_client_order_id(SIGNAL_ID) == uuid.UUID("52b08c7a-7c2b-5fb2-837c-bf8363d7d6c6")


@pytest.mark.parametrize("bad", [None, str(SIGNAL_ID), 5], ids=["none", "uuid-as-str", "int"])
def test_client_order_id_needs_a_uuid_signal_id(bad: object):
    with pytest.raises(TypeError, match="signal_id must be a UUID"):
        make_client_order_id(bad)  # pyright: ignore[reportArgumentType]


# =====================================================================
# Construction
# =====================================================================

def test_new_order_holds_its_fields():
    order = make_order(expected_price=Decimal("190.12"))

    assert order.client_order_id == make_client_order_id(SIGNAL_ID)
    assert order.symbol == "AAPL"
    assert order.side == OrderSide.BUY
    assert order.quantity == Decimal("10")
    assert order.created_at == NOW
    assert order.order_type == OrderType.MARKET
    assert order.expected_price == Decimal("190.12")


def test_new_order_starts_pending_submit_with_nothing_filled():
    order = make_order()

    assert order.status == S.PENDING_SUBMIT
    assert order.filled_quantity == Decimal("0")
    assert order.remaining_quantity == Decimal("10")
    assert order.avg_fill_price is None
    assert order.fills == ()
    assert order.broker_order_id is None
    assert order.reject_reason is None
    assert not order.is_terminal


def test_expected_price_defaults_to_none():
    assert make_order().expected_price is None


def test_for_signal_builds_the_deterministic_client_order_id():
    order = Order.for_signal(
        signal_id=SIGNAL_ID, symbol="AAPL", side=OrderSide.SELL, quantity=Decimal("3"), created_at=NOW,
    )

    assert order.client_order_id == make_client_order_id(SIGNAL_ID)
    assert order.side == OrderSide.SELL
    assert order.quantity == Decimal("3")


def test_positional_arguments_are_refused():
    with pytest.raises(TypeError):
        Order(make_client_order_id(SIGNAL_ID), "AAPL", OrderSide.BUY, Decimal("1"), NOW)  # type: ignore[misc]


@pytest.mark.parametrize("missing", ["client_order_id", "symbol", "side", "quantity", "created_at"])
def test_required_fields(missing: str):
    kwargs: dict[str, object] = {
        "client_order_id": make_client_order_id(SIGNAL_ID),
        "symbol": "AAPL",
        "side": OrderSide.BUY,
        "quantity": Decimal("10"),
        "created_at": NOW,
    }
    del kwargs[missing]

    with pytest.raises(TypeError):
        Order(**kwargs)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("bad", [None, str(SIGNAL_ID)], ids=["none", "uuid-as-str"])
def test_non_uuid_client_order_id_is_refused(bad: object):
    with pytest.raises(TypeError, match="client_order_id must be a UUID"):
        make_order(client_order_id=bad)


@pytest.mark.parametrize("bad", [None, 5, b"AAPL"], ids=["none", "int", "bytes"])
def test_non_str_symbol_is_refused(bad: object):
    with pytest.raises(TypeError, match="symbol must be a str"):
        make_order(symbol=bad)


@pytest.mark.parametrize("blank", BLANKS)
def test_blank_symbol_is_refused(blank: str):
    with pytest.raises(ValueError, match="symbol must not be blank"):
        make_order(symbol=blank)


@pytest.mark.parametrize("bad", ["BUY", None, OrderStatus.SUBMITTED], ids=["plain-str", "none", "wrong-enum"])
def test_side_must_be_an_order_side(bad: object):
    with pytest.raises(TypeError, match="side must be an OrderSide"):
        make_order(side=bad)


@pytest.mark.parametrize("bad", ["MARKET", None], ids=["plain-str", "none"])
def test_order_type_must_be_an_order_type(bad: object):
    with pytest.raises(TypeError, match="order_type must be an OrderType"):
        make_order(order_type=bad)


@pytest.mark.parametrize("bad", [10, 10.0, "10"], ids=["int", "float", "str"])
def test_non_decimal_quantity_is_refused(bad: object):
    with pytest.raises(TypeError, match="quantity must be a Decimal"):
        make_order(quantity=bad)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "sNaN"])
def test_non_finite_quantity_is_refused(bad: str):
    with pytest.raises(ValueError, match="quantity must be finite"):
        make_order(quantity=Decimal(bad))


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_zero_or_negative_quantity_is_refused(bad: str):
    with pytest.raises(ValueError, match="quantity must be greater than 0"):
        make_order(quantity=Decimal(bad))


@pytest.mark.parametrize("bad", [190.12, "190.12"], ids=["float", "str"])
def test_non_decimal_expected_price_is_refused(bad: object):
    with pytest.raises(TypeError, match="expected_price must be a Decimal"):
        make_order(expected_price=bad)


@pytest.mark.parametrize("bad", ["0", "-1", "NaN"])
def test_invalid_expected_price_is_refused(bad: str):
    with pytest.raises(ValueError, match="expected_price must be"):
        make_order(expected_price=Decimal(bad))


def test_naive_created_at_is_refused():
    with pytest.raises(ValueError, match="created_at must be timezone-aware UTC"):
        make_order(created_at=datetime(2026, 11, 9, 14, 30))


def test_non_utc_created_at_is_refused():
    with pytest.raises(ValueError, match="created_at must be timezone-aware UTC"):
        make_order(created_at=datetime(2026, 11, 9, 9, 30, tzinfo=timezone(timedelta(hours=-5))))


def test_non_datetime_created_at_is_refused():
    with pytest.raises(TypeError, match="created_at must be a datetime"):
        make_order(created_at="2026-11-09")


# =====================================================================
# Encapsulation & identity
# =====================================================================

@pytest.mark.parametrize("field", ["status", "filled_quantity", "client_order_id", "quantity", "fills"])
def test_state_cannot_be_set_directly(field: str):
    order = make_order()

    with pytest.raises(AttributeError):
        setattr(order, field, None)


def test_fills_returned_cannot_change_the_order():
    order = submitted_order()
    order.apply_fill(make_fill(order, "4"))

    assert isinstance(order.fills, tuple)


def test_orders_are_equal_by_client_order_id():
    a = make_order(quantity=Decimal("10"))
    b = make_order(quantity=Decimal("99"))

    assert a == b
    assert hash(a) == hash(b)


def test_orders_with_different_ids_are_not_equal():
    assert make_order() != make_order(client_order_id=make_client_order_id(OTHER_ID))


def test_order_is_not_equal_to_other_types():
    assert make_order() != make_order().client_order_id


# =====================================================================
# The transition table
# =====================================================================

def test_transition_table_is_exactly_as_designed():
    assert dict(ALLOWED_TRANSITIONS) == {
        S.PENDING_SUBMIT: frozenset({S.SUBMITTED, S.REJECTED}),
        S.SUBMITTED: frozenset({S.PARTIALLY_FILLED, S.FILLED, S.CANCELED, S.REJECTED}),
        S.PARTIALLY_FILLED: frozenset({S.PARTIALLY_FILLED, S.FILLED, S.CANCELED}),
        S.FILLED: frozenset(),
        S.CANCELED: frozenset(),
        S.REJECTED: frozenset(),
    }


def test_transition_table_cannot_be_modified():
    with pytest.raises(TypeError):
        ALLOWED_TRANSITIONS[S.FILLED] = frozenset({S.SUBMITTED})  # pyright: ignore[reportIndexIssue]


def test_every_status_is_in_the_table():
    assert set(ALLOWED_TRANSITIONS) == set(OrderStatus)


def test_nothing_can_go_back_to_pending_submit():
    assert all(S.PENDING_SUBMIT not in targets for targets in ALLOWED_TRANSITIONS.values())


# --- Drive an order into any status using only public methods ---

def order_in(status: OrderStatus) -> Order:
    order = make_order()
    if status == S.PENDING_SUBMIT:
        return order
    if status == S.REJECTED:
        order.mark_rejected("insufficient buying power")
        return order

    order.mark_submitted("broker-1")
    if status == S.PARTIALLY_FILLED:
        order.apply_fill(make_fill(order, "4"))
    elif status == S.FILLED:
        order.apply_fill(make_fill(order, "10"))
    elif status == S.CANCELED:
        order.mark_canceled()
    return order


def attempt(target: OrderStatus) -> Callable[[Order], None]:
    '''The public action that tries to move an order into `target`.'''
    def partial_fill(order: Order) -> None:
        order.apply_fill(make_fill(order, "1"))

    def full_fill(order: Order) -> None:
        remaining = order.remaining_quantity
        order.apply_fill(make_fill(order, str(remaining) if remaining > 0 else "1"))

    return {
        S.SUBMITTED: lambda o: o.mark_submitted("broker-2"),
        S.PARTIALLY_FILLED: partial_fill,
        S.FILLED: full_fill,
        S.CANCELED: lambda o: o.mark_canceled(),
        S.REJECTED: lambda o: o.mark_rejected("broker said no"),
    }[target]


ALL_PAIRS = [(a, b) for a in OrderStatus for b in OrderStatus if b != S.PENDING_SUBMIT]
LEGAL = [(a, b) for a, b in ALL_PAIRS if b in ALLOWED_TRANSITIONS[a]]
ILLEGAL = [(a, b) for a, b in ALL_PAIRS if b not in ALLOWED_TRANSITIONS[a]]


@pytest.mark.parametrize("current,target", LEGAL, ids=[f"{a}->{b}" for a, b in LEGAL])
def test_every_legal_transition_works(current: OrderStatus, target: OrderStatus):
    order = order_in(current)

    attempt(target)(order)

    assert order.status == target


@pytest.mark.parametrize("current,target", ILLEGAL, ids=[f"{a}->{b}" for a, b in ILLEGAL])
def test_every_illegal_transition_raises(current: OrderStatus, target: OrderStatus):
    order = order_in(current)

    with pytest.raises(IllegalTransitionError) as caught:
        attempt(target)(order)

    assert caught.value.current == current
    if current != S.FILLED:
        # A FILLED order has nothing remaining, so any further fill is reported as an attempt to fill it.
        assert caught.value.target == target


@pytest.mark.parametrize("current,target", ILLEGAL, ids=[f"{a}->{b}" for a, b in ILLEGAL])
def test_illegal_transition_leaves_the_order_unchanged(current: OrderStatus, target: OrderStatus):
    order = order_in(current)
    before = (order.status, order.filled_quantity, order.fills, order.broker_order_id, order.reject_reason)

    with pytest.raises(IllegalTransitionError):
        attempt(target)(order)

    assert (order.status, order.filled_quantity, order.fills, order.broker_order_id, order.reject_reason) == before


@pytest.mark.parametrize("status", [S.FILLED, S.CANCELED, S.REJECTED])
def test_terminal_statuses_report_terminal(status: OrderStatus):
    assert order_in(status).is_terminal


@pytest.mark.parametrize("status", [S.PENDING_SUBMIT, S.SUBMITTED, S.PARTIALLY_FILLED])
def test_open_statuses_are_not_terminal(status: OrderStatus):
    assert not order_in(status).is_terminal


# =====================================================================
# mark_submitted / mark_rejected / mark_canceled
# =====================================================================

def test_mark_submitted_records_the_broker_order_id():
    order = submitted_order()

    assert order.broker_order_id == "broker-1"


@pytest.mark.parametrize("bad", [None, 5], ids=["none", "int"])
def test_mark_submitted_needs_a_str_broker_order_id(bad: object):
    order = make_order()

    with pytest.raises(TypeError, match="broker_order_id must be a str"):
        order.mark_submitted(bad)  # pyright: ignore[reportArgumentType]
    assert order.status == S.PENDING_SUBMIT


@pytest.mark.parametrize("blank", BLANKS)
def test_mark_submitted_refuses_a_blank_broker_order_id(blank: str):
    order = make_order()

    with pytest.raises(ValueError, match="broker_order_id must not be blank"):
        order.mark_submitted(blank)
    assert order.status == S.PENDING_SUBMIT


def test_mark_rejected_records_the_reason():
    order = order_in(S.REJECTED)

    assert order.reject_reason == "insufficient buying power"


@pytest.mark.parametrize("blank", BLANKS)
def test_mark_rejected_refuses_a_blank_reason(blank: str):
    order = make_order()

    with pytest.raises(ValueError, match="reason must not be blank"):
        order.mark_rejected(blank)
    assert order.status == S.PENDING_SUBMIT


def test_mark_rejected_needs_a_str_reason():
    with pytest.raises(TypeError, match="reason must be a str"):
        make_order().mark_rejected(None)  # pyright: ignore[reportArgumentType]


def test_canceling_a_partial_fill_keeps_what_was_filled():
    order = order_in(S.PARTIALLY_FILLED)

    order.mark_canceled()

    assert order.status == S.CANCELED
    assert order.filled_quantity == Decimal("4")
    assert order.remaining_quantity == Decimal("6")


# =====================================================================
# apply_fill
# =====================================================================

def test_partial_fill_then_final_fill():
    order = submitted_order()

    order.apply_fill(make_fill(order, "4", price="100"))
    assert order.status == S.PARTIALLY_FILLED
    assert order.filled_quantity == Decimal("4")
    assert order.remaining_quantity == Decimal("6")

    order.apply_fill(make_fill(order, "6", price="101"))
    assert order.status == S.FILLED
    assert order.filled_quantity == Decimal("10")
    assert order.remaining_quantity == Decimal("0")


def test_single_full_fill_goes_straight_to_filled():
    order = submitted_order()

    order.apply_fill(make_fill(order, "10"))

    assert order.status == S.FILLED


def test_many_partial_fills():
    order = submitted_order()

    for _ in range(9):
        order.apply_fill(make_fill(order, "1"))
        assert order.status == S.PARTIALLY_FILLED

    order.apply_fill(make_fill(order, "1"))
    assert order.status == S.FILLED
    assert len(order.fills) == 10


def test_fractional_fills_add_up_exactly():
    order = submitted_order(quantity=Decimal("0.3"))

    order.apply_fill(make_fill(order, "0.1"))
    order.apply_fill(make_fill(order, "0.1"))
    order.apply_fill(make_fill(order, "0.1"))

    assert order.status == S.FILLED
    assert order.filled_quantity == Decimal("0.3")


def test_avg_fill_price_is_quantity_weighted():
    order = submitted_order()

    order.apply_fill(make_fill(order, "4", price="100"))
    order.apply_fill(make_fill(order, "6", price="101"))

    # (4 x 100 + 6 x 101) / 10 = 100.6
    assert order.avg_fill_price == Decimal("100.6")


def test_avg_fill_price_with_a_single_fill_is_that_price():
    order = submitted_order()

    order.apply_fill(make_fill(order, "10", price="190.15"))

    assert order.avg_fill_price == Decimal("190.15")


def test_fills_are_kept_in_order_applied():
    order = submitted_order()
    first = make_fill(order, "4", fill_id="a")
    second = make_fill(order, "6", fill_id="b")

    order.apply_fill(first)
    order.apply_fill(second)

    assert order.fills == (first, second)


def test_overfill_is_refused_and_nothing_changes():
    order = order_in(S.PARTIALLY_FILLED)

    with pytest.raises(OverfillError) as caught:
        order.apply_fill(make_fill(order, "7"))

    assert caught.value.fill_quantity == Decimal("7")
    assert caught.value.remaining == Decimal("6")
    assert order.status == S.PARTIALLY_FILLED
    assert order.filled_quantity == Decimal("4")
    assert len(order.fills) == 1


def test_duplicate_fill_id_is_refused_and_nothing_changes():
    order = submitted_order()
    fill = make_fill(order, "4", fill_id="dup")
    order.apply_fill(fill)

    with pytest.raises(DuplicateFillError) as caught:
        order.apply_fill(make_fill(order, "1", fill_id="dup"))

    assert caught.value.fill_id == "dup"
    assert order.filled_quantity == Decimal("4")
    assert order.fills == (fill,)


def test_duplicate_fill_on_a_filled_order_reports_duplicate_not_illegal_transition():
    # The broker re-sending its last fill is normal; the manager can safely ignore DuplicateFillError.
    order = submitted_order()
    order.apply_fill(make_fill(order, "10", fill_id="last"))

    with pytest.raises(DuplicateFillError):
        order.apply_fill(make_fill(order, "10", fill_id="last"))


def test_fill_for_another_order_is_refused():
    order = submitted_order()
    foreign = Fill(
        fill_id="x", client_order_id=OTHER_ID, price=Decimal("1"), quantity=Decimal("1"), timestamp=NOW,
    )

    with pytest.raises(FillOrderMismatchError):
        order.apply_fill(foreign)
    assert order.fills == ()


def test_fill_before_submission_is_an_illegal_transition():
    order = make_order()

    with pytest.raises(IllegalTransitionError):
        order.apply_fill(make_fill(order, "1"))


def test_apply_fill_needs_a_fill():
    with pytest.raises(TypeError, match="fill must be a Fill"):
        submitted_order().apply_fill("fill-1")  # pyright: ignore[reportArgumentType]


# =====================================================================
# repr
# =====================================================================

def test_repr_shows_the_essentials():
    text = repr(make_order())

    assert "AAPL" in text
    assert "BUY" in text
    assert "PENDING_SUBMIT" in text
    assert str(make_client_order_id(SIGNAL_ID)) in text
