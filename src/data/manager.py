'''
src/data/manager.py

Application service for the data context. Pulls bars from a provider (any adapter) and
publishes them to the router as MarketBarEvents. Nobody calls into data directly (Decoupling Rule).
'''
from datetime import datetime
from typing import Sequence

from src.core.router import EventRouter
from src.data.domain.enums import TimeResolution
from src.data.domain.events import MarketBarEvent
from src.data.feed import MarketDataProvider


class DataManager:
    def __init__(self, provider: MarketDataProvider, router: EventRouter):
        self._provider = provider
        self._router = router

    def warmup(self,
               symbols: Sequence[str],
               start: datetime,
               end: datetime,
               timeframe: TimeResolution = TimeResolution.DAILY) -> int:
        '''
        Fetches history for every symbol and publishes one MarketBarEvent per bar.
        Bars from all symbols are merged by timestamp, so subscribers see time move forward
        the same way it would live (AAPL 9:30, MSFT 9:30, AAPL 9:31...), not all of AAPL then all of MSFT.
        Returns how many events were published.
        '''
        bars = []
        for symbol in symbols:
            bars.extend(self._provider.get_historical_bars(symbol, start, end, timeframe))
        bars.sort(key=lambda b: (b.timestamp, b.symbol))

        self._router.publish(*(MarketBarEvent(bar=b) for b in bars))
        return len(bars)

    # Lifecycle (src/core/protocols.py) -- live streaming isn't built yet, adapters raise NotImplementedError
    def start(self, symbols: Sequence[str]) -> None:
        self._provider.start_stream(symbols)

    def stop(self) -> None:
        self._provider.stop_stream()
