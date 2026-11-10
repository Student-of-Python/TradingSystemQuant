'''
risk/domain/value.py
'''

from dataclasses import dataclass

@dataclass(frozen=True, slots=True, kw_only=True)
class RuleViolation:
    rule_name: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.rule_name, str): # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"rule_name must be a string, got {type(self.rule_name).__name__}.")
        if not isinstance(self.reason, str): # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"reason must be a string, got {type(self.reason).__name__}.")
        if not self.rule_name.strip():
            raise ValueError(f"A RuleViolation must name the violated rule, got {self.rule_name!r}.")
        if not self.reason.strip():
            raise ValueError(f"A RuleViolation must name a reason, got {self.reason!r}.")