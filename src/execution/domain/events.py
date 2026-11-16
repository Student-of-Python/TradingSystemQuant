'''
src/execution/domain/events.py

Events execution publishes. Each one is a frozen snapshot of an Order at the moment
something happened to it, so consumers never hold (or mutate) the live Order.

OrderSubmittedEvent: the broker acknowledged the order.
FillEvent: one broker execution was applied to the order.
OrderRejectedEvent: the order was refused (by execution itself or by the broker).
OrderCanceledEvent: the broker confirmed the order is canceled.
OrderCancelRequestedEvent: execution asked the broker to cancel (timeout, kill switch, manual).
    Only a request: OrderCanceledEvent (or fills) follows once the broker answers.
'''

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from src.core import BaseEvent
from src.execution.domain.enums import OrderSide, OrderStatus, OrderType
from src.execution.domain.fill import Fill
from src.execution.domain.order import Order
from src.execution.domain.validation import (
    check_instance,
    check_non_blank_str,
    check_non_negative_decimal,
    check_positive_decimal,
    check_uuid,
)

_FILL_STATUSES = frozenset({OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED})


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderSubmittedEvent(BaseEvent):
    '''
    client_order_id (UUID): Our id for the order.
    broker_order_id (str): The broker's id for the order.
    symbol (str): Ticker.
    side (OrderSide): BUY or SELL.
    quantity (Decimal): Units requested.
    order_type (OrderType): MARKET for the MVP.
    '''
    client_order_id: uuid.UUID
    broker_order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType

    def __post_init__(self) -> None:
        check_uuid(self.client_order_id, "client_order_id")
        check_non_blank_str(self.broker_order_id, "broker_order_id")
        check_non_blank_str(self.symbol, "symbol")
        check_instance(self.side, OrderSide, "side")
        check_positive_decimal(self.quantity, "quantity")
        check_instance(self.order_type, OrderType, "order_type")

    @classmethod
    def from_order(cls, order: Order) -> OrderSubmittedEvent:
        if order.broker_order_id is None:
            raise ValueError(f"Order {order.client_order_id} has no broker_order_id; it was never submitted.")
        return cls(
            client_order_id=order.client_order_id,
            broker_order_id=order.broker_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            order_type=order.order_type,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FillEvent(BaseEvent):
    '''
    fill (Fill): The execution that was just applied (carries client_order_id, price, quantity).
    symbol (str): Ticker.
    side (OrderSide): BUY or SELL.
    order_status (OrderStatus): PARTIALLY_FILLED or FILLED, after this fill.
    filled_quantity (Decimal): Total units filled so far, including this fill.
    remaining_quantity (Decimal): Units still open after this fill (0 when FILLED).
    avg_fill_price (Decimal): Quantity-weighted average price of all fills so far.
    expected_price (Decimal | None): Price the strategy saw when it signaled, if known.
    '''
    fill: Fill
    symbol: str
    side: OrderSide
    order_status: OrderStatus
    filled_quantity: Decimal
    remaining_quantity: Decimal
    avg_fill_price: Decimal
    expected_price: Decimal | None = None

    def __post_init__(self) -> None:
        check_instance(self.fill, Fill, "fill")
        check_non_blank_str(self.symbol, "symbol")
        check_instance(self.side, OrderSide, "side")
        check_instance(self.order_status, OrderStatus, "order_status")
        if self.order_status not in _FILL_STATUSES:
            raise ValueError(f"order_status must be PARTIALLY_FILLED or FILLED, got {self.order_status}.")
        check_positive_decimal(self.filled_quantity, "filled_quantity")
        check_non_negative_decimal(self.remaining_quantity, "remaining_quantity")
        check_positive_decimal(self.avg_fill_price, "avg_fill_price")
        if self.expected_price is not None:
            check_positive_decimal(self.expected_price, "expected_price")
        if self.filled_quantity < self.fill.quantity:
            raise ValueError(
                f"filled_quantity ({self.filled_quantity}) cannot be less than the fill's quantity ({self.fill.quantity})."
            )
        if (self.order_status is OrderStatus.FILLED) != (self.remaining_quantity == 0):
            raise ValueError(
                f"remaining_quantity must be 0 exactly when FILLED, got {self.remaining_quantity} with {self.order_status}."
            )

    @property
    def client_order_id(self) -> uuid.UUID:
        return self.fill.client_order_id

    @property
    def slippage(self) -> Decimal | None:
        '''
        Cost per unit of the average fill vs. the expected price: positive = worse than expected
        (paid more on a BUY, received less on a SELL), negative = better. None if no expected price.
        '''
        if self.expected_price is None:
            return None
        diff = self.avg_fill_price - self.expected_price
        return diff if self.side is OrderSide.BUY else -diff

    @property
    def slippage_bps(self) -> Decimal | None:
        '''slippage in basis points of the expected price (1 bp = 0.01%).'''
        slippage = self.slippage
        if slippage is None or self.expected_price is None:
            return None
        return slippage / self.expected_price * Decimal("10000")

    @classmethod
    def from_order(cls, order: Order, fill: Fill) -> FillEvent:
        '''Snapshot of `order` right after `fill` was applied to it.'''
        if fill not in order.fills:
            raise ValueError(f"Fill {fill.fill_id!r} has not been applied to order {order.client_order_id}.")
        avg = order.avg_fill_price
        assert avg is not None  # at least one fill exists
        return cls(
            fill=fill,
            symbol=order.symbol,
            side=order.side,
            order_status=order.status,
            filled_quantity=order.filled_quantity,
            remaining_quantity=order.remaining_quantity,
            avg_fill_price=avg,
            expected_price=order.expected_price,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderRejectedEvent(BaseEvent):
    '''
    client_order_id (UUID): Our id for the order (derived from the signal, even if no Order was built).
    symbol (str): Ticker.
    reason (str): Why it was refused, readable by a human.
    '''
    client_order_id: uuid.UUID
    symbol: str
    reason: str

    def __post_init__(self) -> None:
        check_uuid(self.client_order_id, "client_order_id")
        check_non_blank_str(self.symbol, "symbol")
        check_non_blank_str(self.reason, "reason")

    @classmethod
    def from_order(cls, order: Order) -> OrderRejectedEvent:
        if order.reject_reason is None:
            raise ValueError(f"Order {order.client_order_id} has not been rejected.")
        return cls(client_order_id=order.client_order_id, symbol=order.symbol, reason=order.reject_reason)


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCanceledEvent(BaseEvent):
    '''
    client_order_id (UUID): Our id for the order.
    broker_order_id (str): The broker's id for the order.
    symbol (str): Ticker.
    filled_quantity (Decimal): Units that filled before the cancel (kept, may be 0).
    '''
    client_order_id: uuid.UUID
    broker_order_id: str
    symbol: str
    filled_quantity: Decimal

    def __post_init__(self) -> None:
        check_uuid(self.client_order_id, "client_order_id")
        check_non_blank_str(self.broker_order_id, "broker_order_id")
        check_non_blank_str(self.symbol, "symbol")
        check_non_negative_decimal(self.filled_quantity, "filled_quantity")

    @classmethod
    def from_order(cls, order: Order) -> OrderCanceledEvent:
        if order.status is not OrderStatus.CANCELED:
            raise ValueError(f"Order {order.client_order_id} is {order.status}, not CANCELED.")
        assert order.broker_order_id is not None  # CANCELED is only reachable after SUBMITTED
        return cls(
            client_order_id=order.client_order_id,
            broker_order_id=order.broker_order_id,
            symbol=order.symbol,
            filled_quantity=order.filled_quantity,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCancelRequestedEvent(BaseEvent):
    '''
    client_order_id (UUID): Our id for the order.
    broker_order_id (str): The broker's id for the order.
    symbol (str): Ticker.
    reason (str): Why execution asked for the cancel (timeout, kill switch, ...).
    '''
    client_order_id: uuid.UUID
    broker_order_id: str
    symbol: str
    reason: str

    def __post_init__(self) -> None:
        check_uuid(self.client_order_id, "client_order_id")
        check_non_blank_str(self.broker_order_id, "broker_order_id")
        check_non_blank_str(self.symbol, "symbol")
        check_non_blank_str(self.reason, "reason")

    @classmethod
    def from_order(cls, order: Order, reason: str) -> OrderCancelRequestedEvent:
        if order.broker_order_id is None:
            raise ValueError(f"Order {order.client_order_id} has no broker_order_id; the broker cannot cancel it.")
        return cls(client_order_id=order.client_order_id, broker_order_id=order.broker_order_id,
                   symbol=order.symbol, reason=reason)
