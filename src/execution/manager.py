'''
src/execution/manager.py

ExecutionManager: RiskApprovedEvent -> Order -> broker -> OrderSubmittedEvent / FillEvent.

Entry points, each split into "decide" (returns events, easy to test) and "publish":
  handle_approval(event)          -> events  (published by the RiskApprovedEvent subscription)
  check_open_orders()             -> events  (published by poll(), called once per tick)
  request_cancel(id, reason)      -> events  (published by cancel_order)
  request_cancel_all(reason)      -> events  (published by cancel_all_open_orders: the kill-switch hook)

In-doubt submits: when a submit fails with CONNECTION_FAILURE the broker may or may not have
received the order. The order then stays PENDING_SUBMIT and every poll asks the broker for it by
client_order_id (find_order): found -> SUBMITTED; ORDER_NOT_FOUND -> REJECTED; still unreachable
after `in_doubt_timeout` -> REJECTED with an error log (it may be orphaned at the broker).
It is never re-submitted, so a lost answer can never become a second order.

Timeouts: an order still open `order_timeout` after it was created gets one cancel request.

Lifecycle: start() reconciles with the broker, rebuilding every open order it holds, so a
restart never loses track of a live order. Rebuilt orders take their earlier fills silently
(no FillEvents: those were published before the restart); only later fills are published.

Nothing here is allowed to raise during normal operation: the router swallows handler
exceptions, so a raise would silently lose the order. Problems become OrderRejectedEvents
or log lines instead.
'''

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType

from src.core import BaseEvent
from src.core.results import Error, ErrorCode, Result
from src.core.router import EventRouter
from src.execution.domain.enums import OrderSide, OrderStatus
from src.execution.domain.errors import OrderError
from src.execution.domain.events import (
    FillEvent,
    OrderCanceledEvent,
    OrderCancelRequestedEvent,
    OrderRejectedEvent,
    OrderSubmittedEvent,
)
from src.execution.domain.order import Order, make_client_order_id
from src.execution.ports import BrokerErrorCode, BrokerOrderUpdate, BrokerPort, broker_error_code
from src.risk.domain.events import RiskApprovedEvent
from src.strategy.domain.enums import StrategyAction

logger = logging.getLogger(__name__)

DEFAULT_IN_DOUBT_TIMEOUT = timedelta(minutes=5)

# Only these actions become orders. HOLD should never be a signal; LIQUIDATE needs
# position sizes, which no context owns yet.
_ACTION_TO_SIDE: Mapping[StrategyAction, OrderSide] = MappingProxyType({
    StrategyAction.BUY: OrderSide.BUY,
    StrategyAction.SELL: OrderSide.SELL,
})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _expected_price(signal: object) -> Decimal | None:
    '''
    The signal's price, for slippage. SignalEvent.price is on feature/strategy-context but not
    yet on main, so read it only if present. A missing or unusable price only disables slippage;
    it never blocks the order.
    '''
    price = getattr(signal, "price", None)
    if isinstance(price, Decimal) and price.is_finite() and price > 0:
        return price
    if price is not None:
        logger.warning("Ignoring unusable signal price %r: slippage will not be measured.", price)
    return None


def _describe(error: Error | None) -> str:
    if error is None:
        return "Broker returned a failure without an error."
    return f"{broker_error_code(error) or error.code}: {error.msg}"


class ExecutionManager:
    '''
    Satisfies core's Subscribable (register_subscriptions) and Lifecycle (start / stop)
    protocols structurally. Not inherited: importing src.core.protocols fails on
    Python 3.12 (reported to core).
    '''

    def __init__(
        self,
        broker: BrokerPort,
        *,
        clock: Callable[[], datetime] = _utc_now,
        order_timeout: timedelta | None = None,
        in_doubt_timeout: timedelta = DEFAULT_IN_DOUBT_TIMEOUT,
    ) -> None:
        '''
        order_timeout: cancel orders still open this long after creation (None = never).
        in_doubt_timeout: give up on a submit whose outcome is still unknown after this long.
        '''
        for name, value in (("order_timeout", order_timeout), ("in_doubt_timeout", in_doubt_timeout)):
            if value is not None and (not isinstance(value, timedelta) or value <= timedelta(0)):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise ValueError(f"{name} must be a positive timedelta, got {value!r}.")
        self._broker = broker
        self._clock = clock
        self._order_timeout = order_timeout
        self._in_doubt_timeout = in_doubt_timeout
        self._orders: dict[uuid.UUID, Order] = {}
        self._cancel_requested: set[uuid.UUID] = set()      # cancel accepted by the broker
        self._cancel_when_found: dict[uuid.UUID, str] = {}  # in-doubt orders to cancel once found
        self._router: EventRouter | None = None

    @property
    def orders(self) -> Mapping[uuid.UUID, Order]:
        '''Every order this manager created, by client_order_id (read-only view).'''
        return MappingProxyType(self._orders)

    @property
    def open_orders(self) -> tuple[Order, ...]:
        '''Orders the broker holds that are not finished yet.'''
        return tuple(o for o in self._orders.values() if not o.is_terminal and o.broker_order_id is not None)

    @property
    def in_doubt_orders(self) -> tuple[Order, ...]:
        '''Orders whose submit lost its answer: the broker may or may not have them.'''
        return tuple(o for o in self._orders.values() if o.status is OrderStatus.PENDING_SUBMIT)

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

    def cancel_order(self, client_order_id: uuid.UUID, reason: str) -> None:
        '''Asks the broker to cancel one order and publishes what happened.'''
        self._publish(self.request_cancel(client_order_id, reason))

    def cancel_all_open_orders(self, reason: str) -> None:
        '''
        Cancels every open order. This is the kill-switch hook: once Risk publishes a
        KillSwitchEngagedEvent, subscribe it here.
        '''
        self._publish(self.request_cancel_all(reason))

    def _publish(self, events: tuple[BaseEvent, ...]) -> None:
        if self._router is None:
            raise RuntimeError("ExecutionManager used before register_subscriptions().")
        for event in events:
            # Audit trail: every state change execution makes is one of these events.
            logger.info("execution event %s: %r", type(event).__name__, event)
        if events:
            self._router.publish(*events)

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        '''
        Reconciles with the broker before trading. Raises RuntimeError if the broker cannot
        list its open orders: trading blind after a restart could double-trade or orphan orders.
        '''
        recovered = self.reconcile()
        logger.info("ExecutionManager started; recovered %d open order(s) from the broker.", len(recovered))

    def stop(self) -> None:
        '''Nothing to close (the adapter owns its connection). Open orders stay at the broker.'''
        still_open = self.open_orders + self.in_doubt_orders
        if still_open:
            logger.warning("ExecutionManager stopping with %d order(s) still open: %s",
                           len(still_open), [str(o.client_order_id) for o in still_open])

    def reconcile(self) -> tuple[Order, ...]:
        '''Adopts every open broker order this manager does not know yet. Returns the adopted orders.'''
        result = self._call_broker(self._broker.list_open_orders)
        if not result.is_success or result.value is None:
            raise RuntimeError(f"Startup reconciliation failed: {_describe(result.error)}")

        adopted: list[Order] = []
        for record in result.value:
            known = self._orders.get(record.client_order_id)
            if known is not None:
                continue  # already tracked; normal polling keeps it up to date
            try:
                order = Order(
                    client_order_id=record.client_order_id,
                    symbol=record.symbol,
                    side=record.side,
                    quantity=record.quantity,
                    created_at=record.created_at,
                )
                order.mark_submitted(record.update.broker_order_id)
                for fill in record.update.fills:
                    order.apply_fill(fill)
            except (TypeError, ValueError, OrderError) as error:
                logger.error("Could not adopt broker order %s (%s): %s",
                             record.update.broker_order_id, record.client_order_id, error)
                continue
            self._orders[order.client_order_id] = order
            adopted.append(order)
            logger.info("Recovered open order %s from the broker: %r", record.update.broker_order_id, order)
        return tuple(adopted)

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
            order = Order.for_signal(
                signal_id=signal.event_id,
                symbol=signal.symbol,
                side=side,
                quantity=signal.units,
                created_at=self._clock(),
                expected_price=_expected_price(signal),
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
        elif result.error is not None and result.error.code is ErrorCode.CONNECTION_FAILURE:
            # The broker may have the order: keep it PENDING_SUBMIT and look it up on each poll.
            logger.warning("Submit of order %s is in doubt (%s); will look it up on the next poll.",
                           client_order_id, _describe(result.error))
            return ()
        else:
            reason = _describe(result.error)

        # Any other submit failure is final: the signal is never retried.
        order.mark_rejected(reason)
        return (OrderRejectedEvent.from_order(order),)

    def _refuse(self, client_order_id: uuid.UUID, symbol: object, reason: str) -> OrderRejectedEvent:
        logger.warning("Refusing order %s: %s", client_order_id, reason)
        safe_symbol = symbol if isinstance(symbol, str) and symbol.strip() else "?"
        return OrderRejectedEvent(client_order_id=client_order_id, symbol=safe_symbol, reason=reason)

    # ------------------------------------------------------------------ polling

    def check_open_orders(self) -> tuple[BaseEvent, ...]:
        events: list[BaseEvent] = []
        for order in self.in_doubt_orders:
            events.extend(self._resolve_in_doubt(order))
        for order in self.open_orders:
            assert order.broker_order_id is not None  # guaranteed by open_orders
            result = self._call_broker(lambda: self._broker.get_order_status(order.broker_order_id))
            if not result.is_success or result.value is None:
                logger.warning("Could not get status of order %s: %s",
                               order.client_order_id, _describe(result.error))
                continue  # try again next poll
            events.extend(self._apply_update(order, result.value))
        events.extend(self._enforce_timeout())
        return tuple(events)

    def _resolve_in_doubt(self, order: Order) -> list[BaseEvent]:
        result = self._call_broker(lambda: self._broker.find_order(order.client_order_id))
        if result.is_success and result.value is not None:
            update = result.value
            try:
                order.mark_submitted(update.broker_order_id)
            except (TypeError, ValueError, OrderError) as error:
                logger.error("Could not record in-doubt order %s as submitted: %s", order.client_order_id, error)
                return []
            logger.info("In-doubt order %s was received by the broker as %s.",
                        order.client_order_id, update.broker_order_id)
            events: list[BaseEvent] = [OrderSubmittedEvent.from_order(order)]
            events.extend(self._apply_update(order, update))
            reason = self._cancel_when_found.pop(order.client_order_id, None)
            if reason is not None and not order.is_terminal:
                events.extend(self._send_cancel(order, reason))
            return events

        if broker_error_code(result.error) is BrokerErrorCode.ORDER_NOT_FOUND:
            return self._give_up(order, "Submit failed: the connection dropped and the broker never received the order.")

        if self._clock() - order.created_at >= self._in_doubt_timeout:
            logger.error("Order %s: submit outcome still unknown after %s (%s). It may exist at the broker; "
                         "check it by hand.", order.client_order_id, self._in_doubt_timeout, _describe(result.error))
            return self._give_up(order, f"Submit outcome unknown after {self._in_doubt_timeout}: {_describe(result.error)}")

        logger.warning("Order %s is still in doubt: %s", order.client_order_id, _describe(result.error))
        return []

    def _give_up(self, order: Order, reason: str) -> list[BaseEvent]:
        self._cancel_when_found.pop(order.client_order_id, None)
        order.mark_rejected(reason)
        return [OrderRejectedEvent.from_order(order)]

    def _enforce_timeout(self) -> list[BaseEvent]:
        if self._order_timeout is None:
            return []
        now = self._clock()
        events: list[BaseEvent] = []
        for order in self.open_orders:
            if order.client_order_id in self._cancel_requested:
                continue
            if now - order.created_at >= self._order_timeout:
                logger.warning("Order %s still %s after %s; canceling.", order.client_order_id,
                               order.status, self._order_timeout)
                events.extend(self._send_cancel(order, f"Timed out: still {order.status} after {self._order_timeout}."))
        return events

    # ------------------------------------------------------------------ cancels

    def request_cancel(self, client_order_id: uuid.UUID, reason: str) -> tuple[BaseEvent, ...]:
        '''
        Asks the broker to cancel. Returns OrderCancelRequestedEvent if the broker accepted the
        request (the CANCELED status follows on a later poll), else nothing (logged).
        An in-doubt order is canceled as soon as the broker confirms it has it.
        '''
        order = self._orders.get(client_order_id)
        if order is None:
            logger.warning("Cannot cancel %s: no such order.", client_order_id)
            return ()
        if order.is_terminal:
            logger.info("Not canceling order %s: it is already %s.", client_order_id, order.status)
            return ()
        if order.broker_order_id is None:
            self._cancel_when_found[client_order_id] = reason
            return ()
        if client_order_id in self._cancel_requested:
            return ()
        return tuple(self._send_cancel(order, reason))

    def request_cancel_all(self, reason: str) -> tuple[BaseEvent, ...]:
        events: list[BaseEvent] = []
        for order in self.open_orders + self.in_doubt_orders:
            events.extend(self.request_cancel(order.client_order_id, reason))
        return tuple(events)

    def _send_cancel(self, order: Order, reason: str) -> list[BaseEvent]:
        assert order.broker_order_id is not None
        result = self._call_broker(lambda: self._broker.cancel_order(order.broker_order_id))  # pyright: ignore[reportArgumentType]
        if not result.is_success:
            # Often harmless (e.g. it filled meanwhile); the next poll shows the real status.
            logger.warning("Cancel of order %s refused: %s", order.client_order_id, _describe(result.error))
            return []
        self._cancel_requested.add(order.client_order_id)
        return [OrderCancelRequestedEvent.from_order(order, reason)]

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
