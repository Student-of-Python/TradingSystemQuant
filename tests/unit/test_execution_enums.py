'''
tests/unit/test_execution_enums.py
'''

from enum import StrEnum

import pytest

from src.execution.domain.enums import OrderSide, OrderStatus, OrderType


@pytest.mark.parametrize("enum", [OrderStatus, OrderSide, OrderType])
def test_enums_are_str_enums(enum: type[StrEnum]):
    assert issubclass(enum, StrEnum)


@pytest.mark.parametrize("enum", [OrderStatus, OrderSide, OrderType])
def test_member_values_match_their_names(enum: type[StrEnum]):
    for member in enum:
        assert member.value == member.name


def test_order_status_members():
    assert {s.name for s in OrderStatus} == {
        "PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED",
    }


def test_order_side_members():
    assert {s.name for s in OrderSide} == {"BUY", "SELL"}


def test_order_type_members_mvp_is_market_only():
    assert {t.name for t in OrderType} == {"MARKET"}


def test_unknown_value_is_refused():
    with pytest.raises(ValueError):
        OrderSide("SHORT")
