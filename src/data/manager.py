'''
src/data/manager.py

Application service for the data context. Pulls bars from a provider (any adapter) and
publishes them to the router as events. Nobody calls into data directly (Decoupling Rule).
'''
from datetime import datetime
from typing import Sequence

from src.core.router import EventRouter
from src.data.domain.enums import TimeResolution
from src.data.domain.events import HistoricalBarsEvent
from src.data.feed import MarketDataProvider


class DataManager:
    def __init__(self,
                 provider: MarketDataProvider,
                 router: EventRouter,
                 stream_symbols: Sequence[str] | None = None):
        self._provider = provider
        self._router = router
        self._stream_symbols = tuple(stream_symbols) if stream_symbols is not None else None

    def warmup(self,
               symbols: Sequence[str],
               start: datetime,
               end: datetime,
               timeframe: TimeResolution = TimeResolution.DAILY) -> int:
        '''
        Fetches history for every symbol and publishes one event carrying the full warmup.
        Bars from all symbols are merged by timestamp so consumers can replay time in order
        without forcing the router to handle one event per historical bar.
        Returns how many bars were loaded.
        '''
        bars = []
        for symbol in symbols:
            bars.extend(self._provider.get_historical_bars(symbol, start, end, timeframe))
        bars.sort(key=lambda b: (b.timestamp, b.symbol))

        if bars:
            self._router.publish(HistoricalBarsEvent(bars=tuple(bars)))
        return len(bars)

    # Lifecycle (src/core/protocols.py) -- live streaming isn't built yet, adapters raise NotImplementedError
    def start(self, symbols: Sequence[str] | None = None) -> None:
        symbols = symbols if symbols is not None else self._stream_symbols
        if symbols is None:
            raise ValueError("stream_symbols are required to start data streaming")
        self._provider.start_stream(symbols)

    def stop(self) -> None:
        self._provider.stop_stream()
