'''
tests/unit/test_execution_errors.py
'''

import uuid
from decimal import Decimal

import pytest

from src.execution.domain.enums import OrderStatus
from src.execution.domain.errors import (
    DuplicateFillError,
    FillOrderMismatchError,
    IllegalTransitionError,
    OrderError,
    OverfillError,
)

ORDER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


@pytest.mark.parametrize(
    "error",
    [IllegalTransitionError, OverfillError, DuplicateFillError, FillOrderMismatchError],
)
def test_all_order_errors_share_a_base_class(error: type[Exception]):
    assert issubclass(error, OrderError)


def test_illegal_transition_error_keeps_its_details():
    error = IllegalTransitionError(ORDER_ID, OrderStatus.FILLED, OrderStatus.SUBMITTED)

    assert error.client_order_id == ORDER_ID
    assert error.current == OrderStatus.FILLED
    assert error.target == OrderStatus.SUBMITTED
    assert str(error) == f"Order {ORDER_ID} cannot move from FILLED to SUBMITTED."


def test_overfill_error_keeps_its_details():
    error = OverfillError(ORDER_ID, fill_quantity=Decimal("7"), remaining=Decimal("6"))

    assert error.fill_quantity == Decimal("7")
    assert error.remaining == Decimal("6")
    assert str(error) == f"Fill of 7 on order {ORDER_ID} exceeds the remaining quantity of 6."


def test_duplicate_fill_error_keeps_its_details():
    error = DuplicateFillError(ORDER_ID, fill_id="fill-1")

    assert error.fill_id == "fill-1"
    assert str(error) == f"Fill 'fill-1' was already applied to order {ORDER_ID}."


def test_fill_order_mismatch_error_keeps_its_details():
    other = uuid.UUID("87654321-4321-8765-4321-876543218765")
    error = FillOrderMismatchError(ORDER_ID, fill_order_id=other)

    assert error.fill_order_id == other
    assert str(error) == f"Fill belongs to order {other}, not order {ORDER_ID}."
