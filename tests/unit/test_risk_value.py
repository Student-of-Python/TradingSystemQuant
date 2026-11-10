'''
tests/unit/test_risk_value.py
'''

from dataclasses import FrozenInstanceError

import pytest

from src.risk.domain.value import RuleViolation

BLANKS = ["", " ", "\t\n", " "]

def test_holds_rule_name_and_reason():
    violation = RuleViolation(rule_name="max_unit_size_rule", reason="150 units exceeds the limit of 100.")

    assert violation.rule_name == "max_unit_size_rule"
    assert violation.reason == "150 units exceeds the limit of 100."

def test_values_are_stored_exactly_as_given():
    violation = RuleViolation(rule_name="  rule  ", reason=" reason ")

    assert violation.rule_name == "  rule  "
    assert violation.reason == " reason "

@pytest.mark.parametrize("blank", BLANKS)
def test_blank_rule_name_is_refused(blank: str):
    with pytest.raises(ValueError, match="must name the violated rule"):
        RuleViolation(rule_name=blank, reason="some reason")

@pytest.mark.parametrize("blank", BLANKS)
def test_blank_reason_is_refused(blank: str):
    with pytest.raises(ValueError, match="must name a reason"):
        RuleViolation(rule_name="some_rule", reason=blank)

def test_rule_name_is_checked_before_reason():
    with pytest.raises(ValueError, match="must name the violated rule"):
        RuleViolation(rule_name="", reason="")

def test_positional_arguments_are_refused():
    with pytest.raises(TypeError):
        RuleViolation("some_rule", "some reason") # type: ignore[misc]

@pytest.mark.parametrize("missing", ["rule_name", "reason"])
def test_both_fields_are_required(missing: str):
    kwargs = {"rule_name": "some_rule", "reason": "some reason"}
    del kwargs[missing]

    with pytest.raises(TypeError):
        RuleViolation(**kwargs) # pyright: ignore[reportCallIssue]

@pytest.mark.parametrize("bad", [None, 5, b"rule"], ids=["none", "int", "bytes"])
def test_non_str_fields_are_refused_with_type_error(bad: object):
    with pytest.raises(TypeError):
        RuleViolation(rule_name=bad, reason="some reason") # pyright: ignore[reportArgumentType]

@pytest.mark.parametrize("field", ["rule_name", "reason"])
def test_fields_cannot_be_changed(field: str):
    violation = RuleViolation(rule_name="some_rule", reason="some reason")

    with pytest.raises(FrozenInstanceError):
        setattr(violation, field, "changed")

def test_new_attributes_cannot_be_added():
    violation = RuleViolation(rule_name="some_rule", reason="some reason")

    with pytest.raises((FrozenInstanceError, AttributeError)):
        violation.extra = "x"  # pyright: ignore[reportAttributeAccessIssue]

def test_equal_values_are_equal():
    assert RuleViolation(rule_name="r", reason="x") == RuleViolation(rule_name="r", reason="x")

@pytest.mark.parametrize(
    "other",
    [RuleViolation(rule_name="other", reason="x"), RuleViolation(rule_name="r", reason="other")],
    ids=["different-name", "different-reason"],
)
def test_different_values_are_not_equal(other: RuleViolation):
    assert RuleViolation(rule_name="r", reason="x") != other

def test_equal_violations_hash_the_same_and_dedupe_in_a_set():
    a = RuleViolation(rule_name="r", reason="x")
    b = RuleViolation(rule_name="r", reason="x")

    assert hash(a) == hash(b)
    assert len({a, b}) == 1

def test_repr_shows_both_fields():
    text = repr(RuleViolation(rule_name="some_rule", reason="some reason"))

    assert "some_rule" in text
    assert "some reason" in text