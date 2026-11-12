"""RiskManager construction, decision-making, and router integration tests."""

from collections.abc import Callable, Iterable
from decimal import Decimal

import pytest

from src.core.router import EventRouter
from src.risk.domain.events import RiskApprovedEvent, RiskRejectedEvent
from src.risk.domain.rules import (
    KillSwitchRule,
    MaxOrderValueRule,
    MaxUnitSizeRule,
    RiskRule,
)
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
        price=Decimal("150.00"),
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
    [
        lambda: [PassRule()],
        lambda: (PassRule(),),
        lambda: (r for r in [PassRule()]),
        lambda: {PassRule(): 1},
    ],  # pyright: ignore[reportUnknownLambdaType]
    ids=["list", "tuple", "generator", "dict-keys"],
)
def test_any_iterable_of_rules_is_accepted(
    make_rules: Callable[[], Iterable[RiskRule]],
):
    RiskManager(make_rules())


def test_duck_typed_rule_that_does_not_inherit_risk_rule_is_accepted():
    RiskManager([make_duck(name="duck", evaluate=_no_violation)])  # pyright: ignore[reportArgumentType]


def test_names_that_differ_only_by_case_are_not_duplicates():
    RiskManager([PassRule("rule"), PassRule("RULE")])


@pytest.mark.parametrize(
    "make_rules",
    [lambda: (), lambda: [], lambda: (r for r in ()), lambda: {}],  # pyright: ignore[reportUnknownLambdaType]
    ids=["tuple", "list", "generator", "dict"],
)
def test_empty_rules_are_refused(make_rules: Callable[[], Iterable[RiskRule]]):
    with pytest.raises(ValueError, match="at least one rule"):
        RiskManager(make_rules())


@pytest.mark.parametrize(
    "bad", [None, 5, PassRule()], ids=["none", "int", "single-rule-not-in-a-list"]
)
def test_non_iterable_rules_are_refused(bad: object):
    with pytest.raises(TypeError):
        RiskManager(bad)  # pyright: ignore[reportArgumentType]


def test_a_string_is_not_treated_as_a_list_of_rules():
    # tuple("ab") == ("a", "b"); each letter must then fail validation.
    with pytest.raises(TypeError, match="non-empty string 'name'"):
        RiskManager("ab")  # pyright: ignore[reportArgumentType]


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
        RiskManager([rule])  # pyright: ignore[reportArgumentType]


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
        RiskManager([rule])  # pyright: ignore[reportArgumentType]


def test_a_non_rule_object_is_refused():
    with pytest.raises(TypeError):
        RiskManager([object()])  # pyright: ignore[reportArgumentType]


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
        RiskManager([PassRule("ok"), make_duck(name="", evaluate=_no_violation)])  # pyright: ignore[reportArgumentType]


def test_error_names_the_bad_rules_type():
    with pytest.raises(TypeError, match=r"\(Duck\)"):
        RiskManager([make_duck(name="", evaluate=_no_violation)])  # pyright: ignore[reportArgumentType]


def test_first_bad_rule_is_the_one_reported():
    with pytest.raises(TypeError, match=r"rules\[0\]"):
        RiskManager([make_duck(name=""), make_duck(name=None)])  # pyright: ignore[reportArgumentType]


def test_name_is_checked_before_evaluate():
    with pytest.raises(TypeError, match="non-empty string 'name'"):
        RiskManager([make_duck()])  # pyright: ignore[reportArgumentType]


def test_signal_before_registration_raises():
    manager = RiskManager([PassRule()])

    with pytest.raises(RuntimeError, match="before register_subscriptions"):
        manager._on_signal(make_signal())  # pyright: ignore[reportPrivateUsage]


def test_signal_before_registration_evaluates_no_rules():
    rule = PassRule()
    manager = RiskManager([rule])

    with pytest.raises(RuntimeError):
        manager._on_signal(make_signal())  # pyright: ignore[reportPrivateUsage]

    assert rule.calls == 0


def test_registering_with_the_same_router_twice_is_idempotent():
    rule = PassRule()
    manager = RiskManager([rule])
    router = EventRouter()

    manager.register_subscriptions(router)
    manager.register_subscriptions(router)
    router.publish(make_signal())
    router.dispatch_next()

    assert rule.calls == 1


def test_registering_with_a_different_router_is_refused():
    manager = RiskManager([PassRule()])
    first_router = EventRouter()
    second_router = EventRouter()

    manager.register_subscriptions(first_router)

    with pytest.raises(RuntimeError, match="different router"):
        manager.register_subscriptions(second_router)


def test_router_dispatch_evaluates_signal_and_publishes_approval():
    manager = RiskManager([PassRule()])
    router = EventRouter()
    published: list[RiskApprovedEvent | RiskRejectedEvent] = []

    manager.register_subscriptions(router)
    router.subscribe([RiskApprovedEvent, RiskRejectedEvent], published.append)
    signal = make_signal()

    router.publish(signal)
    router.dispatch_next()

    assert published == []
    router.dispatch_next()

    assert len(published) == 1
    assert isinstance(published[0], RiskApprovedEvent)
    assert published[0].signal is signal


def test_router_dispatch_publishes_rejection_for_a_failing_rule():
    manager = RiskManager([FakeRule("blocked", fails=True)])
    router = EventRouter()
    published: list[RiskApprovedEvent | RiskRejectedEvent] = []

    manager.register_subscriptions(router)
    router.subscribe([RiskApprovedEvent, RiskRejectedEvent], published.append)
    signal = make_signal()

    router.publish(signal)
    router.dispatch_next()
    router.dispatch_next()

    assert len(published) == 1
    assert isinstance(published[0], RiskRejectedEvent)
    assert published[0].signal is signal
    assert violation_names(published[0]) == ["blocked"]


def test_the_mvp_rule_set_is_accepted():
    RiskManager(
        [
            MaxUnitSizeRule(Decimal("100")),
            MaxOrderValueRule(Decimal("10000")),
            KillSwitchRule(engaged=False),
        ]
    )


def test_two_unit_caps_with_different_limits_are_accepted():
    RiskManager([MaxUnitSizeRule(Decimal("100")), MaxUnitSizeRule(Decimal("500"))])


def test_two_unit_caps_with_the_same_limit_are_refused():
    with pytest.raises(ValueError, match="Duplicate rule name"):
        RiskManager([MaxUnitSizeRule(Decimal("100")), MaxUnitSizeRule(Decimal("100"))])


def test_two_kill_switches_are_refused():
    with pytest.raises(ValueError, match="Duplicate rule name 'kill_switch_rule'"):
        RiskManager([KillSwitchRule(engaged=True), KillSwitchRule(engaged=False)])


class FakeRule(RiskRule):
    def __init__(
        self,
        name: str,
        *,
        fails: bool = False,
        raises: BaseException | None = None,
        log: list[str] | None = None,
    ) -> None:
        self._name = name
        self._fails = fails
        self._raises = raises
        self._log = log
        self.seen: list[SignalEvent] = []

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        self.seen.append(signal)
        if self._log is not None:
            self._log.append(self._name)
        if self._raises is not None:
            raise self._raises
        if self._fails:
            return RuleViolation(rule_name=self._name, reason=f"{self._name} failed")
        return None


class ReturnsRule(RiskRule):
    def __init__(self, value: object) -> None:
        self._value = value

    @property
    def name(self) -> str:
        return "returns_junk"

    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        return self._value  # pyright: ignore[reportReturnType]


def violation_names(verdict: RiskApprovedEvent | RiskRejectedEvent) -> list[str]:
    assert isinstance(verdict, RiskRejectedEvent), (
        f"expected a rejection, got {verdict!r}"
    )
    return [v.rule_name for v in verdict.violations]


def test_decide_needs_no_router():
    assert isinstance(
        RiskManager([FakeRule("a")]).decide(make_signal()), RiskApprovedEvent
    )


def test_all_rules_passing_gives_an_approval():
    verdict = RiskManager([FakeRule("a"), FakeRule("b")]).decide(make_signal())

    assert isinstance(verdict, RiskApprovedEvent)


def test_approval_carries_the_same_signal_object():
    signal = make_signal()

    verdict = RiskManager([FakeRule("a")]).decide(signal)

    assert verdict.signal is signal


def test_one_failing_rule_gives_a_rejection_naming_only_that_rule():
    verdict = RiskManager(
        [FakeRule("a"), FakeRule("bad", fails=True), FakeRule("c")]
    ).decide(make_signal())

    assert violation_names(verdict) == ["bad"]


def test_rejection_carries_the_same_signal_object():
    signal = make_signal()

    verdict = RiskManager([FakeRule("bad", fails=True)]).decide(signal)

    assert isinstance(verdict, RiskRejectedEvent)
    assert verdict.signal is signal


def test_rules_after_a_failure_are_still_run():
    rules = [FakeRule("bad", fails=True), FakeRule("b"), FakeRule("c")]

    RiskManager(rules).decide(make_signal())

    assert [len(r.seen) for r in rules] == [1, 1, 1]


def test_rules_run_in_the_order_given():
    log: list[str] = []
    manager = RiskManager(
        [FakeRule("c", log=log), FakeRule("a", log=log), FakeRule("b", log=log)]
    )

    manager.decide(make_signal())

    assert log == ["c", "a", "b"]


def test_every_rule_receives_the_same_signal_object():
    rules = [FakeRule("a"), FakeRule("b"), FakeRule("c")]
    signal = make_signal()

    RiskManager(rules).decide(signal)

    assert all(len(r.seen) == 1 and r.seen[0] is signal for r in rules)


def test_each_call_runs_every_rule_once_and_gives_its_own_verdict():
    rules = [FakeRule("a"), FakeRule("b")]
    manager = RiskManager(rules)
    s1, s2 = make_signal(), make_signal()

    first = manager.decide(s1)
    second = manager.decide(s2)

    assert [len(r.seen) for r in rules] == [2, 2]
    assert first.signal is s1
    assert second.signal is s2


@pytest.mark.parametrize("position", [0, 1, 2], ids=["first", "middle", "last"])
def test_engaged_kill_switch_rejects_when_every_other_rule_passes(position: int):
    rules: list[RiskRule] = [FakeRule("a"), FakeRule("b")]
    rules.insert(position, KillSwitchRule(engaged=True))

    assert violation_names(RiskManager(rules).decide(make_signal())) == [
        "kill_switch_rule"
    ]


@pytest.mark.parametrize("action", list(StrategyAction))
def test_engaged_kill_switch_rejects_every_action(action: StrategyAction):
    signal = SignalEvent(
        symbol="AAPL",
        action=action,
        units=Decimal("1"),
        confidence=Decimal("0.8"),
        strategy_name="test_strategy",
        price=Decimal("150.00"),
    )

    verdict = RiskManager([KillSwitchRule(engaged=True), FakeRule("a")]).decide(signal)

    assert isinstance(verdict, RiskRejectedEvent)


def test_disengaged_kill_switch_with_passing_rules_approves():
    verdict = RiskManager([KillSwitchRule(engaged=False), FakeRule("a")]).decide(
        make_signal()
    )

    assert isinstance(verdict, RiskApprovedEvent)


def test_rules_from_a_generator_still_apply_on_later_calls():
    manager = RiskManager(r for r in [FakeRule("bad", fails=True)])

    assert isinstance(manager.decide(make_signal()), RiskRejectedEvent)
    assert isinstance(manager.decide(make_signal()), RiskRejectedEvent)


def test_copies_passed_in_rules():
    rules: list[RiskRule] = [FakeRule("bad", fails=True)]
    manager = RiskManager(rules)

    rules.clear()

    assert isinstance(manager.decide(make_signal()), RiskRejectedEvent)


def test_adding_to_the_passed_in_rules_does_not_add_rules():
    rules: list[RiskRule] = [FakeRule("a")]
    manager = RiskManager(rules)

    rules.append(FakeRule("added_later", fails=True))

    assert isinstance(manager.decide(make_signal()), RiskApprovedEvent)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("rule blew up"),
        ValueError("bad"),
        ZeroDivisionError(),
        KeyError("missing"),
    ],
    ids=["runtime", "value", "empty-message", "key"],
)
def test_a_raising_rule_gives_a_rejection_naming_it(error: Exception):
    verdict = RiskManager([FakeRule("ok"), FakeRule("boom", raises=error)]).decide(
        make_signal()
    )

    assert violation_names(verdict) == ["boom"]


def test_raising_rule_reason_names_the_error_type_and_message():
    verdict = RiskManager([FakeRule("boom", raises=ValueError("bad input"))]).decide(
        make_signal()
    )

    assert isinstance(verdict, RiskRejectedEvent)
    assert "ValueError" in verdict.violations[0].reason
    assert "bad input" in verdict.violations[0].reason


def test_an_error_with_no_message_still_gives_a_non_blank_reason():
    verdict = RiskManager([FakeRule("boom", raises=RuntimeError())]).decide(
        make_signal()
    )

    assert isinstance(verdict, RiskRejectedEvent)
    assert verdict.violations[0].reason.strip()


@pytest.mark.parametrize("position", [0, 1], ids=["raiser-first", "raiser-last"])
def test_engaged_kill_switch_still_rejects_when_another_rule_raises(position: int):
    rules: list[RiskRule] = [KillSwitchRule(engaged=True)]
    rules.insert(position, FakeRule("boom", raises=RuntimeError("x")))

    names = violation_names(RiskManager(rules).decide(make_signal()))

    assert sorted(names) == ["boom", "kill_switch_rule"]


def test_rules_after_a_raising_rule_are_still_run():
    after = FakeRule("after")

    RiskManager([FakeRule("boom", raises=RuntimeError("x")), after]).decide(
        make_signal()
    )

    assert len(after.seen) == 1


@pytest.mark.parametrize(
    "junk",
    [False, 0, "", "failed", True, 1.5],
    ids=["false", "zero", "empty-str", "str", "true", "float"],
)
def test_a_rule_returning_junk_gives_a_rejection_naming_it(junk: object):
    verdict = RiskManager([ReturnsRule(junk)]).decide(make_signal())

    assert violation_names(verdict) == ["returns_junk"]


def test_junk_reason_names_the_type_returned():
    verdict = RiskManager([ReturnsRule("failed")]).decide(make_signal())

    assert isinstance(verdict, RiskRejectedEvent)
    assert "str" in verdict.violations[0].reason
