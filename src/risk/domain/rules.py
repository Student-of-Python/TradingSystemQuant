"""Risk rules that validate strategy signals before execution."""

from abc import abstractmethod
from decimal import Decimal
from typing import Protocol

from src.risk.domain.value import RuleViolation
from src.strategy.domain.events import SignalEvent


class RiskRule(Protocol):
    """Structural interface implemented by every risk rule."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique name used to identify the rule."""
        ...

    @abstractmethod
    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        """Return a violation when the signal fails this rule."""
        ...


def check_risk_rule(obj: object, where: str) -> str:
    """
    Validate the runtime shape required of a risk rule.

    Args:
        obj: The object to validate as a risk rule.
        where: A location label used in validation error messages.

    Returns:
        The validated rule name.

    Raises:
        TypeError: If the object has no non-empty string name or callable
            ``evaluate`` method.
    """
    kind = type(obj).__name__
    name = getattr(obj, "name", None)

    if not isinstance(name, str) or not name.strip():
        raise TypeError(
            f"{where} ({kind}) must have a non-empty string 'name', got {name!r}."
        )
    if not callable(getattr(obj, "evaluate", None)):
        raise TypeError(f"{where} ({kind}) must have a callable 'evaluate'.")

    return name


class MaxOrderValueRule(RiskRule):
    """Reject orders whose notional value exceeds a configured maximum."""

    @property
    def name(self) -> str:
        """Return the rule name including the configured value limit."""
        return f"max_order_value_rule[{self._max_order_value}]"

    def __init__(self, max_order_value: Decimal) -> None:
        """Configure the maximum notional value permitted for an order.

        Args:
            max_order_value: The greatest allowed product of units and price.

        Raises:
            TypeError: If ``max_order_value`` is not a ``Decimal``.
            ValueError: If the value is non-finite or not positive.
        """
        # Decimal accepts floats and returns the direct conversion
        if not isinstance(max_order_value, Decimal):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(
                f"max_order_value must be a Decimal, got {type(max_order_value).__name__}."
            )
        if not max_order_value.is_finite():
            raise ValueError(
                f"max_order_value must be a finite number, got {max_order_value}."
            )
        if max_order_value <= 0:
            raise ValueError(
                f"max_order_value must be a greater than 0, got {max_order_value}."
            )

        self._max_order_value = max_order_value

    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        """Return a violation when the signal's order value is too large.

        Args:
            signal: The strategy signal whose order value should be checked.

        Returns:
            A violation when the order exceeds the configured maximum;
            otherwise ``None``.
        """
        if signal.units * signal.price > self._max_order_value:
            return RuleViolation(
                rule_name=self.name,
                reason=f"An order with a value of {signal.units * signal.price} exceeds the order value limit of {self._max_order_value}.",
            )


class MaxUnitSizeRule(RiskRule):
    """Reject orders containing more units than a configured maximum."""

    @property
    def name(self) -> str:
        """
        Return the rule name including the configured unit limit.

        Returns:
            The unique name of this risk rule.
        """
        return f"max_unit_size_rule[{self._max_units}]"

    def __init__(self, max_units: Decimal) -> None:
        """
        Configure the maximum number of units permitted in an order.

        Args:
            max_units: The greatest number of units an order may contain.

        Raises:
            TypeError: If ``max_units`` is not a ``Decimal``.
            ValueError: If the value is non-finite or not positive.
        """
        # Decimal accepts floats and returns the direct conversion
        if not isinstance(max_units, Decimal):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(
                f"max_units must be a Decimal, got {type(max_units).__name__}."
            )
        if not max_units.is_finite():
            raise ValueError(f"max_units must be a finite number, got {max_units}.")
        if max_units <= 0:
            raise ValueError(f"max_units must be greater than 0, got {max_units}.")

        self._max_units = max_units

    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        """
        Return a violation when a signal contains too many units.

        Args:
            signal: The strategy signal whose unit count should be checked.

        Returns:
            A violation when the unit count is invalid or exceeds the limit;
            otherwise ``None``.
        """
        units = signal.units

        if not isinstance(units, Decimal) or not units.is_finite():  # pyright: ignore[reportUnnecessaryIsInstance]
            return RuleViolation(
                rule_name=self.name,
                reason=f"units must be a finite Decimal, got {units!r}.",
            )
        if units > self._max_units:
            return RuleViolation(
                rule_name=self.name,
                reason=f"{units} units exceeds the limit of {self._max_units}.",
            )


class KillSwitchRule(RiskRule):
    """Reject every signal while the configured kill switch is engaged."""

    @property
    def name(self) -> str:
        """Return the stable name of the kill-switch rule."""
        return "kill_switch_rule"

    def __init__(self, engaged: bool) -> None:
        """
        Configures whether the kill switch is active. The switch state determines whether signals are blocked.

        Args:
            engaged: Whether the kill switch should block signals.

        Raises:
            TypeError: If ``engaged`` is not a boolean.
        """
        # Any parameter that evaluates to false may be able to silently turn the kill switch off
        if not isinstance(engaged, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"engaged must be a bool, got {type(engaged).__name__}.")

        self._engaged = engaged

    def evaluate(self, signal: SignalEvent) -> RuleViolation | None:
        """
        Return a violation when the kill switch is engaged.

        Args:
            signal: The strategy signal to approve or block. It is unused when
                the switch state alone determines the result.

        Returns:
            A violation when the switch is engaged; otherwise ``None``.
        """
        if self._engaged:
            return RuleViolation(rule_name=self.name, reason="kill switch engaged.")
