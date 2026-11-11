from decimal import Decimal
import unittest

from src.core.router import EventRouter
from src.data.domain.events import MarketBarEvent
from src.strategy.domain.enums import StrategyAction
from src.strategy.domain.events import SignalEvent
from src.strategy.domain.value import StrategyOutput
from src.strategy.manager import StrategyManager


class FakeStrategy:
    def __init__(self, output=None):
        self.output = output
        self.warmed = False

    @property
    def strategy_id(self) -> str:
        return "fake"

    def on_warmup(self, historical_bars) -> None:
        self.warmed = True

    def on_bar(self, bar) -> StrategyOutput | None:
        return self.output


class StrategyManagerTest(unittest.TestCase):
    def test_publishes_signal(self):
        output = StrategyOutput(
            "AAPL",
            StrategyAction.BUY,
            Decimal("1"),
            Decimal("1"),
            "fake",
            Decimal("100"),
        )
        manager = StrategyManager([FakeStrategy(output)])
        router = EventRouter()
        manager.register_subscriptions(router)

        published = []
        router.subscribe(SignalEvent, published.append)
        router.publish(MarketBarEvent())
        router.dispatch_next()
        router.dispatch_next()

        self.assertEqual(len(published), 1)
        self.assertEqual(published[0].price, Decimal("100"))

    def test_none_publishes_nothing(self):
        manager = StrategyManager([FakeStrategy(None)])
        router = EventRouter()
        manager.register_subscriptions(router)

        published = []
        router.subscribe(SignalEvent, published.append)
        router.publish(MarketBarEvent())
        router.dispatch_next()

        self.assertEqual(published, [])

    def test_warmup_does_not_publish(self):
        strategy = FakeStrategy(
            StrategyOutput(
                "AAPL",
                StrategyAction.BUY,
                Decimal("1"),
                Decimal("1"),
                "fake",
                Decimal("100"),
            )
        )
        manager = StrategyManager([strategy])
        router = EventRouter()
        manager.register_subscriptions(router)

        published = []
        router.subscribe(SignalEvent, published.append)
        manager.warmup([])

        self.assertTrue(strategy.warmed)
        self.assertEqual(published, [])


if __name__ == "__main__":
    unittest.main()
