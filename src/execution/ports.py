'''
src/execution/ports.py

BrokerPort: what execution needs from a broker, and nothing about any specific broker.
Adapters (fake_broker, alpaca_broker) implement it; the manager depends only on this file.

Rule for every adapter: never raise. Every problem (refusal, network, unknown id) comes
back as a failed Result, because the router silently swallows exceptions from handlers.
'''

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from src.core.results import Error, ErrorCode, Result
from src.execution.domain.enums import OrderSide, OrderStatus
from src.execution.domain.fill import Fill
from src.execution.domain.order import Order
from src.execution.domain.validation import (
    check_instance,
    check_non_blank_str,
    check_positive_decimal,
    check_utc_datetime,
    check_uuid,
)

type BrokerOrderId = str

_BROKER_CODE_KEY = "broker_code"


class BrokerErrorCode(StrEnum):
    '''
    Broker failures execution cares about. Core's ErrorCode has no broker codes yet, so for
    now these travel in Error.details["broker_code"] with Error.code = UNKNOWN_ERROR.
    TODO: move into core's ErrorCode once core adds them (ask Gleb), then drop the details key.
    '''
    BROKER_REJECTED = 'BROKER_REJECTED'          # Broker refused the order (generic)
    INSUFFICIENT_FUNDS = 'INSUFFICIENT_FUNDS'    # Not enough buying power
    DUPLICATE_ORDER = 'DUPLICATE_ORDER'          # client_order_id already used at the broker
    ORDER_NOT_FOUND = 'ORDER_NOT_FOUND'          # Broker has no order with that id


def broker_error(code: BrokerErrorCode, msg: str, details: dict[str, Any] | None = None) -> Error:
    '''Builds a core Error that carries a BrokerErrorCode.'''
    return Error(code=ErrorCode.UNKNOWN_ERROR, msg=msg, details={**(details or {}), _BROKER_CODE_KEY: code})


def broker_error_code(error: Error | None) -> BrokerErrorCode | None:
    '''The BrokerErrorCode inside an Error built by broker_error, else None.'''
    if error is None or not error.details:
        return None
    code = error.details.get(_BROKER_CODE_KEY)
    return code if isinstance(code, BrokerErrorCode) else None


@dataclass(frozen=True, slots=True, kw_only=True)
class BrokerOrderUpdate:
    '''
    What the broker currently knows about one order.

    broker_order_id (str): The broker's id for the order.
    status (OrderStatus): The broker's status, already translated to ours (never PENDING_SUBMIT).
    fills (tuple[Fill, ...]): Every fill the broker reports for the order. May repeat fills
        already applied (brokers re-send), so the reader must skip known fill_ids.
    reason (str | None): Why the order was rejected or canceled, when the broker says.
    '''
    broker_order_id: BrokerOrderId
    status: OrderStatus
    fills: tuple[Fill, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        check_non_blank_str(self.broker_order_id, "broker_order_id")
        check_instance(self.status, OrderStatus, "status")
        if self.status is OrderStatus.PENDING_SUBMIT:
            raise ValueError("status cannot be PENDING_SUBMIT: the broker already has the order.")
        check_instance(self.fills, tuple, "fills")
        for i, fill in enumerate(self.fills):
            check_instance(fill, Fill, f"fills[{i}]")
        if self.reason is not None:
            check_non_blank_str(self.reason, "reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class BrokerOrderRecord:
    '''
    An order as the broker holds it, with everything needed to rebuild our Order after a
    restart (startup reconciliation).

    client_order_id (UUID): Our id for the order, as sent with the submit.
    symbol (str): Ticker.
    side (OrderSide): BUY or SELL.
    quantity (Decimal): Units requested.
    created_at (datetime): When the broker received it, UTC.
    update (BrokerOrderUpdate): Its current status and fills.
    '''
    client_order_id: uuid.UUID
    symbol: str
    side: OrderSide
    quantity: Decimal
    created_at: datetime
    update: BrokerOrderUpdate

    def __post_init__(self) -> None:
        check_uuid(self.client_order_id, "client_order_id")
        check_non_blank_str(self.symbol, "symbol")
        check_instance(self.side, OrderSide, "side")
        check_positive_decimal(self.quantity, "quantity")
        check_utc_datetime(self.created_at, "created_at")
        check_instance(self.update, BrokerOrderUpdate, "update")
        for i, fill in enumerate(self.update.fills):
            if fill.client_order_id != self.client_order_id:
                raise ValueError(f"update.fills[{i}] belongs to order {fill.client_order_id}, not {self.client_order_id}.")


class BrokerPort(Protocol):
    def submit_order(self, order: Order) -> Result[BrokerOrderId]:
        '''Sends the order (with its client_order_id). Success value: the broker's order id.'''
        ...

    def cancel_order(self, broker_order_id: BrokerOrderId) -> Result[None]:
        '''Asks the broker to cancel. Success only means the request was accepted;
        the CANCELED status arrives later through get_order_status.'''
        ...

    def get_order_status(self, broker_order_id: BrokerOrderId) -> Result[BrokerOrderUpdate]:
        '''Current status and every fill so far.'''
        ...

    def find_order(self, client_order_id: uuid.UUID) -> Result[BrokerOrderUpdate]:
        '''
        Looks an order up by OUR id. Used when a submit's answer was lost (connection failure):
        success means the broker did receive it; ORDER_NOT_FOUND means it never arrived.
        '''
        ...

    def list_open_orders(self) -> Result[tuple[BrokerOrderRecord, ...]]:
        '''Every order the broker still has open, for startup reconciliation.'''
        ...
