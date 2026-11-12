from decimal import Decimal
import unittest

from src.strategy.domain.enums import StrategyAction
from src.strategy.domain.events import SignalEvent
from src.strategy.domain.value import StrategyOutput


class StrategyOutputTest(unittest.TestCase):
    def test_signal_has_price(self):
        signal = SignalEvent(
            "AAPL",
            StrategyAction.BUY,
            Decimal("10"),
            Decimal("0.8"),
            "momentum",
            Decimal("150.25"),
        )
        self.assertEqual(signal.price, Decimal("150.25"))

    def test_output_is_frozen(self):
        output = StrategyOutput(
            "AAPL",
            StrategyAction.SELL,
            Decimal("2"),
            Decimal("0.4"),
            "momentum",
            Decimal("100"),
        )
        with self.assertRaises(AttributeError):
            output.action = StrategyAction.BUY


if __name__ == "__main__":
    unittest.main()
