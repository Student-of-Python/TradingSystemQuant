# Bounded Context Charter: Execution & OMS (Action)

> **Context Owner**: Avin   
> **Mission**: Manage the lifecycle of approved trading orders, submission to the broker, and translate broker execution updates into domain events.

---

## 1. The DDD Philosophy & Guardrails

You have creative freedom over your order management architecture. However, because this subsystem directly touches broker capital and handles real market transactions, your design must uphold **three DDD principles**:

1. **The Purity Rule (Domain Isolation)**  
   Your core `Order` entity, order state machine, and fill calculations in `domain/` must be pure Python. Never import broker SDKs (`alpaca`), HTTP clients (`requests`), or databases into your domain models.
2. **The Idempotency & State Integrity Rule**  
   Every order must carry a deterministic, unique `client_order_id` (UUID). Network hiccups, duplicate events, or retries must **never** result in double-submitting an order. Furthermore, your order state machine must strictly forbid illegal transitions (e.g., an order that is `FILLED` or `CANCELED` can never transition back to `SUBMITTED`).
3. **The Anti-Corruption Rule (Broker Isolation via Adapters)**  
   The outside broker API (e.g., Alpaca Paper REST) is strictly restricted to `adapters/`. Your internal domain and manager communicate only through an abstract `BrokerPort` protocol. Swapping Alpaca for another broker should require modifying only one adapter file.

---

## 2. Design Prompts to Guide Your Architecture

Design this context by answering these core questions:

### A. Ubiquitous Language & The Order Lifecycle
* What is an `Order`? What fields are essential for MVP market orders (`client_order_id`, `symbol`, `side`, `quantity` in `Decimal`, `status`, `created_at` UTC)?
* What is an `OrderState`? Look up the **State Pattern** in Ronald Mak's "Software Design for Python Developers". What are the valid transitions?
  $$\text{PENDING_SUBMIT} \longrightarrow \text{SUBMITTED} \longrightarrow \text{PARTIALLY_FILLED} \longrightarrow \text{FILLED}$$
  $$\text{SUBMITTED} \longrightarrow \text{CANCELED} \quad\text{or}\quad \text{REJECTED}$$
* What is a `Fill`? What attributes define an execution record (e.g., `fill_id`, `fill_price`, `fill_quantity`, `timestamp`)?

### B. Ports & Adapters (Hexagonal Architecture)
* What does your `BrokerPort` (Protocol) look like? What methods does the OMS need from any broker? *(e.g., `submit_order(order) -> Result[BrokerOrderId, Error]`, `cancel_order(order_id)`)*.
* How does your `AlpacaBrokerAdapter` translate our clean domain `Order` into an Alpaca API call, and translate Alpaca's JSON response back into domain events?

### C. Application Orchestration (Execution Manager / OMS)
* How will your `ExecutionManager` subscribe to `RiskApprovedEvent`s arriving on the `EventRouter`?
* When an approved event arrives, how does the manager create an `Order`, update its state to `SUBMITTED`, call the broker adapter, and publish `OrderSubmittedEvent`?
* When the broker confirms execution, how does the manager apply the fill to the order and publish a  `FillEvent` for the rest of the platform (like Portfolio accounting)?

---

## 3. Definition of Success

Your bounded context is ready for review when:
1. **Deterministic State Machine**: An `Order` entity that correctly transitions between states and throws explicit exceptions on illegal transitions.
2. **Idempotent Order Identification**: Every order automatically generates a unique `client_order_id`.
3. **Pluggable Broker Port & Paper Adapter**: A clean `BrokerPort` protocol with a working Alpaca Paper adapter (or mock broker adapter).
4. **Router Integration**: Your manager successfully subscribes to `RiskApprovedEvent` and publishes `OrderSubmittedEvent` and `FillEvent` to the `EventRouter`.
5. **Test-Driven Rigor**: Pure unit tests verifying state transitions, fill handling, and broker error conversions pass green with `pytest`.
