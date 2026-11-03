# Bounded Context Charter: Market Data (Observation)

> **Context Owner**: John     
> **Mission**: Observe external financial markets and translate raw vendor feeds into clean, domain events for our system.

---

## 1. The DDD Philosophy & Guardrails

You have creative freedom over how you model and implement this subsystem. However, to keep our trading system financially safe and maintainable, your design must uphold **three inviolable DDD principles**:

1. **The Purity Rule (Domain Isolation)**  
   Your core **domain** models must be pure Python standard library. Never let outside libraries (`requests`, `alpaca`, `pandas`) leak into your domain. If the internet goes down, your domain rules must still run.
2. **The Anti-Corruption Rule (Protect the Inside)**  
   Raw broker JSON and third-party quirks must stay at the boundary (in an adapter). Your context is responsible for translating messy outside data into strict, validated, internal representations using exact `Decimal` math and explicit UTC timestamps. Please consider taking a look at "src/core/results/" for exception handling
3. **The Decoupling Rule (Event-Driven Boundary)**. 
   Other subsystems (Strategy, Risk, OMS) will never call your methods directly. You communicate with the rest of the trading system strictly by publishing immutable events to the `EventRouter`.

---

## 2. Design Prompts to Guide Your Architecture

Design this context by answering these core questions:

### A. Ubiquitous Language & Domain Modeling
* What are the foundational concepts in your context? What is a "Bar"? What is a "Tick"? What is a "Timeframe"?
* Which objects are **Value Objects** (immutable, defined by their attributes, with zero identity like a price bar) and which are **Entities** or **Services**?
* What mathematical invariants must your domain enforce? *(e.g., Can a high price ever be lower than a low price? Can volume be negative?)*

### B. Ports & Adapters (Hexagonal Architecture)
* How will you structure your code so that switching from Alpaca to Interactive Brokers, Yahoo Finance, or a mock CSV file requires changing **only one adapter file** without touching your core domain?
* What does the interface (Port / Protocol) between your manager and external data providers look like?

### C. Application Orchestration
* How will your manager orchestrate the flow: receiving raw ticks $\rightarrow$ validating domain rules $\rightarrow$ publishing events to the router?
* How does your manager handle startup (historical warmup) vs. live streaming?

---

## 3. Definition of Success

Your bounded context is ready for review when:
1. **Domain Integrity**: Your domain models reject invalid market data with clear errors.
2. **Pluggable Adapter**: You have a working adapter (or mock adapter) feeding standardized data into the domain.
3. **Router Integration**: Canonical market events flow safely onto the `EventRouter`.
4. **Test-Driven Rigor**: Pure unit tests prove your validation logic and invariant checks work green with `pytest`.
