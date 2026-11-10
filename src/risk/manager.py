'''
risk/manager.py
'''

from collections.abc import Iterable
from src.core.protocols import Subscribable
from src.core.router import EventRouter
from src.risk.domain.events import RiskApprovedEvent, RiskRejectedEvent
from src.risk.domain.rules import RiskRule, check_risk_rule
from src.risk.domain.value import RuleViolation
from src.strategy.domain.events import SignalEvent

class RiskManager(Subscribable):
    def __init__(self, rules: Iterable[RiskRule]) -> None:
        self._rules: tuple[RiskRule, ...] = tuple(rules)
        
        if not self._rules:
            raise ValueError(f"RiskManager needs at least one rule, got {self._rules}.")

        names: list[str] = []

        for i, rule in enumerate(self._rules):
            name = check_risk_rule(rule, f"rules[{i}]")

            if name in names:
                raise ValueError(f"Duplicate rule name {name!r} at rules[{i}].")

            names.append(name)

        self._rule_names: tuple[str, ...] = tuple(names)

        self._router: EventRouter | None = None
        
    def register_subscriptions(self, router: EventRouter) -> None:
        if self._router is router:
            return
        if self._router is not None:
            raise RuntimeError(f"RiskManager is already registered with a different router, currently subscribed to {self._router}.") # TODO: Perhaps we should make a list of routers later to be able to tell, if this error occurs, which router the RiskManager is subscribed to? 
        
        self._router = router
        
        router.subscribe(SignalEvent, self._on_signal)
        
    def decide(self, signal: SignalEvent) -> RiskApprovedEvent | RiskRejectedEvent:
        violations: list[RuleViolation] = []

        for rule, name in zip(self._rules, self._rule_names):
            try:
                result = rule.evaluate(signal)
            except Exception as error:
                violations.append(RuleViolation(rule_name=name, reason=f"Rule raised {type(error).__name__}: {error}"))
                continue

            if result is None:
                continue
            if not isinstance(result, RuleViolation): # pyright: ignore[reportUnnecessaryIsInstance]
                violations.append(RuleViolation(rule_name=name, reason=f"Rule returned {type(result).__name__}, not a RuleViolation or None."))
                continue

            violations.append(result)
            
        if violations:
            return RiskRejectedEvent(signal=signal, violations=tuple(violations))
        
        return RiskApprovedEvent(signal=signal, rules_checked=self._rules)

    def _on_signal(self, signal: SignalEvent) -> None:
        router = self._router

        if router is None:
            raise RuntimeError(f"RiskManager._on_signal called before register_subscriptions().")

        router.publish(self.decide(signal))