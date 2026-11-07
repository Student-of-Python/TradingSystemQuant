'''
src/execution/domain/order.py

Order entity + state machine.

An Order is an Entity: it has a permanent identity (client_order_id) and its status
changes over time. Status can only change through the intent methods
(mark_submitted, mark_rejected, mark_canceled, apply_fill), and every change is
checked against ALLOWED_TRANSITIONS. A refused change raises and leaves the order untouched.
'''

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from src.execution.domain.enums import OrderSide, OrderStatus, OrderType
from src.execution.domain.errors import (
    DuplicateFillError,
    FillOrderMismatchError,
    IllegalTransitionError,
    OverfillError,
)
from src.execution.domain.fill import Fill
from src.execution.domain.validation import (
    check_non_blank_str,
    check_positive_decimal,
    check_utc_datetime,
    check_uuid,
)

_S = OrderStatus

ALLOWED_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]] = MappingProxyType({
    _S.PENDING_SUBMIT: frozenset({_S.SUBMITTED, _S.REJECTED}),
    _S.SUBMITTED: frozenset({_S.PARTIALLY_FILLED, _S.FILLED, _S.CANCELED, _S.REJECTED}),
    _S.PARTIALLY_FILLED: frozenset({_S.PARTIALLY_FILLED, _S.FILLED, _S.CANCELED}),
    _S.FILLED: frozenset(),
    _S.CANCELED: frozenset(),
    _S.REJECTED: frozenset(),
})

# Fixed forever: changing it changes every client_order_id, so orders created before
# the change could no longer be matched (and could be double-submitted) after a restart.
_CLIENT_ORDER_ID_NAMESPACE = uuid.UUID("08840e16-eabf-4a55-b3a2-8dbcd58da3fd")


def make_client_order_id(signal_id: uuid.UUID) -> uuid.UUID:
    '''
    Deterministic order id for a signal. The same signal always gives the same id,
    so a signal delivered (or approved) twice can never become two orders.
    '''
    check_uuid(signal_id, "signal_id")
    return uuid.uuid5(_CLIENT_ORDER_ID_NAMESPACE, str(signal_id))


class Order:
    '''
    client_order_id (UUID): Our id for the order, sent to the broker. Use make_client_order_id.
    symbol (str): Ticker.
    side (OrderSide): BUY or SELL.
    quantity (Decimal): Units requested. Must be > 0.
    created_at (datetime): Timezone-aware UTC.
    order_type (OrderType): MARKET for the MVP.
    expected_price (Decimal | None): Price the strategy saw, used later to measure slippage.
    '''

    __slots__ = (
        "_client_order_id", "_symbol", "_side", "_quantity", "_created_at", "_order_type",
        "_expected_price", "_status", "_broker_order_id", "_reject_reason", "_fills", "_filled_quantity",
    )

    def __init__(
        self,
        *,
        client_order_id: uuid.UUID,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        created_at: datetime,
        order_type: OrderType = OrderType.MARKET,
        expected_price: Decimal | None = None,
    ) -> None:
        check_uuid(client_order_id, "client_order_id")
        check_non_blank_str(symbol, "symbol")
        if not isinstance(side, OrderSide):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"side must be an OrderSide, got {type(side).__name__}.")
        if not isinstance(order_type, OrderType):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"order_type must be an OrderType, got {type(order_type).__name__}.")
        check_positive_decimal(quantity, "quantity")
        if expected_price is not None:
            check_positive_decimal(expected_price, "expected_price")
        check_utc_datetime(created_at, "created_at")

        self._client_order_id = client_order_id
        self._symbol = symbol
        self._side = side
        self._quantity = quantity
        self._created_at = created_at
        self._order_type = order_type
        self._expected_price = expected_price

        self._status = OrderStatus.PENDING_SUBMIT
        self._broker_order_id: str | None = None
        self._reject_reason: str | None = None
        self._fills: list[Fill] = []
        self._filled_quantity = Decimal("0")

    @classmethod
    def for_signal(
        cls,
        *,
        signal_id: uuid.UUID,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        created_at: datetime,
        expected_price: Decimal | None = None,
    ) -> Order:
        '''Builds a market order whose client_order_id is derived from the signal's id.'''
        return cls(
            client_order_id=make_client_order_id(signal_id),
            symbol=symbol,
            side=side,
            quantity=quantity,
            created_at=created_at,
            expected_price=expected_price,
        )

    # ------------------------------------------------------------------ read-only state

    @property
    def client_order_id(self) -> uuid.UUID:
        return self._client_order_id

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def side(self) -> OrderSide:
        return self._side

    @property
    def quantity(self) -> Decimal:
        return self._quantity

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def order_type(self) -> OrderType:
        return self._order_type

    @property
    def expected_price(self) -> Decimal | None:
        return self._expected_price

    @property
    def status(self) -> OrderStatus:
        return self._status

    @property
    def broker_order_id(self) -> str | None:
        return self._broker_order_id

    @property
    def reject_reason(self) -> str | None:
        return self._reject_reason

    @property
    def fills(self) -> tuple[Fill, ...]:
        return tuple(self._fills)

    @property
    def filled_quantity(self) -> Decimal:
        return self._filled_quantity

    @property
    def remaining_quantity(self) -> Decimal:
        return self._quantity - self._filled_quantity

    @property
    def avg_fill_price(self) -> Decimal | None:
        '''Quantity-weighted average price of all fills, or None if nothing has filled.'''
        if not self._fills:
            return None
        return sum((f.notional for f in self._fills), Decimal("0")) / self._filled_quantity

    @property
    def is_terminal(self) -> bool:
        return not ALLOWED_TRANSITIONS[self._status]

    # ------------------------------------------------------------------ intent methods

    def mark_submitted(self, broker_order_id: str) -> None:
        '''The broker acknowledged the order and gave it this id.'''
        check_non_blank_str(broker_order_id, "broker_order_id")
        self._check_transition(OrderStatus.SUBMITTED)

        self._broker_order_id = broker_order_id
        self._status = OrderStatus.SUBMITTED

    def mark_rejected(self, reason: str) -> None:
        '''The broker (or execution itself) refused the order.'''
        check_non_blank_str(reason, "reason")
        self._check_transition(OrderStatus.REJECTED)

        self._reject_reason = reason
        self._status = OrderStatus.REJECTED

    def mark_canceled(self) -> None:
        '''The broker confirmed the order is canceled. Earlier partial fills are kept.'''
        self._check_transition(OrderStatus.CANCELED)

        self._status = OrderStatus.CANCELED

    def apply_fill(self, fill: Fill) -> None:
        '''
        Records a broker execution and moves to PARTIALLY_FILLED or FILLED.
        Checks run in this order, and nothing changes unless all pass:
        wrong type -> wrong order -> duplicate fill_id -> illegal transition -> overfill.
        '''
        if not isinstance(fill, Fill):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"fill must be a Fill, got {type(fill).__name__}.")
        if fill.client_order_id != self._client_order_id:
            raise FillOrderMismatchError(self._client_order_id, fill_order_id=fill.client_order_id)
        if any(f.fill_id == fill.fill_id for f in self._fills):
            raise DuplicateFillError(self._client_order_id, fill_id=fill.fill_id)

        new_filled = self._filled_quantity + fill.quantity
        target = OrderStatus.FILLED if new_filled >= self._quantity else OrderStatus.PARTIALLY_FILLED
        self._check_transition(target)

        if new_filled > self._quantity:
            raise OverfillError(self._client_order_id, fill_quantity=fill.quantity, remaining=self.remaining_quantity)

        self._fills.append(fill)
        self._filled_quantity = new_filled
        self._status = target

    # ------------------------------------------------------------------ internals

    def _check_transition(self, target: OrderStatus) -> None:
        if target not in ALLOWED_TRANSITIONS[self._status]:
            raise IllegalTransitionError(self._client_order_id, self._status, target)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Order):
            return NotImplemented
        return self._client_order_id == other._client_order_id

    def __hash__(self) -> int:
        return hash(self._client_order_id)

    def __repr__(self) -> str:
        return (f"Order(client_order_id={self._client_order_id}, symbol={self._symbol!r}, "
                f"side={self._side}, quantity={self._quantity}, status={self._status}, "
                f"filled={self._filled_quantity})")
