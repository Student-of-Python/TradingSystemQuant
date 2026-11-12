'''
tests/unit/test_risk_events.py
'''

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.core.base_event import BaseEvent
from src.risk.domain.events import RiskApprovedEvent, RiskRejectedEvent
from src.risk.domain.rules import KillSwitchRule, MaxUnitSizeRule
from src.risk.domain.value import RuleViolation
from src.strategy.domain.enums import StrategyAction
from src.strategy.domain.events import SignalEvent


def make_signal() -> SignalEvent:
    return SignalEvent(
        symbol="AAPL",
        action=StrategyAction.BUY,
        units=Decimal("10"),
        confidence=Decimal("0.8"),
        strategy_name="test_strategy",
        price=Decimal("150.00")
    )

RULE = MaxUnitSizeRule(Decimal("100"))
OTHER_RULE = KillSwitchRule(engaged=False)
VIOLATION = RuleViolation(rule_name="some_rule", reason="some reason")
OTHER_VIOLATION = RuleViolation(rule_name="other_rule", reason="other reason")
NOT_A_SIGNAL: list[object] = [None, "AAPL", 5, object(), BaseEvent()]

def approved(**overrides: object) -> RiskApprovedEvent:
    kwargs: dict[str, object] = {"signal": make_signal(), "rules_checked": (RULE,)}
    kwargs.update(overrides)
    return RiskApprovedEvent(**kwargs)  # pyright: ignore[reportArgumentType]

def rejected(**overrides: object) -> RiskRejectedEvent:
    kwargs: dict[str, object] = {"signal": make_signal(), "violations": (VIOLATION,)}
    kwargs.update(overrides)
    return RiskRejectedEvent(**kwargs)  # pyright: ignore[reportArgumentType]

class TestRiskApprovedEvent:
    def test_carries_signal_and_rules_checked(self):
        signal = make_signal()
        event = RiskApprovedEvent(signal=signal, rules_checked=(RULE, OTHER_RULE))

        assert event.signal is signal
        assert event.rules_checked == (RULE, OTHER_RULE)

    def test_is_a_base_event(self):
        assert isinstance(approved(), BaseEvent)

    @pytest.mark.parametrize("bad", NOT_A_SIGNAL, ids=["none", "str", "int", "object", "base_event"])
    def test_non_signal_is_refused(self, bad: object):
        with pytest.raises(TypeError, match="signal must be a SignalEvent"):
            approved(signal=bad)

    @pytest.mark.parametrize("bad", [[RULE], {RULE}, None, RULE], ids=["list", "set", "none", "bare-rule"])
    def test_non_tuple_rules_checked_is_refused(self, bad: object):
        with pytest.raises(TypeError, match="must be a tuple"):
            approved(rules_checked=bad)

    def test_empty_rules_checked_is_refused(self):
        with pytest.raises(ValueError, match="at least one rule"):
            approved(rules_checked=())

    @pytest.mark.parametrize(
        "bad",
        ["max_unit_size_rule[100]", "", None, 5, VIOLATION],
        ids=["rule-name-str", "empty-str", "none", "int", "violation"],
    )
    def test_non_rule_in_rules_checked_is_refused(self, bad: object):
        with pytest.raises(TypeError, match=r"rules_checked\[0\]"):
            approved(rules_checked=(bad,))

    def test_one_bad_entry_among_good_rules_is_refused(self):
        with pytest.raises(TypeError):
            approved(rules_checked=(RULE, "not a rule", OTHER_RULE))

    def test_signal_is_checked_before_rules(self):
        with pytest.raises(TypeError, match="signal must be a SignalEvent"):
            approved(signal=None, rules_checked=())

    def test_is_keyword_only(self):
        with pytest.raises(TypeError):
            RiskApprovedEvent(make_signal(), (RULE,)) # type: ignore[misc]

    @pytest.mark.parametrize("field", ["signal", "rules_checked"])
    def test_fields_cannot_be_changed(self, field: str):
        event = approved()

        with pytest.raises(FrozenInstanceError):
            setattr(event, field, None)

class TestRiskRejectedEvent:
    def test_carries_signal_and_violations(self):
        signal = make_signal()
        event = RiskRejectedEvent(signal=signal, violations=(VIOLATION, OTHER_VIOLATION))

        assert event.signal is signal
        assert event.violations == (VIOLATION, OTHER_VIOLATION)

    def test_keeps_duplicate_violations(self):
        assert rejected(violations=(VIOLATION, VIOLATION)).violations == (VIOLATION, VIOLATION)

    def test_is_a_base_event(self):
        assert isinstance(rejected(), BaseEvent)

    @pytest.mark.parametrize("bad", NOT_A_SIGNAL, ids=["none", "str", "int", "object", "base_event"])
    def test_non_signal_is_refused(self, bad: object):
        with pytest.raises(TypeError, match="signal must be a SignalEvent"):
            rejected(signal=bad)

    @pytest.mark.parametrize("bad", [[VIOLATION], [], None, VIOLATION], ids=["list", "empty-list", "none", "bare-violation"])
    def test_non_tuple_violations_is_refused(self, bad: object):
        with pytest.raises(TypeError, match="collection of RuleViolation"):
            rejected(violations=bad)

    def test_empty_violations_is_refused(self):
        with pytest.raises(ValueError, match="empty"):
            rejected(violations=())

    @pytest.mark.parametrize(
        "bad",
        ["some_rule", None, 5, RULE, ("some_rule", "some reason")],
        ids=["str", "none", "int", "rule", "tuple"],
    )
    def test_non_violation_in_violations_is_refused(self, bad: object):
        with pytest.raises(TypeError, match="RuleViolation"):
            rejected(violations=(bad,))

    def test_one_bad_entry_among_good_violations_is_refused(self):
        with pytest.raises(TypeError):
            rejected(violations=(VIOLATION, "not a violation"))

    def test_signal_is_checked_before_violations(self):
        with pytest.raises(TypeError, match="signal must be a SignalEvent"):
            rejected(signal=None, violations=())

    def test_is_keyword_only(self):
        with pytest.raises(TypeError):
            RiskRejectedEvent(make_signal(), (VIOLATION,))  # type: ignore[misc]

    @pytest.mark.parametrize("field", ["signal", "violations"])
    def test_fields_cannot_be_changed(self, field: str):
        event = rejected()

        with pytest.raises(FrozenInstanceError):
            setattr(event, field, None)

@pytest.mark.parametrize("make", [approved, rejected], ids=["approved", "rejected"])
class TestCommonEventBehavior:
    def test_every_event_gets_a_unique_id(self, make: Callable[..., BaseEvent]):
        signal = make_signal()
        
        assert make(signal=signal).event_tag != make(signal=signal).event_tag

    def test_event_tag_starts_with_the_class_name(self, make: Callable[..., BaseEvent]):
        event = make()
        
        assert event.event_tag.startswith(f"{type(event).__name__}_")

    def test_created_at_is_now_in_utc(self, make: Callable[..., BaseEvent]):
        before = datetime.now(timezone.utc)
        event = make()
        after = datetime.now(timezone.utc)
        
        assert event.created_at.tzinfo is not None
        assert before - timedelta(milliseconds=2) <= event.created_at <= after + timedelta(milliseconds=2)

    def test_events_with_the_same_contents_are_still_different_events(self, make: Callable[..., BaseEvent]):
        signal = make_signal()

        assert make(signal=signal) != make(signal=signal)

def test_approval_and_rejection_are_different_types():
    assert not isinstance(approved(), RiskRejectedEvent)
    assert not isinstance(rejected(), RiskApprovedEvent)

class _NotCallableEvaluate:
    name = "fake"
    evaluate = 5

class _BlankName:
    name = "   "

    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        return None

def test_approval_refuses_a_rule_whose_evaluate_is_not_callable():
    with pytest.raises(TypeError, match="callable 'evaluate'"):
        approved(rules_checked=(_NotCallableEvaluate(),))

def test_approval_refuses_a_rule_with_a_blank_name():
    with pytest.raises(TypeError, match="non-empty string 'name'"):
        approved(rules_checked=(_BlankName(),))

def test_approval_error_points_at_the_bad_rules_position():
    with pytest.raises(TypeError, match=r"rules_checked\[1\] \(_NotCallableEvaluate\)"):
        approved(rules_checked=(RULE, _NotCallableEvaluate()))

def test_approval_keeps_the_same_rule_objects():
    event = approved(rules_checked=(RULE, OTHER_RULE))

    assert event.rules_checked[0] is RULE
    assert event.rules_checked[1] is OTHER_RULE

@pytest.mark.parametrize(
    "bad",
    [(r for r in [RULE]), frozenset({RULE}), {RULE: 1}],
    ids=["generator", "frozenset", "dict"],
)
def test_approval_refuses_other_iterables_of_rules(bad: object):
    with pytest.raises(TypeError, match="must be a tuple"):
        approved(rules_checked=bad)

@pytest.mark.parametrize("missing", ["signal", "rules_checked"])
def test_approval_fields_are_required(missing: str):
    kwargs: dict[str, object] = {"signal": make_signal(), "rules_checked": (RULE,)}
    del kwargs[missing]

    with pytest.raises(TypeError):
        RiskApprovedEvent(**kwargs)  # pyright: ignore[reportArgumentType]

@pytest.mark.parametrize(
    "bad",
    [(v for v in [VIOLATION]), frozenset({VIOLATION}), "some_rule: some reason"],
    ids=["generator", "frozenset", "str"],
)
def test_rejection_refuses_other_iterables_of_violations(bad: object):
    with pytest.raises(TypeError, match="collection of RuleViolation"):
        rejected(violations=bad)

def test_rejection_keeps_the_same_violation_objects():
    event = rejected(violations=(VIOLATION, OTHER_VIOLATION))

    assert event.violations[0] is VIOLATION
    assert event.violations[1] is OTHER_VIOLATION

@pytest.mark.parametrize("missing", ["signal", "violations"])
def test_rejection_fields_are_required(missing: str):
    kwargs: dict[str, object] = {"signal": make_signal(), "violations": (VIOLATION,)}
    del kwargs[missing]

    with pytest.raises(TypeError):
        RiskRejectedEvent(**kwargs) # pyright: ignore[reportArgumentType]

@pytest.mark.parametrize("make", [approved, rejected], ids=["approved", "rejected"])
def test_new_attributes_cannot_be_added(make: Callable[..., BaseEvent]):
    event = make()

    with pytest.raises((FrozenInstanceError, AttributeError)):
        event.extra = "x" # pyright: ignore[reportAttributeAccessIssue]

@pytest.mark.parametrize("make", [approved, rejected], ids=["approved", "rejected"])
def test_the_carried_signal_is_unchanged(make: Callable[..., RiskApprovedEvent | RiskRejectedEvent]):
    signal = make_signal()
    before = (signal.symbol, signal.action, signal.units, signal.confidence, signal.strategy_name, signal.event_tag)

    carried = make(signal=signal).signal

    after = (carried.symbol, carried.action, carried.units, carried.confidence, carried.strategy_name, carried.event_tag)
    assert after == before
