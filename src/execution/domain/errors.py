'''
src/execution/domain/errors.py

Errors raised by the Order entity when asked to break one of its rules.
They all inherit OrderError so the manager can catch every domain refusal in one place.
'''

import uuid
from decimal import Decimal

from src.execution.domain.enums import OrderStatus


class OrderError(Exception):
    '''Base class for every Order rule violation.'''

    def __init__(self, client_order_id: uuid.UUID, message: str) -> None:
        super().__init__(message)
        self.client_order_id = client_order_id


class IllegalTransitionError(OrderError):
    '''The order's status cannot move from `current` to `target`.'''

    def __init__(self, client_order_id: uuid.UUID, current: OrderStatus, target: OrderStatus) -> None:
        super().__init__(client_order_id, f"Order {client_order_id} cannot move from {current} to {target}.")
        self.current = current
        self.target = target


class OverfillError(OrderError):
    '''A fill would push the filled quantity above the order's quantity.'''

    def __init__(self, client_order_id: uuid.UUID, *, fill_quantity: Decimal, remaining: Decimal) -> None:
        super().__init__(
            client_order_id,
            f"Fill of {fill_quantity} on order {client_order_id} exceeds the remaining quantity of {remaining}.",
        )
        self.fill_quantity = fill_quantity
        self.remaining = remaining


class DuplicateFillError(OrderError):
    '''A fill with this fill_id was already applied. Safe to ignore: brokers re-send fills.'''

    def __init__(self, client_order_id: uuid.UUID, *, fill_id: str) -> None:
        super().__init__(client_order_id, f"Fill {fill_id!r} was already applied to order {client_order_id}.")
        self.fill_id = fill_id


class FillOrderMismatchError(OrderError):
    '''A fill was applied to an order it does not belong to.'''

    def __init__(self, client_order_id: uuid.UUID, *, fill_order_id: uuid.UUID) -> None:
        super().__init__(client_order_id, f"Fill belongs to order {fill_order_id}, not order {client_order_id}.")
        self.fill_order_id = fill_order_id
