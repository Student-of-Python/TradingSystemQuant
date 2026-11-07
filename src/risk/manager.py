'''
risk/manager.py
'''

from collections.abc import Iterable
from src.core.protocols import Subscribable
from src.core.router import EventRouter
from src.risk.domain.events import RiskApprovedEvent, RiskRejectedEvent
from src.risk.domain.rules import RiskRule, check_risk_rule
from src.strategy.domain.events import SignalEvent

class RiskManager(Subscribable):
    def __init__(self, rules: Iterable[RiskRule]) -> None:
        self._rules: tuple[RiskRule, ...] = tuple(rules)
        
        if not self._rules:
            raise ValueError(f"RiskManager needs at least one rule, got {self._rules}.")

        seen: set[str] = set()
        
        for i, rule in enumerate(self._rules):
            name = check_risk_rule(rule, f"rules[{i}]")

            if name in seen:
                raise ValueError(f"Duplicate rule name {name!r} at rules[{i}].")
            
            seen.add(name)
        
        self._router: EventRouter | None = None
        
    def register_subscriptions(self, router: EventRouter) -> None:
        if self._router is router:
            return
        if self._router is not None:
            raise RuntimeError(f"RiskManager is already registered with a different router, currently subscribed to {self._router}.") # TODO: Perhaps we should make a list of routers later to be able to tell, if this error occurs, which router the RiskManager is subscribed to? 
        
        self._router = router
        
        router.subscribe(SignalEvent, self._on_signal)
        
    def _on_signal(self, signal: SignalEvent) -> None:
        router = self._router
        
        if router is None:
            raise RuntimeError(f"RiskManager._on_signal called before register_subscriptions().")
        
        violations = tuple(v for rule in self._rules if (v := rule.evaluate(signal)) is not None)

        if violations:
            router.publish(RiskRejectedEvent(signal=signal, violations=violations))
        else:
            router.publish(RiskApprovedEvent(signal=signal, rules_checked=self._rules))