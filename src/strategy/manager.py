'''
src/strategy/manager.py
'''
from src.core.router import EventRouter
from src.data.domain.events import MarketBarEvent
from src.strategy.domain.events import SignalEvent


class StrategyManager:
    def __init__(self, strategies):
        self._strategies = list(strategies)
        self._router: EventRouter | None = None

    def warmup(self, bars) -> None:
        for strategy in self._strategies:
            strategy.on_warmup(bars)

    def register_subscriptions(self, router: EventRouter) -> None:
        self._router = router
        router.subscribe(MarketBarEvent, self.on_market_bar)

    def on_market_bar(self, bar: MarketBarEvent) -> None:
        if self._router is None:
            return
        for strategy in self._strategies:
            output = strategy.on_bar(bar)
            if output is None:
                continue
            self._router.publish(
                SignalEvent(
                    symbol=output.symbol,
                    action=output.action,
                    units=output.units,
                    confidence=output.confidence,
                    strategy_name=output.strategy_name,
                    price=output.price,
                )
            )
