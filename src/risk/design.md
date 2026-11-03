# Bounded Context Charter: Risk Engine (Permission & Safety)

> **Context Owner**: Jesse   
> **Mission**: Serve as the independent safety net of the trading platform. Evaluate every strategy intent (*Signal*) against strict risk limits and grant permission (*Approved* vs. *Rejected*) before any trade reaches the broker.

---

## 1. The DDD Philosophy & Guardrails

You have creative freedom over how you design and structure the risk checks. However, because this subsystem protects the club's capital from runaway algorithms, your design must uphold **three inviolable DDD principles**:

1. **The Purity Rule (Domain Isolation)**  
   Risk rules are pure mathematical constraints (e.g., $\text{shares} \times \text{price} \le \text{Max Capital}$). Your `domain/` rules must be pure standard library Python—never import external libraries, brokers, or databases.
2. **The Gatekeeper Rule (Zero Execution / Absolute Authority)**  
   The Risk Engine never places trades, never alters a strategy's signal, and never talks to brokers. It is strictly an impartial judge: it evaluates a signal and issues an explicit **PASS** (`RiskApprovedEvent`) or **FAIL** (`RiskRejectedEvent`). No trade ever reaches the market without passing through this gate. Please consider checking `src/core/exceptions/` (or `Result`) for clean internal evaluation outcomes.
3. **The Decoupling Rule (Event-Driven Boundary)**  
   Your subsystem never calls Strategy or OMS code directly. You listen strictly for `SignalEvent`s arriving on the `EventRouter`, and you publish `RiskApprovedEvent` or `RiskRejectedEvent` back to the router.

---

## 2. Design Prompts to Guide Your Architecture

Design this context by answering these core questions:

### A. Ubiquitous Language & Domain Modeling
* What is a "RiskRule"? What does a rule evaluation return? *(e.g., Does it return a boolean, or an outcome object containing a clear rejection reason?)*
* For our MVP, what are the essential safety checks?
  1. **Max Order Value Rule**: Rejects trades where $\text{units} \times \text{price}$ exceeds a hard cash limit (e.g., $10,000).
  2. **Max Unit Size Rule**: Rejects trades requesting more than a hard share limit (e.g., 100 shares).
  3. **Global Kill Switch**: An emergency circuit breaker that instantly rejects 100% of signals when engaged.

### B. Composable Patterns (Chain of Responsibility / Specification)
* As our club grows, quant researchers will want to add new risk rules (e.g., Max Daily Loss, Volatility Filter, Wash Sale Prevention).
* How will you design a generic `RiskRule` interface (Protocol) so that new rules can be plugged into a list or chain without changing existing code? *(Look up the **Chain of Responsibility** or **Composite** patterns in Ronald Mak's "Software Design for Python Developers").*
* Does the engine stop evaluating on the first failing rule (fast-fail), or run all rules to collect all failure reasons?

### C. Application Orchestration (Risk Manager)
* How will your `RiskManager` subscribe to `SignalEvent`s on the `EventRouter`?
* When a signal arrives, how does the manager feed it through your risk rules?
* If all rules pass, what event does it emit? If any rule fails, what event does it emit, and how does it explain *why* the trade was rejected?

---

## 3. Definition of Success

Your bounded context is ready for review when:
1. **Composable Rule Contract**: A clean `RiskRule` protocol that allows adding or removing rules like building blocks.
2. **Core MVP Rules**: Working implementations for at least Max Order Size and an emergency Kill Switch.
3. **Dual Event Routing**: Signals that pass cleanly emit `RiskApprovedEvent`; signals that violate rules emit `RiskRejectedEvent` with explicit error details.
4. **Test-Driven Rigor**: Pure unit tests proving that bad signals and tripped kill switches are rejected 100% of the time with `pytest`.
