# Bounded Context Charter: Strategy (Alpha Decisioning)

> **Context Owner**: Rudra  
> **Mission**: Have a strategy emit pure trading intents (*Signals*) without communicating directly with brokers or placing orders after recieving and compiling data. 

---

## 1. The DDD Philosophy & Guardrails

You have creative freedom over how you design and implement your trading models. However, to keep our trading system financially safe and modular, your design must uphold **three inviolable DDD principles**:

1. **The Purity Rule (Domain Isolation)**  
   Your core domain models and signal logic must be pure Python. If a strategy uses numerical libraries (like NumPy or internal arrays) for its calculations, that math must be strictly encapsulated inside the strategy model—it must **never** leak into external events or shared interfaces.
2. **The Intent Rule (Express Intent, Not Execution)**  
   Strategies express *trading intent* (e.g., *"I want to buy 10 shares of AAPL"*), **never** execution commands. Strategies must never know about broker accounts, buying power, risk limits, or order routing. All units/quantities must use exact `Decimal` math, and actions must use strict `StrEnum` types.
3. **The Decoupling Rule (Event-Driven Boundary)**  
   Your subsystem never communicates directly with Market Data or the Risk Engine. You receive market data strictly by listening to `MarketBarEvent`s on the `EventRouter`, and you broadcast your decisions strictly by publishing immutable `SignalEvent`s.

---

## 2. Design Prompts to Guide Your Architecture

Design this context by answering these core questions:

### A. Ubiquitous Language & Domain Modeling
* What is a "Signal"? What specific information does a downstream Risk Engine or OMS need to safely evaluate it (e.g., symbol, action, quantity, strategy identifier, timestamp)?
* How will you model strategy actions? What discrete states exist (`BUY`, `SELL`, `LIQUIDATE`)? 
* What happens when a strategy evaluates a bar and decides not to trade? *(Why is returning `None` cleaner for the event bus than publishing a `HOLD` event?)*

### B. The Strategy Pattern (Pluggable Alpha Models)
* How will you design a generic `Strategy` interface (Protocol) so any quantitative analyst in the club can write a new strategy (e.g., 20-MA Crossover, RSI, Mean Reversion) and plug it in seamlessly?
* Where should a strategy store its internal rolling state (e.g., historical prices to compute a moving average) without leaking memory or state across different strategies?

### C. Application Orchestration (Strategy Manager)
* How will your `StrategyManager` act as the conductor? How does it subscribe to `MarketBarEvent`s, route bars to active strategies, collect their signals, and publish `SignalEvent`s to the `EventRouter`?
* How will your strategies handle **warmup** (e.g., needing 20 historical bars to seed a moving average before trading starts) versus **live bar processing**?

---

## 3. Definition of Success

Your bounded context is ready for review when:
1. **Pluggable Strategy Contract**: You have a clean `Strategy` interface/protocol that decouples strategy logic from the system.
2. **Working Reference Strategy**: You have at least one concrete strategy implemented (e.g., SMA Crossover) that generates valid signals from bar inputs.
3. **Router Integration**: Your manager successfully subscribes to `MarketBarEvent` and publishes validated `SignalEvent`s to the `EventRouter`.
4. **Test-Driven Rigor**: Pure unit tests prove your indicator calculations, signal generation, and edge cases (e.g., warmup handling, flat markets) pass green with `pytest`.
