'''
src/execution/adapters/alpaca_broker.py

Alpaca (paper or live) BrokerPort: the only file that knows Alpaca exists.

Translation rules (Alpaca -> our domain):

  Status mapping (Alpaca order.status -> OrderStatus):
    new, pending_new, accepted, accepted_for_bidding, pending_review,
    calculated, held, suspended, stopped, done_for_day,
    pending_cancel, pending_replace            -> still open: SUBMITTED, or PARTIALLY_FILLED
                                                  when filled_qty > 0
    partially_filled                           -> PARTIALLY_FILLED
    filled                                     -> FILLED
    canceled, expired, replaced                -> CANCELED (partial fills are kept)
    rejected                                   -> REJECTED, or CANCELED when something already
                                                  filled (our state machine has no
                                                  PARTIALLY_FILLED -> REJECTED; the fills are real)
    anything else                              -> failed Result (INVALID_DATA); the manager
                                                  logs it and retries on the next poll

  Fills: Alpaca's order object only has cumulative filled_qty / filled_avg_price, with no
  per-execution ids. Each time filled_qty grows, this adapter records ONE synthetic fill
  for the difference:
    quantity = new filled_qty - old filled_qty
    price    = (new filled_qty * new avg - old notional) / quantity
    fill_id  = "<alpaca order id>:<cumulative filled_qty>"   (deterministic)
  Every poll returns all fills recorded so far, as the BrokerPort contract asks.

  Errors (never raised, always a failed Result):
    HTTP 404                                   -> ORDER_NOT_FOUND
    "insufficient buying power / qty"          -> INSUFFICIENT_FUNDS
    "client_order_id must be unique"           -> DUPLICATE_ORDER
    HTTP 429 or 5xx, network errors (OSError)  -> CONNECTION_FAILURE (safe to retry)
    any other APIError                         -> BROKER_REJECTED
    anything else                              -> UNKNOWN_ERROR

Orders are always MARKET / DAY with our client_order_id, so a retried POST can never
create a second order at Alpaca: it refuses a client_order_id it has already seen.
'''

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide as AlpacaSide
from alpaca.trading.enums import QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

from src.core.results import Error, ErrorCode, Result
from src.execution.domain.enums import OrderSide, OrderStatus, OrderType
from src.execution.domain.fill import Fill
from src.execution.domain.order import Order
from src.execution.ports import (
    BrokerErrorCode,
    BrokerOrderId,
    BrokerOrderRecord,
    BrokerOrderUpdate,
    broker_error,
)

logger = logging.getLogger(__name__)

API_KEY_ENV = "ALPACA_API_KEY"
SECRET_KEY_ENV = "ALPACA_SECRET_KEY"
PAPER_ENV = "ALPACA_PAPER"

# None = the order is still open; its status then depends on whether anything filled.
_OPEN = None
STATUS_MAP: Mapping[str, OrderStatus | None] = MappingProxyType({
    "new": _OPEN,
    "pending_new": _OPEN,
    "accepted": _OPEN,
    "accepted_for_bidding": _OPEN,
    "pending_review": _OPEN,
    "calculated": _OPEN,
    "held": _OPEN,
    "suspended": _OPEN,
    "stopped": _OPEN,
    "done_for_day": _OPEN,
    "pending_cancel": _OPEN,
    "pending_replace": _OPEN,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELED,
    "expired": OrderStatus.CANCELED,
    "replaced": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
})

_SIDE_TO_ALPACA: Mapping[OrderSide, AlpacaSide] = MappingProxyType({
    OrderSide.BUY: AlpacaSide.BUY,
    OrderSide.SELL: AlpacaSide.SELL,
})
_SIDE_FROM_ALPACA: Mapping[str, OrderSide] = MappingProxyType({"buy": OrderSide.BUY, "sell": OrderSide.SELL})

_RETRYABLE_HTTP = frozenset({408, 429})


class TradingClientLike(Protocol):
    '''The part of alpaca.trading.client.TradingClient this adapter uses (tests pass a fake).'''

    def submit_order(self, order_data: Any) -> Any: ...
    def cancel_order_by_id(self, order_id: Any) -> Any: ...
    def get_order_by_id(self, order_id: Any, filter: Any = None) -> Any: ...
    def get_order_by_client_id(self, client_id: str) -> Any: ...
    def get_orders(self, filter: Any = None) -> Any: ...


class _BadData(Exception):
    '''Alpaca sent something this adapter cannot translate.'''


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AlpacaBroker:
    def __init__(self, client: TradingClientLike, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._client = client
        self._clock = clock
        # Synthetic fills per Alpaca order id (see module docstring).
        self._fills: dict[BrokerOrderId, list[Fill]] = {}

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AlpacaBroker:
        '''
        Builds a TradingClient from ALPACA_API_KEY / ALPACA_SECRET_KEY.
        ALPACA_PAPER defaults to true; only the exact value "false" turns on live trading.
        '''
        env = os.environ if env is None else env
        api_key, secret_key = env.get(API_KEY_ENV), env.get(SECRET_KEY_ENV)
        if not api_key or not secret_key:
            raise ValueError(f"{API_KEY_ENV} and {SECRET_KEY_ENV} must be set.")
        paper = env.get(PAPER_ENV, "true").strip().lower() != "false"
        return cls(TradingClient(api_key=api_key, secret_key=secret_key, paper=paper))

    # ------------------------------------------------------------------ BrokerPort

    def submit_order(self, order: Order) -> Result[BrokerOrderId]:
        if order.order_type is not OrderType.MARKET:
            return self._invalid(f"Only MARKET orders are supported, got {order.order_type}.")
        qty = float(order.quantity)
        if Decimal(repr(qty)) != order.quantity:
            # alpaca-py sends qty as a float; never send a different quantity than we hold.
            return self._invalid(f"Quantity {order.quantity} cannot be sent exactly to Alpaca.")
        try:
            request = MarketOrderRequest(
                symbol=order.symbol,
                qty=qty,
                side=_SIDE_TO_ALPACA[order.side],
                time_in_force=TimeInForce.DAY,
                client_order_id=str(order.client_order_id),
            )
            response = self._client.submit_order(request)
            return Result.successful(str(_field(response, "id")))
        except Exception as error:  # noqa: BLE001 - every SDK problem becomes a Result
            return Result.failure(to_error(error))

    def cancel_order(self, broker_order_id: BrokerOrderId) -> Result[None]:
        try:
            self._client.cancel_order_by_id(broker_order_id)
            return Result.successful(None)
        except Exception as error:  # noqa: BLE001
            return Result.failure(to_error(error))

    def get_order_status(self, broker_order_id: BrokerOrderId) -> Result[BrokerOrderUpdate]:
        try:
            return Result.successful(self._to_update(self._client.get_order_by_id(broker_order_id)))
        except Exception as error:  # noqa: BLE001
            return Result.failure(to_error(error))

    def find_order(self, client_order_id: uuid.UUID) -> Result[BrokerOrderUpdate]:
        try:
            return Result.successful(self._to_update(self._client.get_order_by_client_id(str(client_order_id))))
        except Exception as error:  # noqa: BLE001
            return Result.failure(to_error(error))

    def list_open_orders(self) -> Result[tuple[BrokerOrderRecord, ...]]:
        try:
            raw_orders = self._client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        except Exception as error:  # noqa: BLE001
            return Result.failure(to_error(error))

        records: list[BrokerOrderRecord] = []
        for raw in raw_orders or ():
            try:
                records.append(self._to_record(raw))
            except Exception as error:  # noqa: BLE001 - skip one bad/foreign order, keep the rest
                logger.warning("Skipping Alpaca order %s during reconciliation: %s",
                               _safe_field(raw, "id"), error)
        return Result.successful(tuple(records))

    # ------------------------------------------------------------------ translation

    def _to_update(self, raw: Any) -> BrokerOrderUpdate:
        broker_order_id = str(_field(raw, "id"))
        client_order_id = _parse_client_order_id(_field(raw, "client_order_id"))
        alpaca_status = _enum_value(_field(raw, "status"))
        if alpaca_status not in STATUS_MAP:
            raise _BadData(f"Unknown Alpaca status {alpaca_status!r} for order {broker_order_id}.")

        fills = self._record_fills(broker_order_id, client_order_id, raw)
        has_fills = bool(fills)
        status = STATUS_MAP[alpaca_status]
        if status is None:
            status = OrderStatus.PARTIALLY_FILLED if has_fills else OrderStatus.SUBMITTED
        elif status is OrderStatus.REJECTED and has_fills:
            status = OrderStatus.CANCELED

        reason = None
        if status in (OrderStatus.CANCELED, OrderStatus.REJECTED):
            reason = f"Alpaca order status: {alpaca_status}."

        return BrokerOrderUpdate(broker_order_id=broker_order_id, status=status, fills=tuple(fills), reason=reason)

    def _record_fills(self, broker_order_id: BrokerOrderId, client_order_id: uuid.UUID, raw: Any) -> list[Fill]:
        fills = self._fills.setdefault(broker_order_id, [])
        cum_qty = _decimal(_field(raw, "filled_qty", None), default=Decimal("0"))
        known_qty = sum((f.quantity for f in fills), Decimal("0"))
        if cum_qty < known_qty:
            logger.error("Alpaca order %s filled_qty went down from %s to %s; ignoring.",
                         broker_order_id, known_qty, cum_qty)
            return fills
        if cum_qty == known_qty:
            return fills

        avg = _decimal(_field(raw, "filled_avg_price", None), default=None)
        if avg is None or avg <= 0:
            raise _BadData(f"Order {broker_order_id} filled {cum_qty} without a filled_avg_price.")

        quantity = cum_qty - known_qty
        known_notional = sum((f.notional for f in fills), Decimal("0"))
        price = (cum_qty * avg - known_notional) / quantity
        if not price.is_finite() or price <= 0:
            price = avg  # rounding in Alpaca's average; the average is the best we have

        when = _field(raw, "filled_at", None) or _field(raw, "updated_at", None)
        timestamp = when.astimezone(timezone.utc) if isinstance(when, datetime) and when.tzinfo else self._clock()

        fills.append(Fill(
            fill_id=f"{broker_order_id}:{cum_qty.normalize():f}",
            client_order_id=client_order_id,
            price=price,
            quantity=quantity,
            timestamp=timestamp,
        ))
        return fills

    def _to_record(self, raw: Any) -> BrokerOrderRecord:
        side = _SIDE_FROM_ALPACA.get(_enum_value(_field(raw, "side", None)))
        if side is None:
            raise _BadData(f"Unsupported side {_field(raw, 'side', None)!r}.")
        quantity = _decimal(_field(raw, "qty", None), default=None)
        if quantity is None:
            raise _BadData("Order has no qty (notional orders are not ours).")
        created_at = _field(raw, "created_at")
        if not isinstance(created_at, datetime) or created_at.tzinfo is None:
            raise _BadData(f"Order has no timezone-aware created_at: {created_at!r}.")
        return BrokerOrderRecord(
            client_order_id=_parse_client_order_id(_field(raw, "client_order_id")),
            symbol=str(_field(raw, "symbol")),
            side=side,
            quantity=quantity,
            created_at=created_at.astimezone(timezone.utc),
            update=self._to_update(raw),
        )

    @staticmethod
    def _invalid(msg: str) -> Result:
        return Result.failure(Error(code=ErrorCode.INVALID_DATA, msg=msg, details=None))


# ---------------------------------------------------------------------- error translation


def to_error(error: Exception) -> Error:
    '''Translates anything the SDK (or our parsing) raised into a core Error. Never raises.'''
    if isinstance(error, _BadData):
        return Error(code=ErrorCode.INVALID_DATA, msg=str(error), details=None)

    if isinstance(error, APIError):
        status = _safe_attr(error, "status_code")
        message = _safe_attr(error, "message") or str(error)
        details: dict[str, Any] = {"http_status": status, "alpaca_code": _safe_attr(error, "code")}
        text = str(message).lower()

        if status == 404:
            return broker_error(BrokerErrorCode.ORDER_NOT_FOUND, str(message), details)
        if "insufficient" in text:
            return broker_error(BrokerErrorCode.INSUFFICIENT_FUNDS, str(message), details)
        if "client_order_id" in text and "unique" in text:
            return broker_error(BrokerErrorCode.DUPLICATE_ORDER, str(message), details)
        if isinstance(status, int) and (status in _RETRYABLE_HTTP or status >= 500):
            return Error.connection_failed(f"Alpaca HTTP {status}: {message}", details)
        return broker_error(BrokerErrorCode.BROKER_REJECTED, str(message), details)

    if isinstance(error, OSError):  # requests' ConnectionError / Timeout are OSErrors
        return Error.connection_failed(f"{type(error).__name__}: {error}", None)

    return Error.unknown_error(f"{type(error).__name__}: {error}", {})


# ---------------------------------------------------------------------- field helpers


_MISSING = object()


def _field(raw: Any, name: str, default: Any = _MISSING) -> Any:
    '''Reads a field from an SDK model or a raw dict (raw_data=True clients).'''
    value = raw.get(name, _MISSING) if isinstance(raw, Mapping) else getattr(raw, name, _MISSING)
    if value is _MISSING:
        if default is _MISSING:
            raise _BadData(f"Alpaca order has no {name!r}.")
        return default
    return value


def _safe_field(raw: Any, name: str) -> Any:
    try:
        return _field(raw, name, None)
    except Exception:  # noqa: BLE001
        return None


def _safe_attr(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except Exception:  # noqa: BLE001 - APIError.message/code parse JSON and may fail
        return None


def _enum_value(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value).lower()


def _decimal(value: Any, *, default: Decimal | None) -> Decimal | None:
    if value is None or value == "":
        return default
    try:
        # str() first: Decimal(0.1) would keep the float's binary noise.
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise _BadData(f"Not a number: {value!r}.") from error
    if not result.is_finite():
        raise _BadData(f"Not a finite number: {value!r}.")
    return result


def _parse_client_order_id(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as error:
        raise _BadData(f"client_order_id {value!r} is not one of ours (not a UUID).") from error
