'''
src/execution/manager.py

ExecutionManager: RiskApprovedEvent -> Order -> broker -> OrderSubmittedEvent / FillEvent.

Two entry points, each split into "decide" (returns events, easy to test) and "publish":
  handle_approval(event)  -> events   (published by the RiskApprovedEvent subscription)
  check_open_orders()     -> events   (published by poll(), called once per tick)

Nothing here is allowed to raise during normal operation: the router swallows handler
exceptions, so a raise would silently lose the order. Problems become OrderRejectedEvents
or log lines instead.
'''

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from types import MappingProxyType

from src.core import BaseEvent
from src.core.results import Error, Result
from src.core.router import EventRouter
from src.execution.domain.enums import OrderSide, OrderStatus
from src.execution.domain.errors import OrderError
from src.execution.domain.events import (
    FillEvent,
    OrderCanceledEvent,
    OrderRejectedEvent,
    OrderSubmittedEvent,
)
from src.execution.domain.order import Order, make_client_order_id
from src.execution.ports import BrokerOrderUpdate, BrokerPort, broker_error_code
from src.risk.domain.events import RiskApprovedEvent
from src.strategy.domain.enums import StrategyAction

logger = logging.getLogger(__name__)

# Only these actions become orders. HOLD should never be a signal; LIQUIDATE needs
# position sizes, which no context owns yet.
_ACTION_TO_SIDE: Mapping[StrategyAction, OrderSide] = MappingProxyType({
    StrategyAction.BUY: OrderSide.BUY,
    StrategyAction.SELL: OrderSide.SELL,
})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _describe(error: Error | None) -> str:
    if error is None:
        return "Broker returned a failure without an error."
    return f"{broker_error_code(error) or error.code}: {error.msg}"


class ExecutionManager:
    '''
    Satisfies core's Subscribable protocol structurally (register_subscriptions).
    Not inherited: importing src.core.protocols fails on Python 3.12 (reported to core).
    '''

    def __init__(self, broker: BrokerPort, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._broker = broker
        self._clock = clock
        self._orders: dict[uuid.UUID, Order] = {}
        self._router: EventRouter | None = None

    @property
    def orders(self) -> Mapping[uuid.UUID, Order]:
        '''Every order this manager created, by client_order_id (read-only view).'''
        return MappingProxyType(self._orders)

    @property
    def open_orders(self) -> tuple[Order, ...]:
        '''Orders the broker holds that are not finished yet.'''
        return tuple(o for o in self._orders.values() if not o.is_terminal and o.broker_order_id is not None)

    # ------------------------------------------------------------------ wiring

    def register_subscriptions(self, router: EventRouter) -> None:
        if self._router is router:
            return
        if self._router is not None:
            raise RuntimeError("ExecutionManager is already registered with a different router.")

        self._router = router
        router.subscribe(RiskApprovedEvent, self._on_risk_approved)

    def _on_risk_approved(self, event: RiskApprovedEvent) -> None:
        self._publish(self.handle_approval(event))

    def poll(self) -> None:
        '''Asks the broker about every open order and publishes what changed. Call once per tick.'''
        self._publish(self.check_open_orders())

    def _publish(self, events: tuple[BaseEvent, ...]) -> None:
        if self._router is None:
            raise RuntimeError("ExecutionManager used before register_subscriptions().")
        if events:
            self._router.publish(*events)

    # ------------------------------------------------------------------ approvals

    def handle_approval(self, event: RiskApprovedEvent) -> tuple[BaseEvent, ...]:
        '''
        action check -> duplicate check -> build Order -> submit -> Submitted / Rejected event.
        Returns () for a duplicate (the signal already has an order).
        '''
        signal = event.signal
        client_order_id = make_client_order_id(signal.event_id)

        side = _ACTION_TO_SIDE.get(signal.action)
        if side is None:
            return (self._refuse(client_order_id, signal.symbol,
                                 f"Unsupported action {signal.action}: only BUY and SELL become orders."),)

        if client_order_id in self._orders:
            logger.info("Ignoring approval %s: signal %s already has order %s.",
                        event.event_id, signal.event_id, client_order_id)
            return ()

        try:
            # TODO(Week 4): pass expected_price=signal.price once SignalEvent has it (slippage).
            order = Order.for_signal(
                signal_id=signal.event_id,
                symbol=signal.symbol,
                side=side,
                quantity=signal.units,
                created_at=self._clock(),
            )
        except (TypeError, ValueError) as error:
            return (self._refuse(client_order_id, signal.symbol, f"Invalid signal: {error}"),)

        # Stored before calling the broker, so the order is known even if the call goes wrong.
        self._orders[client_order_id] = order
        result = self._call_broker(lambda: self._broker.submit_order(order))

        if result.is_success:
            try:
                order.mark_submitted(result.value)  # pyright: ignore[reportArgumentType]
                return (OrderSubmittedEvent.from_order(order),)
            except (TypeError, ValueError) as error:  # checked before any state change
                reason = f"Broker returned an invalid order id: {error}"
        else:
            reason = _describe(result.error)

        # MVP: any submit failure is final. A connection failure might hide an order the broker
        # did receive; startup reconciliation (Week 4) will cover that case.
        order.mark_rejected(reason)
        return (OrderRejectedEvent.from_order(order),)

    def _refuse(self, client_order_id: uuid.UUID, symbol: object, reason: str) -> OrderRejectedEvent:
        logger.warning("Refusing order %s: %s", client_order_id, reason)
        safe_symbol = symbol if isinstance(symbol, str) and symbol.strip() else "?"
        return OrderRejectedEvent(client_order_id=client_order_id, symbol=safe_symbol, reason=reason)

    # ------------------------------------------------------------------ polling

    def check_open_orders(self) -> tuple[BaseEvent, ...]:
        events: list[BaseEvent] = []
        for order in self.open_orders:
            assert order.broker_order_id is not None  # guaranteed by open_orders
            result = self._call_broker(lambda: self._broker.get_order_status(order.broker_order_id))
            if not result.is_success or result.value is None:
                logger.warning("Could not get status of order %s: %s",
                               order.client_order_id, _describe(result.error))
                continue  # try again next poll
            events.extend(self._apply_update(order, result.value))
        return tuple(events)

    def _apply_update(self, order: Order, update: BrokerOrderUpdate) -> list[BaseEvent]:
        events: list[BaseEvent] = []

        # Fills first: a canceled order may still report fills that happened before the cancel.
        known = {f.fill_id for f in order.fills}
        for fill in update.fills:
            if fill.fill_id in known:
                continue  # the broker re-sends every fill on each poll
            try:
                order.apply_fill(fill)
            except OrderError as error:
                logger.error("Broker fill %s refused by order %s: %s", fill.fill_id, order.client_order_id, error)
                continue
            known.add(fill.fill_id)
            events.append(FillEvent.from_order(order, fill))

        if order.is_terminal:
            return events

        try:
            if update.status is OrderStatus.CANCELED:
                order.mark_canceled()
                events.append(OrderCanceledEvent.from_order(order))
            elif update.status is OrderStatus.REJECTED:
                order.mark_rejected(update.reason or "Rejected by the broker after submission.")
                events.append(OrderRejectedEvent.from_order(order))
            elif update.status is OrderStatus.FILLED:
                # The broker says FILLED but we have not seen every fill yet; they should arrive later.
                logger.warning("Broker reports order %s FILLED but only %s of %s is filled here.",
                               order.client_order_id, order.filled_quantity, order.quantity)
        except OrderError as error:
            logger.error("Broker status %s refused by order %s: %s", update.status, order.client_order_id, error)

        return events

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _call_broker[T](call: Callable[[], Result[T]]) -> Result[T]:
        '''Adapters must not raise, but if one does it must not take the manager down with it.'''
        try:
            return call()
        except Exception as error:  # noqa: BLE001 - last line of defense around adapter code
            logger.exception("Broker adapter raised instead of returning a Result.")
            return Result.failure(Error.unknown_error(f"{type(error).__name__}: {error}", {}))  # pyright: ignore[reportReturnType]
