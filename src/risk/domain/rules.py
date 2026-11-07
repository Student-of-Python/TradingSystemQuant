'''
risk/domain/rules.py
'''

from decimal import Decimal

from typing import Protocol, runtime_checkable

from abc import abstractmethod

from src.strategy.domain.events import SignalEvent
from src.risk.domain.value import RuleViolation

@runtime_checkable
class RiskRule(Protocol):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def evaluate(self, signal: SignalEvent) -> RuleViolation | None: ...

def check_risk_rule(obj: object, where: str) -> str:
    '''
    isinstance(obj, RiskRule) only checks that the attributes exist,
    so a blank name or a non-callable evaluate would get through.
    '''
    kind = type(obj).__name__
    name = getattr(obj, "name", None)

    if not isinstance(name, str) or not name.strip():
        raise TypeError(f"{where} ({kind}) must have a non-empty string 'name', got {name!r}.")
    if not callable(getattr(obj, "evaluate", None)):
        raise TypeError(f"{where} ({kind}) must have a callable 'evaluate'.")

    return name

class MaxOrderValueRule(RiskRule):
    @property
    def name(self) -> str:
        return f"max_order_value_rule[{self._max_order_value}]"

    def __init__(self, max_order_value: Decimal) -> None:
        # Decimal accepts floats and returns the direct conversion
        if not isinstance(max_order_value, Decimal): # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"max_order_value must be a Decimal, got {type(max_order_value).__name__}.")
        if not max_order_value.is_finite():
            raise ValueError(f"max_order_value must be a finite number, got {max_order_value}.")
        if max_order_value <= 0:
            raise ValueError(f"max_order_value must be a greater than 0, got {max_order_value}.")
        
        self._max_order_value = max_order_value
        
    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        # TODO: Awaiting signal.price implementation
        if signal.units * signal.price > self._max_order_value:
            return RuleViolation(rule_name=self.name, reason=f"An order with a value of {signal.units * signal.price} exceeds the order value limit of {self._max_order_value}.")

class MaxUnitSizeRule(RiskRule):
    @property
    def name(self) -> str:
        return f"max_unit_size_rule[{self._max_units}]"
    
    def __init__(self, max_units: Decimal) -> None:
        # Decimal accepts floats and returns the direct conversion
        if not isinstance(max_units, Decimal): # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"max_units must be a Decimal, got {type(max_units).__name__}.")
        if not max_units.is_finite():
            raise ValueError(f"max_units must be a finite number, got {max_units}.")
        if max_units < 0:
            raise ValueError(f"max_units must be greater than 0, got {max_units}.")
        
        self._max_units = max_units

    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        units = signal.units
        
        if not isinstance(units, Decimal) or not units.is_finite(): # pyright: ignore[reportUnnecessaryIsInstance]
            return RuleViolation(rule_name=self.name, reason=f"units must be a finite Decimal, got {units!r}.")
        if units > self._max_units:
            return RuleViolation(rule_name=self.name, reason=f"{units} units exceeds the limit of {self._max_units}.")

class KillSwitchRule(RiskRule):
    @property
    def name(self) -> str:
        return "kill_switch_rule"
    
    def __init__(self, engaged: bool) -> None:
        # Any parameter that evaluates to false may be able to silently turn the kill switch off
        if not isinstance(engaged, bool): # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"engaged must be a bool, got {type(engaged).__name__}.")
        
        self._engaged = engaged

    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        if self._engaged:
            return RuleViolation(rule_name=self.name, reason=f"kill switch engaged.")