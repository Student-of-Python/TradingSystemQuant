'''
tests/unit/test_execution_fill.py
'''

import uuid
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.execution.domain.fill import Fill

BLANKS = ["", " ", "\t\n"]
ORDER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
NOW = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)


def make_fill(**overrides: object) -> Fill:
    kwargs: dict[str, object] = {
        "fill_id": "fill-1",
        "client_order_id": ORDER_ID,
        "price": Decimal("190.15"),
        "quantity": Decimal("10"),
        "timestamp": NOW,
    }
    kwargs.update(overrides)
    return Fill(**kwargs)  # pyright: ignore[reportArgumentType]


# --- Happy path ---

def test_holds_all_fields_exactly_as_given():
    fill = make_fill()

    assert fill.fill_id == "fill-1"
    assert fill.client_order_id == ORDER_ID
    assert fill.price == Decimal("190.15")
    assert fill.quantity == Decimal("10")
    assert fill.timestamp == NOW


def test_fractional_quantity_is_allowed():
    fill = make_fill(quantity=Decimal("0.5"))

    assert fill.quantity == Decimal("0.5")


def test_notional_is_exact_price_times_quantity():
    fill = make_fill(price=Decimal("0.1"), quantity=Decimal("3"))

    assert fill.notional == Decimal("0.3")


def test_fills_with_same_fields_are_equal():
    assert make_fill() == make_fill()


# --- Construction rules ---

def test_positional_arguments_are_refused():
    with pytest.raises(TypeError):
        Fill("fill-1", ORDER_ID, Decimal("1"), Decimal("1"), NOW)  # type: ignore[misc]


@pytest.mark.parametrize("missing", ["fill_id", "client_order_id", "price", "quantity", "timestamp"])
def test_every_field_is_required(missing: str):
    kwargs: dict[str, object] = {
        "fill_id": "fill-1",
        "client_order_id": ORDER_ID,
        "price": Decimal("1"),
        "quantity": Decimal("1"),
        "timestamp": NOW,
    }
    del kwargs[missing]

    with pytest.raises(TypeError):
        Fill(**kwargs)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("field", ["fill_id", "client_order_id", "price", "quantity", "timestamp"])
def test_fields_cannot_be_changed(field: str):
    fill = make_fill()

    with pytest.raises(FrozenInstanceError):
        setattr(fill, field, None)


# --- fill_id ---

@pytest.mark.parametrize("bad", [None, 5, b"fill-1"], ids=["none", "int", "bytes"])
def test_non_str_fill_id_is_refused(bad: object):
    with pytest.raises(TypeError, match="fill_id must be a str"):
        make_fill(fill_id=bad)


@pytest.mark.parametrize("blank", BLANKS)
def test_blank_fill_id_is_refused(blank: str):
    with pytest.raises(ValueError, match="fill_id must not be blank"):
        make_fill(fill_id=blank)


# --- client_order_id ---

@pytest.mark.parametrize("bad", [None, str(ORDER_ID), 5], ids=["none", "uuid-as-str", "int"])
def test_non_uuid_client_order_id_is_refused(bad: object):
    with pytest.raises(TypeError, match="client_order_id must be a UUID"):
        make_fill(client_order_id=bad)


# --- price and quantity ---

@pytest.mark.parametrize("field", ["price", "quantity"])
@pytest.mark.parametrize("bad", [1, 1.5, "1", None], ids=["int", "float", "str", "none"])
def test_non_decimal_price_and_quantity_are_refused(field: str, bad: object):
    with pytest.raises(TypeError, match=f"{field} must be a Decimal"):
        make_fill(**{field: bad})


@pytest.mark.parametrize("field", ["price", "quantity"])
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_non_finite_price_and_quantity_are_refused(field: str, bad: str):
    with pytest.raises(ValueError, match=f"{field} must be finite"):
        make_fill(**{field: Decimal(bad)})


@pytest.mark.parametrize("field", ["price", "quantity"])
@pytest.mark.parametrize("bad", ["0", "-0", "-1", "-0.01"])
def test_zero_or_negative_price_and_quantity_are_refused(field: str, bad: str):
    with pytest.raises(ValueError, match=f"{field} must be greater than 0"):
        make_fill(**{field: Decimal(bad)})


# --- timestamp ---

@pytest.mark.parametrize("bad", [None, "2026-11-09T14:30:00Z", 1762698600], ids=["none", "str", "epoch-int"])
def test_non_datetime_timestamp_is_refused(bad: object):
    with pytest.raises(TypeError, match="timestamp must be a datetime"):
        make_fill(timestamp=bad)


def test_naive_timestamp_is_refused():
    with pytest.raises(ValueError, match="timestamp must be timezone-aware UTC"):
        make_fill(timestamp=datetime(2026, 11, 9, 14, 30))


def test_non_utc_timestamp_is_refused():
    new_york = timezone(timedelta(hours=-5))

    with pytest.raises(ValueError, match="timestamp must be timezone-aware UTC"):
        make_fill(timestamp=datetime(2026, 11, 9, 9, 30, tzinfo=new_york))


# --- Check order ---

def test_fill_id_is_checked_first():
    with pytest.raises(TypeError, match="fill_id"):
        Fill(fill_id=None, client_order_id=None, price=None, quantity=None, timestamp=None)  # pyright: ignore[reportArgumentType]

