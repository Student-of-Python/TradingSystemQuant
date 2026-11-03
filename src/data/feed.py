'''
data/feed.py
'''
from src.data.domain.enums import TimeResolution
from typing import Protocol, Sequence, TypeAlias
from src.data.domain.value import MarketBar
from datetime import datetime
from pandas import DataFrame

HistoricalData: TypeAlias = pd.DataFrame | Sequence[MarketBar] #Will most likely have to stick with Dataframe because conversion cost between MarketBar and Dataframe is too expensive?


class MarketDataProvider(Protocol):
    '''
    Protocol for data providers
    '''

    def get_historical_bars(self,
                            symbol: str,
                            start: datetime,
                            end: datetime,
                            timeframe: TimeResolution = TimeResolution.DAILY) -> HistoricalData: #We'll focus on the output later
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
    ...
