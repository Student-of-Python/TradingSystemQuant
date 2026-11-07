'''
tests/unit/test_risk_manager.py

Awaiting router to be finished implementing to check
'''

from collections.abc import Callable, Iterable
from decimal import Decimal

import pytest

from src.risk.domain.rules import KillSwitchRule, MaxOrderValueRule, MaxUnitSizeRule, RiskRule
from src.risk.domain.value import RuleViolation
from src.risk.manager import RiskManager
from src.strategy.domain.enums import StrategyAction
from src.strategy.domain.events import SignalEvent


def make_signal() -> SignalEvent:
    return SignalEvent(
        symbol="AAPL",
        action=StrategyAction.BUY,
        units=Decimal("10"),
        confidence=Decimal("0.8"),
        strategy_name="test_strategy",
    )

class PassRule(RiskRule):
    def __init__(self, name: str = "pass") -> None:
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        self.calls += 1
        return None

def _no_violation(self: object, signal: SignalEvent) -> None:
    return None

def make_duck(**attrs: object) -> object:
    return type("Duck", (), attrs)()

def test_valid_rules_are_accepted():
   # Guards the tests below: if __init__ always raised, they would all pass.
    RiskManager([PassRule("a"), PassRule("b")])

@pytest.mark.parametrize(
    "make_rules",
    [lambda: [PassRule()], lambda: (PassRule(),), lambda: (r for r in [PassRule()]), lambda: {PassRule(): 1}], # pyright: ignore[reportUnknownLambdaType]
    ids=["list", "tuple", "generator", "dict-keys"],
)
def test_any_iterable_of_rules_is_accepted(make_rules: Callable[[], Iterable[RiskRule]]):
    RiskManager(make_rules())

def test_duck_typed_rule_that_does_not_inherit_risk_rule_is_accepted():
    RiskManager([make_duck(name="duck", evaluate=_no_violation)]) # pyright: ignore[reportArgumentType]

def test_names_that_differ_only_by_case_are_not_duplicates():
    RiskManager([PassRule("rule"), PassRule("RULE")])

@pytest.mark.parametrize(
    "make_rules",
    [lambda: (), lambda: [], lambda: (r for r in ()), lambda: {}], # pyright: ignore[reportUnknownLambdaType]
    ids=["tuple", "list", "generator", "dict"],
)
def test_empty_rules_are_refused(make_rules: Callable[[], Iterable[RiskRule]]):
    with pytest.raises(ValueError, match="at least one rule"):
        RiskManager(make_rules())

@pytest.mark.parametrize("bad", [None, 5, PassRule()], ids=["none", "int", "single-rule-not-in-a-list"])
def test_non_iterable_rules_are_refused(bad: object):
    with pytest.raises(TypeError):
        RiskManager(bad) # pyright: ignore[reportArgumentType]


def test_a_string_is_not_treated_as_a_list_of_rules():
   # tuple("ab") == ("a", "b"); each letter must then fail validation.
    with pytest.raises(TypeError, match="non-empty string 'name'"):
        RiskManager("ab") # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    "rule",
    [
        make_duck(evaluate=_no_violation),
        make_duck(name=None, evaluate=_no_violation),
        make_duck(name=5, evaluate=_no_violation),
        make_duck(name=b"bytes", evaluate=_no_violation),
        make_duck(name="", evaluate=_no_violation),
        make_duck(name="   ", evaluate=_no_violation),
        make_duck(name="\t\n", evaluate=_no_violation),
    ],
    ids=["missing", "none", "int", "bytes", "empty", "spaces", "tab-newline"],
)
def test_rule_without_a_usable_name_is_refused(rule: object):
    with pytest.raises(TypeError, match="non-empty string 'name'"):
        RiskManager([rule]) # pyright: ignore[reportArgumentType]

@pytest.mark.parametrize(
    "rule",
    [
        make_duck(name="no_evaluate"),
        make_duck(name="none_evaluate", evaluate=None),
        make_duck(name="int_evaluate", evaluate=5),
        make_duck(name="str_evaluate", evaluate="evaluate"),
    ],
    ids=["missing", "none", "int", "str"],
)
def test_rule_without_a_callable_evaluate_is_refused(rule: object):
    with pytest.raises(TypeError, match="callable 'evaluate'"):
        RiskManager([rule]) # pyright: ignore[reportArgumentType]

def test_a_non_rule_object_is_refused():
    with pytest.raises(TypeError):
        RiskManager([object()]) # pyright: ignore[reportArgumentType]

def test_duplicate_rule_names_are_refused():
    with pytest.raises(ValueError, match=r"Duplicate rule name 'same' at rules\[1\]"):
        RiskManager([PassRule("same"), PassRule("same")])

def test_the_same_rule_object_twice_is_refused():
    rule = PassRule("once")

    with pytest.raises(ValueError, match="Duplicate rule name 'once'"):
        RiskManager([rule, rule])

def test_duplicate_is_reported_at_its_second_position():
    with pytest.raises(ValueError, match=r"rules\[2\]"):
        RiskManager([PassRule("a"), PassRule("b"), PassRule("a")])

def test_error_points_at_the_bad_rules_position():
    with pytest.raises(TypeError, match=r"rules\[1\]"):
        RiskManager([PassRule("ok"), make_duck(name="", evaluate=_no_violation)]) # pyright: ignore[reportArgumentType]

def test_error_names_the_bad_rules_type():
    with pytest.raises(TypeError, match=r"\(Duck\)"):
        RiskManager([make_duck(name="", evaluate=_no_violation)]) # pyright: ignore[reportArgumentType]

def test_first_bad_rule_is_the_one_reported():
    with pytest.raises(TypeError, match=r"rules\[0\]"):
        RiskManager([make_duck(name=""), make_duck(name=None)]) # pyright: ignore[reportArgumentType]

def test_name_is_checked_before_evaluate():
    with pytest.raises(TypeError, match="non-empty string 'name'"):
        RiskManager([make_duck()]) # pyright: ignore[reportArgumentType]

def test_signal_before_registration_raises():
    manager = RiskManager([PassRule()])

    with pytest.raises(RuntimeError, match="before register_subscriptions"):
        manager._on_signal(make_signal()) # pyright: ignore[reportPrivateUsage]

def test_signal_before_registration_evaluates_no_rules():
    rule = PassRule()
    manager = RiskManager([rule])

    with pytest.raises(RuntimeError):
        manager._on_signal(make_signal()) # pyright: ignore[reportPrivateUsage]

    assert rule.calls == 0

def test_the_mvp_rule_set_is_accepted():
    RiskManager([MaxUnitSizeRule(Decimal("100")), MaxOrderValueRule(Decimal("10000")), KillSwitchRule(engaged=False)])

def test_two_unit_caps_with_different_limits_are_accepted():
    RiskManager([MaxUnitSizeRule(Decimal("100")), MaxUnitSizeRule(Decimal("500"))])

def test_two_unit_caps_with_the_same_limit_are_refused():
    with pytest.raises(ValueError, match="Duplicate rule name"):
        RiskManager([MaxUnitSizeRule(Decimal("100")), MaxUnitSizeRule(Decimal("100"))])

def test_two_kill_switches_are_refused():
    with pytest.raises(ValueError, match="Duplicate rule name 'kill_switch_rule'"):
        RiskManager([KillSwitchRule(engaged=True), KillSwitchRule(engaged=False)])