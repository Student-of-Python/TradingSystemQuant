import unittest

from src.spine.events import Metric, MetricEvent, SignalEvent
from src.strategy.strategy_output import StrategyOutput, split_output


class SplitOutputTest(unittest.TestCase):
    def test_split_copies_trade_and_metrics(self):
        metrics = [Metric("rsi", 55.0), Metric("sharpe", 1.2)]
        output = StrategyOutput("AAPL", "BUY", 10, 0.8, "momentum", metrics)

        signal, metric = split_output(output)

        self.assertEqual(signal, SignalEvent("AAPL", "BUY", 10, 0.8, "momentum"))
        self.assertEqual(metric, MetricEvent("AAPL", "momentum", metrics))

    def test_metrics_list_is_a_copy(self):
        metrics = [Metric("rsi", 55.0)]
        output = StrategyOutput("AAPL", "HOLD", 0, 0.0, "momentum", metrics)

        signal, metric = split_output(output)
        metrics.append(Metric("sharpe", 1.2))

        self.assertEqual(metric.metrics, [Metric("rsi", 55.0)])

    def test_output_is_frozen(self):
        output = StrategyOutput("AAPL", "SELL", 2, 0.4, "momentum", [])

        with self.assertRaises(AttributeError):
            output.action = "BUY"


if __name__ == "__main__":
    unittest.main()
