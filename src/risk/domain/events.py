"""Events emitted after risk evaluation."""

from dataclasses import dataclass

from src.core import BaseEvent

from src.strategy.domain.events import SignalEvent

from src.risk.domain.value import RuleViolation
from src.risk.domain.rules import RiskRule, check_risk_rule

@dataclass(frozen=True, slots=True, kw_only=True)
class RiskApprovedEvent(BaseEvent):
    """Represent a signal that passed every configured risk rule."""

    signal: SignalEvent
    rules_checked: tuple[RiskRule, ...]

    def __post_init__(self) -> None:
        """Validate the signal and ensure at least one valid rule was checked."""
        if not isinstance(self.signal, SignalEvent): # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"signal must be a SignalEvent, got {type(self.signal).__name__}.")  
        if not isinstance(self.rules_checked, tuple): # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"rules_checked must be a tuple, got {type(self.rules_checked).__name__}.")
        if not self.rules_checked:
            raise ValueError("An approval must have at least one rule that was checked.")
        
        for i, rule in enumerate(self.rules_checked):
            check_risk_rule(rule, f"rules_checked[{i}]")

@dataclass(frozen=True, slots=True, kw_only=True)
class RiskRejectedEvent(BaseEvent):
    """Represent a signal rejected by one or more risk-rule violations."""

    signal: SignalEvent
    violations: tuple[RuleViolation, ...]

    def __post_init__(self) -> None:
        """Validate that the rejection contains at least one violation."""
        if not isinstance(self.signal, SignalEvent): # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"signal must be a SignalEvent, got {type(self.signal).__name__}.")
        if not (isinstance(self.violations, tuple) and all(isinstance(v, RuleViolation) for v in self.violations)): # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"violations must be a collection of RuleViolation, got {self.violations}.")
        
        violations = tuple(self.violations)
        
        if not violations:
            raise ValueError("A rejection cannot have an empty list of violations.")
        for violation in violations:
            if not isinstance(violation, RuleViolation): # pyright: ignore[reportUnnecessaryIsInstance]
                raise TypeError(f"violations must contain RuleViolation, got {type(violation).__name__}.")
            
        object.__setattr__(self, "violations", violations)
