'''
market_data/feed.py
'''
from typing import Protocol, Sequence, TypeAlias
from datetime import datetime
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from src.market_data.enums import TimeResolution
from src.market_data.value_objects import MarketBar
from pandas import DataFrame

HistoricalData: TypeAlias = DataFrame | Sequence[MarketBar] #Will most likely have to stick with Dataframe because conversion cost between MarketBar and Dataframe is too expensive?


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
    '''

    _TIMEFRAMES = {
        TimeResolution.MINUTE: TimeFrame.Minute,
        TimeResolution.HOURLY: TimeFrame.Hour,
        TimeResolution.DAILY: TimeFrame.Day,
    }

    def __init__(self, api_key: str, secret_key: str):
        self._client = StockHistoricalDataClient(api_key, secret_key)

    def get_historical_bars(self,
                            symbol: str,
                            start: datetime,
                            end: datetime,
                            timeframe: TimeResolution = TimeResolution.DAILY) -> DataFrame:
        '''Fetches historical bars to warm up a strategy'''
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            start=start,
            end=end,
            timeframe=self._TIMEFRAMES[timeframe],
        )
        return self._client.get_stock_bars(request).df
