# Execution / OMS

Turns `RiskApprovedEvent`s into broker orders and turns what the broker reports back into
domain events. Charter: [`design.md`](design.md).

```
RiskApprovedEvent ──► ExecutionManager ──► BrokerPort ──► FakeBroker   (tests, demos)
                           │                         └──► AlpacaBroker (paper / live)
                           ▼
   OrderSubmittedEvent · FillEvent · OrderRejectedEvent · OrderCanceledEvent · OrderCancelRequestedEvent
```

## Layout

| Path | What it holds |
|---|---|
| `domain/` | Pure Python (no SDKs, enforced by a test): `Order` entity + state machine, `Fill`, events, errors |
| `ports.py` | `BrokerPort` protocol, `BrokerOrderUpdate`, `BrokerOrderRecord`, `BrokerErrorCode` |
| `adapters/fake_broker.py` | In-memory broker: immediate / partial / manual fills, rejects, disconnects, lost acks |
| `adapters/alpaca_broker.py` | Alpaca adapter, the only file that imports `alpaca` |
| `manager.py` | `ExecutionManager`: orchestration, idempotency, polling, cancels, timeouts, reconciliation |

## Order lifecycle

```
PENDING_SUBMIT   → SUBMITTED, REJECTED
SUBMITTED        → PARTIALLY_FILLED, FILLED, CANCELED, REJECTED
PARTIALLY_FILLED → PARTIALLY_FILLED, FILLED, CANCELED
FILLED / CANCELED / REJECTED → terminal
```
Any other move raises `IllegalTransitionError` and leaves the order unchanged. Fills drive the status.
Overfills, duplicate `fill_id`s, and fills for another order are refused.

## Guarantees

- **One signal, at most one order.** `client_order_id = uuid5(namespace, signal.event_id)`. A repeated
  approval, or two approvals of the same signal, are ignored. The broker also refuses a reused
  `client_order_id` as a second safety net.
- **Lost answers are not retried blindly.** If a submit fails with `CONNECTION_FAILURE`, the order
  stays `PENDING_SUBMIT` ("in doubt"), and each poll looks it up with `find_order`.
  If found, it becomes `SUBMITTED`. If the broker says not found, it becomes `REJECTED`.
  If the broker is still unreachable after `in_doubt_timeout` (default 5 min), it becomes `REJECTED`
  and an error is logged for a manual check. The order is never re-submitted.
- **Nothing raises into the router.** Adapters return `Result`s. Anything unexpected is logged and
  becomes an `OrderRejectedEvent`.
- **Restarts don't lose orders.** `start()` adopts every open broker order. Fills that happened before
  the restart are applied without publishing events; only later fills are published.

## Using it

```python
from src.core.router import EventRouter
from src.execution.adapters.alpaca_broker import AlpacaBroker   # or FakeBroker()
from src.execution.manager import ExecutionManager
from datetime import timedelta

router = EventRouter()
manager = ExecutionManager(AlpacaBroker.from_env(), order_timeout=timedelta(minutes=15))
manager.register_subscriptions(router)   # subscribes to RiskApprovedEvent
manager.start()                          # reconcile with the broker (raises if unreachable)

# main loop, once per tick:
manager.poll()                           # fills, cancels, in-doubt lookups, timeouts

manager.cancel_all_open_orders("kill switch")   # hook for Risk's kill switch
manager.stop()
```

Every published event is also logged at INFO by `src.execution.manager` (audit trail).

## Events

| Event | When |
|---|---|
| `OrderSubmittedEvent` | The broker acknowledged the order |
| `FillEvent` | A fill was applied. Includes cumulative/remaining qty, avg price, and `expected_price` → `slippage`, `slippage_bps` (positive = worse) |
| `OrderRejectedEvent` | Refused by execution (unsupported action, bad units) or by the broker |
| `OrderCancelRequestedEvent` | Execution asked the broker to cancel (timeout, kill switch, manual) |
| `OrderCanceledEvent` | The broker confirmed the cancel. Partial fills are kept |

## Alpaca

Install: `.venv/bin/pip install -r src/execution/requirements.txt`. Put your keys in `.env` at the
repo root (it's git-ignored):

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_PAPER=true      # only the exact value "false" enables live trading
```

| Alpaca status | Ours |
|---|---|
| `new`, `pending_new`, `accepted`, `accepted_for_bidding`, `pending_review`, `calculated`, `held`, `suspended`, `stopped`, `done_for_day`, `pending_cancel`, `pending_replace` | `SUBMITTED` (or `PARTIALLY_FILLED` if `filled_qty > 0`) |
| `partially_filled` | `PARTIALLY_FILLED` |
| `filled` | `FILLED` |
| `canceled`, `expired`, `replaced` | `CANCELED` |
| `rejected` | `REJECTED` (`CANCELED` if something already filled) |

Alpaca's order object only reports cumulative `filled_qty` / `filled_avg_price`. The adapter records
one synthetic fill per increase (`fill_id = "<alpaca id>:<cumulative qty>"`), priced so that the sum
of the fills matches Alpaca's average exactly. Errors: 404 → `ORDER_NOT_FOUND`, insufficient buying
power → `INSUFFICIENT_FUNDS`, duplicate `client_order_id` → `DUPLICATE_ORDER`, 429/5xx/network →
`CONNECTION_FAILURE`, other API errors → `BROKER_REJECTED`.

MVP scope: market orders, `DAY`, US equities, polling (no websocket).

## Tests

```bash
.venv/bin/python -m pytest tests/unit/test_execution_*.py            # no network
RUN_INTEGRATION=1 .venv/bin/python -m pytest tests/integration -s     # real Alpaca PAPER order
```
Python 3.12+. The Alpaca unit tests are skipped if `alpaca-py` isn't installed. The integration test
refuses to run against a live account, and it skips (after canceling) if the market is closed.
