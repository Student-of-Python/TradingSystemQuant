from dataclasses import dataclass
from decimal import Decimal
import unittest

from src.strategy.domain.enums import StrategyAction
from src.strategy.sma_crossover import SmaCrossOverStrategy


@dataclass(frozen=True)
class Bar:
    symbol: str
    close: Decimal


class SmaCrossoverTest(unittest.TestCase):
    def test_no_signal_before_warmup(self):
        strategy = SmaCrossOverStrategy("AAPL", short_window=2, long_window=3)
        self.assertIsNone(strategy.on_bar(Bar("AAPL", Decimal("10"))))

    def test_cross_up_buys(self):
        strategy = SmaCrossOverStrategy("AAPL", short_window=2, long_window=3)
        strategy.on_warmup([
            Bar("AAPL", Decimal("10")),
            Bar("AAPL", Decimal("10")),
            Bar("AAPL", Decimal("10")),
        ])
        out = strategy.on_bar(Bar("AAPL", Decimal("13")))
        self.assertIsNotNone(out)
        self.assertEqual(out.action, StrategyAction.BUY)
        self.assertEqual(out.price, Decimal("13"))

    def test_no_cross_returns_none(self):
        strategy = SmaCrossOverStrategy("AAPL", short_window=2, long_window=3)
        strategy.on_warmup([
            Bar("AAPL", Decimal("10")),
            Bar("AAPL", Decimal("10")),
            Bar("AAPL", Decimal("10")),
        ])
        self.assertIsNone(strategy.on_bar(Bar("AAPL", Decimal("10"))))


if __name__ == "__main__":
    unittest.main()
