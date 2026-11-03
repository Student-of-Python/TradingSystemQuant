# Domain-Driven Design (DDD) & Clean Architecture Cheatsheet

---

## 1. The 3 Rules 

| Rule | The Law | Why It Matters |
| :--- | :--- | :--- |
| **1. The Purity Rule** | The `domain/` directory must be **100% pure standard library Python**. No `pandas`, no `requests`, no `alpaca-py`. | If internet access is lost, domain math and rules must still run with 100% reliability. |
| **2. The Anti-Corruption Rule** | External vendor schemas (Alpaca JSON, HTTP responses) must never cross into the domain. | Translating data at the boundary (`adapters/`) ensures an Alpaca API update never breaks our internal models. |
| **3. The Decoupling Rule** | Bounded contexts **never** import or call each other directly (e.g., Strategy never imports Execution). | All cross-system communication flows strictly through canonical events via the `EventRouter`. |

---

## 2. The 3-Zone Folder Structure

Every bounded context is organized identically. Put your code in the right zone:

```text
src/<your_context>/
├── domain/        # ZONE 1: Pure Business Rules
│                  # Entities, Value Objects, Enums, Math. (Zero external imports!)
│
├── ports.py       # ZONE 2: Interfaces & Contracts
│                  # typing.Protocol defining what external adapters must satisfy.
│
├── adapters/      # ZONE 3: Outside World & Anti-Corruption Layer
│                  # Talks to Alpaca, REST APIs, WebSockets, or CSV files.
│
├── events.py      # THE ENVELOPE: Events emitted to the EventRouter.
└── manager.py     # THE CONDUCTOR: Orchestrates domain rules and router subscriptions.
```

---

## 3. Core DDD Concepts: Fast Glossary

### Entity
* **What it is**: A domain object defined by its **unique, persistent identity** (`id`), rather than just its attributes. Its state changes over time.
* **Example**: `Order` (it has a `client_order_id`, and transitions from `PENDING` $\rightarrow$ `SUBMITTED` $\rightarrow$ `FILLED`, but it remains the *same* order).
* **Python idiom**: Class or dataclass with an explicit `id` field.

### Value Object
* **What it is**: An **immutable** object defined solely by its data attributes. It has no identity. Two value objects with identical fields are considered equal.
* **Example**: `MarketBar` (an OHLCV slice), `Fill` (a record of shares transacted), `Money`.
* **Python idiom**: `@dataclass(frozen=True)`.

### Domain Event
* **What it is**: A record of **a historical fact that has already occurred** in the system. Always named in the past tense or as an event occurrence.
* **Example**: `MarketBarEvent`, `SignalEvent`, `RiskApprovedEvent`, `FillEvent`.
* **Python idiom**: Subclasses `BaseEvent`, `@dataclass(frozen=True)`, explicit UTC timestamp.

###  Port (Interface)
* **What it is**: A contract describing *what* a component needs from the outside world without caring *how* it's done.
* **Python idiom**: `typing.Protocol` (e.g., `BrokerPort`, `MarketDataProvider`).

###  Adapter (Anti-Corruption Layer)
* **What it is**: The concrete translation code that plugs into a Port. It takes raw external APIs/JSON and converts them into our clean domain objects.
* **Example**: `AlpacaBrokerAdapter`, `YahooFinanceFeedAdapter`.

###  Invariant
* **What it is**: A mathematical or business truth that must **always** hold true. An object must never be allowed to exist in an invalid state.
* **Example**: `high >= low`, `volume >= 0`, `price > 0`.
* **Python idiom**: Checked inside `__post_init__` on dataclasses.

---

## 4. Type Safety & Financial Math Cheat Sheet

| Domain Concept | ❌ DO NOT USE | ✅ ALWAYS USE | Why? |
| :--- | :--- | :--- | :--- |
| **Prices & Quantities** | `float` (e.g. `10.5`) | `decimal.Decimal` (e.g. `Decimal("10.5")`) | Binary floats suffer from rounding drift (`0.1 + 0.2 != 0.3`). Real capital requires exact math. |
| **Timestamps** | `datetime.now()` | `datetime.now(timezone.utc)` | Naive datetimes cause daylight saving and timezone disaster across exchanges. |
| **Discrete Actions** | `str` (e.g. `"BUY"`) | `enum.StrEnum` (e.g. `OrderSide.BUY`) | Eliminates silent typos and allows IDE autocomplete and static type checking. |
| **Unique Identifiers** | Sequential integers | `uuid.uuid4()` | Guarantees global uniqueness across distributed systems and test runs. |

---

## 5. Our Platform's Event Flow Assembly Line

```text
[ Market Data ] ──(MarketBarEvent)──► [ Strategy Engine ]
                                            │
                                            ▼ (SignalEvent)
                                      [ Risk Engine ]
                                            │
                                            ▼ (RiskApprovedEvent)
                                      [ Execution / OMS ]
                                            │
                                            ▼ (FillEvent)
                                      [ Portfolio Accounting ]
```

---