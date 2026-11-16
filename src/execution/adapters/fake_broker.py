'''
src/execution/adapters/fake_broker.py

In-memory BrokerPort for tests and demos. No network, fully deterministic.

Fills happen when the order is polled (get_order_status), like a real broker that fills
between two polls:
  FillMode.IMMEDIATE: the whole quantity fills on the first poll.
  FillMode.PARTIAL:   the quantity fills in `partial_steps` equal chunks, one chunk per poll.
  FillMode.MANUAL:    nothing fills on its own; the test calls fill() / reject() itself.

Failures:
  fail_submits_with(error): every submit_order fails with `error` until cleared (None).
  disconnect() / reconnect(): every call fails with CONNECTION_FAILURE while disconnected.
  A second submit with the same client_order_id fails with DUPLICATE_ORDER (like Alpaca).
  drop_next_submit_ack(): the next submit reaches the broker (the order exists) but the
    answer is lost, so the caller sees CONNECTION_FAILURE. Use find_order to recover it.

Like a real broker, get_order_status reports every fill so far, not just the new ones.
'''

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from src.core.results import Error, Result
from src.execution.domain.enums import OrderSide, OrderStatus
from src.execution.domain.fill import Fill
from src.execution.domain.order import ALLOWED_TRANSITIONS, Order
from src.execution.ports import (
    BrokerErrorCode,
    BrokerOrderId,
    BrokerOrderRecord,
    BrokerOrderUpdate,
    broker_error,
)


class FillMode(StrEnum):
    IMMEDIATE = 'IMMEDIATE'
    PARTIAL = 'PARTIAL'
    MANUAL = 'MANUAL'


@dataclass(slots=True)
class _FakeOrder:
    client_order_id: uuid.UUID
    symbol: str
    side: OrderSide
    quantity: Decimal
    created_at: datetime
    status: OrderStatus = OrderStatus.SUBMITTED
    fills: list[Fill] = field(default_factory=list)
    reason: str | None = None

    @property
    def filled(self) -> Decimal:
        return sum((f.quantity for f in self.fills), Decimal("0"))

    @property
    def is_open(self) -> bool:
        return bool(ALLOWED_TRANSITIONS[self.status])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FakeBroker:
    def __init__(
        self,
        *,
        fill_mode: FillMode = FillMode.IMMEDIATE,
        fill_price: Decimal = Decimal("100"),
        partial_steps: int = 2,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not isinstance(fill_mode, FillMode):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"fill_mode must be a FillMode, got {type(fill_mode).__name__}.")
        if not isinstance(partial_steps, int) or partial_steps < 2:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError(f"partial_steps must be an int >= 2, got {partial_steps!r}.")

        self.fill_mode = fill_mode
        self.fill_price = fill_price
        self._partial_steps = partial_steps
        self._clock = clock

        self._orders: dict[BrokerOrderId, _FakeOrder] = {}
        self._by_client_id: dict[uuid.UUID, BrokerOrderId] = {}
        self._submit_error: Error | None = None
        self._drop_next_ack = False
        self._connected = True

        # Call log, for assertions in tests.
        self.submitted: list[Order] = []
        self.cancel_requests: list[BrokerOrderId] = []
        self.status_requests: list[BrokerOrderId] = []
        self.find_requests: list[uuid.UUID] = []

    # ------------------------------------------------------------------ test controls

    def fail_submits_with(self, error: Error | None) -> None:
        '''Every following submit fails with `error`. Pass None to go back to normal.'''
        self._submit_error = error

    def drop_next_submit_ack(self) -> None:
        '''The next submit is accepted, but its answer is lost (CONNECTION_FAILURE).'''
        self._drop_next_ack = True

    def disconnect(self) -> None:
        self._connected = False

    def reconnect(self) -> None:
        self._connected = True

    def fill(self, broker_order_id: BrokerOrderId, quantity: Decimal, price: Decimal | None = None) -> Fill:
        '''Fills part of an open order right now (used with FillMode.MANUAL).'''
        fake = self._orders[broker_order_id]
        if not fake.is_open:
            raise ValueError(f"Order {broker_order_id} is {fake.status}; it cannot fill.")
        if quantity > fake.quantity - fake.filled:
            raise ValueError(f"Fill of {quantity} exceeds the {fake.quantity - fake.filled} still open.")
        return self._add_fill(broker_order_id, fake, quantity, price)

    def reject(self, broker_order_id: BrokerOrderId, reason: str) -> None:
        '''The broker rejects an order it had accepted (e.g. a later risk check on its side).'''
        fake = self._orders[broker_order_id]
        fake.status = OrderStatus.REJECTED
        fake.reason = reason

    # ------------------------------------------------------------------ BrokerPort

    def submit_order(self, order: Order) -> Result[BrokerOrderId]:
        self.submitted.append(order)
        if not self._connected:
            return self._connection_failure()
        if self._submit_error is not None:
            return Result.failure(self._submit_error)
        if order.client_order_id in self._by_client_id:
            return Result.failure(broker_error(
                BrokerErrorCode.DUPLICATE_ORDER,
                f"client_order_id {order.client_order_id} was already submitted.",
                {"broker_order_id": self._by_client_id[order.client_order_id]},
            ))

        broker_order_id = f"FAKE-{len(self._orders) + 1}"
        self._orders[broker_order_id] = _FakeOrder(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            created_at=self._clock(),
        )
        self._by_client_id[order.client_order_id] = broker_order_id
        if self._drop_next_ack:
            self._drop_next_ack = False
            return self._connection_failure()
        return Result.successful(broker_order_id)

    def cancel_order(self, broker_order_id: BrokerOrderId) -> Result[None]:
        self.cancel_requests.append(broker_order_id)
        if not self._connected:
            return self._connection_failure()
        fake = self._orders.get(broker_order_id)
        if fake is None:
            return self._not_found(broker_order_id)
        if not fake.is_open:
            return Result.failure(broker_error(
                BrokerErrorCode.BROKER_REJECTED,
                f"Order {broker_order_id} is {fake.status} and cannot be canceled.",
            ))
        fake.status = OrderStatus.CANCELED
        return Result.successful(None)

    def get_order_status(self, broker_order_id: BrokerOrderId) -> Result[BrokerOrderUpdate]:
        self.status_requests.append(broker_order_id)
        if not self._connected:
            return self._connection_failure()
        fake = self._orders.get(broker_order_id)
        if fake is None:
            return self._not_found(broker_order_id)

        if fake.is_open:
            self._auto_fill(broker_order_id, fake)

        return Result.successful(self._update(broker_order_id, fake))

    def find_order(self, client_order_id: uuid.UUID) -> Result[BrokerOrderUpdate]:
        '''Lookup by our id. Unlike get_order_status, it never triggers automatic fills.'''
        self.find_requests.append(client_order_id)
        if not self._connected:
            return self._connection_failure()
        broker_order_id = self._by_client_id.get(client_order_id)
        if broker_order_id is None:
            return Result.failure(broker_error(
                BrokerErrorCode.ORDER_NOT_FOUND, f"No order with client_order_id {client_order_id}."
            ))
        return Result.successful(self._update(broker_order_id, self._orders[broker_order_id]))

    def list_open_orders(self) -> Result[tuple[BrokerOrderRecord, ...]]:
        if not self._connected:
            return self._connection_failure()
        return Result.successful(tuple(
            BrokerOrderRecord(
                client_order_id=fake.client_order_id,
                symbol=fake.symbol,
                side=fake.side,
                quantity=fake.quantity,
                created_at=fake.created_at,
                update=self._update(broker_order_id, fake),
            )
            for broker_order_id, fake in self._orders.items()
            if fake.is_open
        ))

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _update(broker_order_id: BrokerOrderId, fake: _FakeOrder) -> BrokerOrderUpdate:
        return BrokerOrderUpdate(
            broker_order_id=broker_order_id,
            status=fake.status,
            fills=tuple(fake.fills),
            reason=fake.reason,
        )

    def _auto_fill(self, broker_order_id: BrokerOrderId, fake: _FakeOrder) -> None:
        remaining = fake.quantity - fake.filled
        if self.fill_mode is FillMode.IMMEDIATE:
            self._add_fill(broker_order_id, fake, remaining, None)
        elif self.fill_mode is FillMode.PARTIAL:
            chunk = fake.quantity / self._partial_steps
            # The last step takes exactly what is left, so the chunks always add up.
            last_step = len(fake.fills) + 1 >= self._partial_steps or chunk >= remaining
            self._add_fill(broker_order_id, fake, remaining if last_step else chunk, None)

    def _add_fill(self, broker_order_id: BrokerOrderId, fake: _FakeOrder,
                  quantity: Decimal, price: Decimal | None) -> Fill:
        fill = Fill(
            fill_id=f"{broker_order_id}-fill-{len(fake.fills) + 1}",
            client_order_id=fake.client_order_id,
            price=self.fill_price if price is None else price,
            quantity=quantity,
            timestamp=self._clock(),
        )
        fake.fills.append(fill)
        fake.status = OrderStatus.FILLED if fake.filled >= fake.quantity else OrderStatus.PARTIALLY_FILLED
        return fill

    @staticmethod
    def _connection_failure() -> Result:
        return Result.failure(Error.connection_failed("Fake broker is disconnected.", None))

    @staticmethod
    def _not_found(broker_order_id: BrokerOrderId) -> Result:
        return Result.failure(broker_error(BrokerErrorCode.ORDER_NOT_FOUND, f"No order with id {broker_order_id}."))
