'''
market_data/feed.py
'''
from typing import Protocol, Sequence
from datetime import datetime
from enums import TimeResolution
from src.spine.events import MarketBarEvent

class MarketDataProvider(Protocol):
    '''
    Protocol for data providers
    '''

    def get_historical_bars(self,
                            symbol: str,
                            start: datetime,
                            end: datetime,
                            timeframe: TimeResolution = TimeResolution.DAILY) -> Sequence[MarketBarEvent]: #We'll focus on the output later; it'll most likely be returned to router instead
        '''Fetches historical bars to warm up a strategy'''
        ...

    def start_stream(self, symbol: Sequence[str]) -> None:
        '''Listens to live market bar updates and publish to router'''
        ...

    def stop_stream(self) -> None:
        '''Closes stream'''
        ...


#There a better provider than alpaca? I know Alpaca, Yfinance have delays on live tickers.
class AlpacaDataFeed:
    '''
    Alpaca Market feed
    #TODO: Complete
    '''

