'''
src/data/feed.py

Port (interface) between the data context and any vendor.
Swapping Alpaca -> IBKR / yfinance / CSV = write one new adapter in src/data/adapters/, nothing here changes.
'''
from datetime import datetime
from typing import Protocol, Sequence

from src.data.domain.enums import TimeResolution
from src.data.domain.value import MarketBar


class MarketDataProvider(Protocol):
    '''
    Protocol for data providers. Adapters hand back domain MarketBars, never vendor objects / DataFrames.
    '''

    def get_historical_bars(self,
                            symbol: str,
                            start: datetime,
                            end: datetime,
                            timeframe: TimeResolution = TimeResolution.DAILY) -> Sequence[MarketBar]:
        '''Fetches historical bars to warm up a strategy, oldest first'''
        ...

    def start_stream(self, symbols: Sequence[str]) -> None:
        '''Listens to live market bar updates and publish to router'''
        ...

    def stop_stream(self) -> None:
        '''Closes stream'''
        ...
