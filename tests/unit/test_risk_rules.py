"""
tests/unit/test_risk_rules.py
"""

from decimal import Decimal, localcontext

import pytest

from src.risk.domain.rules import (
    KillSwitchRule,
    MaxOrderValueRule,
    MaxUnitSizeRule,
    RiskRule,
    check_risk_rule,
)
from src.risk.domain.value import RuleViolation
from src.strategy.domain.enums import StrategyAction
from src.strategy.domain.events import SignalEvent


def make_signal(
    units: str = "10",
    price: str = "100.00",
    action: StrategyAction = StrategyAction.BUY,
) -> SignalEvent:
    return SignalEvent(
        symbol="AAPL",
        action=action,
        units=Decimal(units),
        # price=Decimal(price),
        confidence=Decimal("0.8"),
        strategy_name="test_strategy",
        price=Decimal(price),
    )


# Invalid rule configurations
NON_FINITE = [
    Decimal("NaN"),
    Decimal("sNaN"),
    Decimal("Infinity"),
    Decimal("-Infinity"),
]
NON_POSITIVE = [Decimal("0"), Decimal("-0"), Decimal("-1"), Decimal("-0.01")]
WRONG_TYPES: list[object] = [100.0, 100, True, None, "100"]
ALL_ACTIONS = list(StrategyAction)


def test_rule_without_evaluate_function_cannot_be_constructed():
    class Forgetful(RiskRule):
        @property
        def name(self) -> str:
            return "forgetful"

    with pytest.raises(TypeError, match="abstract method 'evaluate'"):
        Forgetful()  # type: ignore[abstract]


def test_rule_without_name_property_cannot_be_constructed():
    class Forgetful(RiskRule):
        def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
            return None

    with pytest.raises(TypeError, match="abstract method 'name'"):
        Forgetful()  # type: ignore[abstract]


@pytest.mark.parametrize(
    "rule",
    [
        MaxUnitSizeRule(Decimal("100")),
        MaxOrderValueRule(Decimal("10000")),
        KillSwitchRule(engaged=False),
    ],
    ids=["max_units", "max_order_value", "kill_switch"],
)
def _valid_evaluate(self: object, signal: SignalEvent) -> None:
    return None


def make_object(**attrs: object) -> object:
    return type("Thing", (), attrs)()


@pytest.mark.parametrize(
    "rule",
    [
        MaxUnitSizeRule(Decimal("100")),
        MaxOrderValueRule(Decimal("10000")),
        KillSwitchRule(engaged=False),
    ],
    ids=["max_units", "max_order_value", "kill_switch"],
)
def test_check_risk_rule_accepts_every_real_rule_and_returns_its_name(rule: RiskRule):
    assert check_risk_rule(rule, "rule") == rule.name


def test_check_risk_rule_accepts_a_duck_typed_rule():
    assert (
        check_risk_rule(make_object(name="duck", evaluate=_valid_evaluate), "rule")
        == "duck"
    )


@pytest.mark.parametrize(
    "thing",
    [
        make_object(evaluate=_valid_evaluate),
        make_object(name=None, evaluate=_valid_evaluate),
        make_object(name=5, evaluate=_valid_evaluate),
        make_object(name=b"bytes", evaluate=_valid_evaluate),
        make_object(name="", evaluate=_valid_evaluate),
        make_object(name=" \t\n", evaluate=_valid_evaluate),
        None,
        "kill_switch_rule",
    ],
    ids=[
        "missing",
        "none",
        "int",
        "bytes",
        "empty",
        "blank",
        "None-object",
        "str-object",
    ],
)
def test_check_risk_rule_refuses_an_unusable_name(thing: object):
    with pytest.raises(TypeError, match="non-empty string 'name'"):
        check_risk_rule(thing, "rule")


@pytest.mark.parametrize(
    "thing",
    [
        make_object(name="no_evaluate"),
        make_object(name="none", evaluate=None),
        make_object(name="int", evaluate=5),
        make_object(name="str", evaluate="evaluate"),
    ],
    ids=["missing", "none", "int", "str"],
)
def test_check_risk_rule_refuses_a_non_callable_evaluate(thing: object):
    with pytest.raises(TypeError, match="callable 'evaluate'"):
        check_risk_rule(thing, "rule")


def test_check_risk_rule_error_says_where_and_what_type():
    with pytest.raises(TypeError, match=r"^rules\[3\] \(Thing\) "):
        check_risk_rule(make_object(name=""), "rules[3]")


def test_check_risk_rule_checks_name_before_evaluate():
    with pytest.raises(TypeError, match="non-empty string 'name'"):
        check_risk_rule(make_object(), "rule")


class TestMaxUnitSizeRule:
    @pytest.mark.parametrize("units", ["100", "50", "10", "1", "0.5", "100.00"])
    def test_name_includes_the_limit_as_given(self, units: str):
        assert MaxUnitSizeRule(Decimal(units)).name == f"max_unit_size_rule[{units}]"

    def test_rules_with_different_limits_have_different_names(self):
        assert (
            MaxUnitSizeRule(Decimal("100")).name != MaxUnitSizeRule(Decimal("101")).name
        )

    @pytest.mark.parametrize("units", ["-5", "0", "1", "99", "99.99", "100", "100.00"])
    def test_at_or_under_limit_passes(self, units: str):
        assert (
            MaxUnitSizeRule(Decimal("100")).evaluate(make_signal(units=units)) is None
        )

    @pytest.mark.parametrize(
        "units", ["100.0000001", "100.01", "101", "1000000", "Infinity"]
    )
    def test_over_limit_is_rejected(self, units: str):
        rule = MaxUnitSizeRule(Decimal("100"))

        violation = rule.evaluate(make_signal(units=units))

        assert isinstance(violation, RuleViolation)
        assert violation.rule_name == rule.name

    def test_rejection_reason_states_units_and_limit(self):
        violation = MaxUnitSizeRule(Decimal("100")).evaluate(make_signal(units="150"))

        assert violation is not None
        assert "150" in violation.reason
        assert "100" in violation.reason

    @pytest.mark.parametrize("action", ALL_ACTIONS)
    def test_limit_applies_to_every_action(self, action: StrategyAction):
        assert (
            MaxUnitSizeRule(Decimal("100")).evaluate(
                make_signal(units="101", action=action)
            )
            is not None
        )

    def test_fractional_limit_works(self):
        rule = MaxUnitSizeRule(Decimal("0.5"))

        assert rule.evaluate(make_signal(units="0.5")) is None
        assert rule.evaluate(make_signal(units="0.51")) is not None

    def test_evaluate_gives_the_same_answer_every_time(self):
        rule = MaxUnitSizeRule(Decimal("100"))
        signal = make_signal(units="150")

        assert rule.evaluate(signal) == rule.evaluate(signal)

    @pytest.mark.parametrize("units", ["NaN", "sNaN", "-NaN", "Infinity", "-Infinity"])
    def test_non_finite_units_are_rejected(self, units: str):
        rule = MaxUnitSizeRule(Decimal("100"))

        violation = rule.evaluate(make_signal(units=units))

        assert isinstance(violation, RuleViolation)
        assert violation.rule_name == rule.name
        assert "finite" in violation.reason

    @pytest.mark.parametrize(
        "units", [99.5, 50, "10", None], ids=["float", "int", "str", "none"]
    )
    def test_non_decimal_units_are_rejected(self, units: object):
        signal = SignalEvent(
            symbol="AAPL",
            action=StrategyAction.BUY,
            units=units,  # pyright: ignore[reportArgumentType]
            confidence=Decimal("0.8"),
            strategy_name="test_strategy",
            price=Decimal("150.00"),
        )

        violation = MaxUnitSizeRule(Decimal("100")).evaluate(signal)

        assert isinstance(violation, RuleViolation)
        assert "finite Decimal" in violation.reason

    @pytest.mark.parametrize("limit", NON_POSITIVE + NON_FINITE)
    def test_invalid_limit_value_raises(self, limit: Decimal):
        with pytest.raises(ValueError):
            MaxUnitSizeRule(limit)

    @pytest.mark.parametrize("limit", WRONG_TYPES)
    def test_non_decimal_limit_raises(self, limit: object):
        with pytest.raises(TypeError, match="must be a Decimal"):
            MaxUnitSizeRule(limit)  # type: ignore[arg-type]


class TestMaxOrderValueRule:
    @pytest.mark.parametrize("limit", ["10000", "3000", "1", "0.30"])
    def test_name_includes_the_limit_as_given(self, limit: str):
        assert (
            MaxOrderValueRule(Decimal(limit)).name == f"max_order_value_rule[{limit}]"
        )

    @pytest.mark.parametrize("limit", NON_POSITIVE + NON_FINITE)
    def test_invalid_limit_value_raises(self, limit: Decimal):
        with pytest.raises(ValueError):
            MaxOrderValueRule(limit)

    @pytest.mark.parametrize("limit", WRONG_TYPES)
    def test_non_decimal_limit_raises(self, limit: object):
        with pytest.raises(TypeError, match="must be a Decimal"):
            MaxOrderValueRule(limit)  # type: ignore[arg-type]

    def test_under_limit_passes(self):
        rule = MaxOrderValueRule(Decimal("10000.00"))

        assert rule.evaluate(make_signal(units="10", price="100.00")) is None

    def test_exactly_at_limit_passes(self):
        rule = MaxOrderValueRule(Decimal("10000.00"))

        assert rule.evaluate(make_signal(units="100", price="100.00")) is None

    def test_one_cent_over_limit_is_rejected(self):
        rule = MaxOrderValueRule(Decimal("10000.00"))

        violation = rule.evaluate(make_signal(units="1", price="10000.01"))

        assert isinstance(violation, RuleViolation)
        assert violation.rule_name == rule.name

    def test_sub_cent_excess_is_not_rounded_away(self):
        rule = MaxOrderValueRule(Decimal("10000.00"))

        assert rule.evaluate(make_signal(units="1", price="10000.004")) is not None

    def test_limit_with_cents_is_exact(self):
        rule = MaxOrderValueRule(Decimal("0.30"))

        assert rule.evaluate(make_signal(units="3", price="0.10")) is None

    def test_rejection_reason_states_order_value_and_limit(self):
        violation = MaxOrderValueRule(Decimal("10000")).evaluate(
            make_signal(units="200", price="100")
        )

        assert violation is not None
        assert "20000" in violation.reason
        assert "10000" in violation.reason

    @pytest.mark.parametrize("action", ALL_ACTIONS)
    def test_limit_applies_to_every_action(self, action: StrategyAction):
        rule = MaxOrderValueRule(Decimal("10000"))

        assert (
            rule.evaluate(make_signal(units="200", price="100", action=action))
            is not None
        )


class TestKillSwitchRule:
    @pytest.mark.parametrize("engaged", [True, False])
    def test_name_is_the_same_whether_engaged_or_not(self, engaged: bool):
        assert KillSwitchRule(engaged=engaged).name == "kill_switch_rule"

    # TODO: LIQUIDATE is included on purpose but must be decided whether to exempt or not
    @pytest.mark.parametrize("action", ALL_ACTIONS)
    @pytest.mark.parametrize("units", ["0", "1", "-1", "1000000", "NaN", "Infinity"])
    def test_engaged_rejects_every_signal(self, action: StrategyAction, units: str):
        rule = KillSwitchRule(engaged=True)

        violation = rule.evaluate(make_signal(units=units, action=action))

        assert isinstance(violation, RuleViolation)
        assert violation.rule_name == rule.name

    def test_engaged_reason_says_the_switch_is_engaged(self):
        violation = KillSwitchRule(engaged=True).evaluate(make_signal())

        assert violation is not None
        assert "kill switch engaged" in violation.reason

    def test_engaged_rejects_every_time_not_just_once(self):
        rule = KillSwitchRule(engaged=True)

        assert all(rule.evaluate(make_signal()) is not None for _ in range(5))

    @pytest.mark.parametrize("action", ALL_ACTIONS)
    @pytest.mark.parametrize("units", ["0", "1", "1000000"])
    def test_disengaged_passes_every_signal(self, action: StrategyAction, units: str):
        assert (
            KillSwitchRule(engaged=False).evaluate(
                make_signal(units=units, action=action)
            )
            is None
        )

    @pytest.mark.parametrize("engaged", [None, 0, 1, "", "false", "true", 0.0])
    def test_non_bool_state_raises(self, engaged: object):
        # A value that evaluates to false (i.e. None, 0, "") must never silently turn off the switch.
        with pytest.raises(TypeError, match="must be a bool"):
            KillSwitchRule(engaged=engaged)  # type: ignore[arg-type]

    def test_two_switches_do_not_share_state(self):
        on, off = KillSwitchRule(engaged=True), KillSwitchRule(engaged=False)

        assert on.evaluate(make_signal()) is not None
        assert off.evaluate(make_signal()) is None


class TestMaxUnitSizeRuleDecimal:
    def test_tiny_excess_beyond_the_default_precision_is_still_rejected(self):
        units = "100." + "0" * 40 + "1"

        assert (
            MaxUnitSizeRule(Decimal("100")).evaluate(make_signal(units=units))
            is not None
        )

    def test_low_context_precision_does_not_round_away_an_excess(self):
        with localcontext() as ctx:
            ctx.prec = 2
            violation = MaxUnitSizeRule(Decimal("100")).evaluate(
                make_signal(units="100.4")
            )

        assert violation is not None

    def test_tiny_positive_units_pass(self):
        assert (
            MaxUnitSizeRule(Decimal("100")).evaluate(make_signal(units="1E-999999"))
            is None
        )

    def test_two_rules_with_different_limits_do_not_share_state(self):
        small, large = MaxUnitSizeRule(Decimal("10")), MaxUnitSizeRule(Decimal("1000"))
        signal = make_signal(units="500")

        assert small.evaluate(signal) is not None
        assert large.evaluate(signal) is None
