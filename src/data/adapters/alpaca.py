'''
src/data/adapters/alpaca.py

Anti-corruption layer for Alpaca. Alpaca's types stop here; everything leaving this file is a MarketBar.
alpaca-py is imported lazily so the rest of the system (and the tests) don't need it installed.
'''
from datetime import datetime
from typing import Any, Sequence

from src.data.domain.enums import TimeResolution
from src.data.domain.value import MarketBar


def bar_from_alpaca(raw: Any, resolution: TimeResolution) -> MarketBar:
    '''Translates one alpaca.data.models.Bar (or anything with the same attributes) into a MarketBar'''
    return MarketBar(
        symbol=raw.symbol,
        timestamp=raw.timestamp,
        resolution=resolution,
        open=raw.open,
        high=raw.high,
        low=raw.low,
        close=raw.close,
        volume=raw.volume,
        vwap=getattr(raw, "vwap", None),
        trade_count=getattr(raw, "trade_count", None),
    )


class AlpacaDataFeed:
    '''
    Alpaca market feed. Historical only for now.
    '''

    def __init__(self, api_key: str, secret_key: str, client: Any | None = None):
        if client is None:
            from alpaca.data.historical import StockHistoricalDataClient
            client = StockHistoricalDataClient(api_key, secret_key)
        self._client = client

    @staticmethod
    def _timeframe(resolution: TimeResolution) -> Any:
        from alpaca.data.timeframe import TimeFrame
        return {
            TimeResolution.MINUTE: TimeFrame.Minute,
            TimeResolution.HOURLY: TimeFrame.Hour,
            TimeResolution.DAILY: TimeFrame.Day,
        }[resolution]

    def get_historical_bars(self,
                            symbol: str,
                            start: datetime,
                            end: datetime,
                            timeframe: TimeResolution = TimeResolution.DAILY) -> Sequence[MarketBar]:
        '''Fetches historical bars to warm up a strategy, oldest first'''
        from alpaca.data.requests import StockBarsRequest
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            start=start,
            end=end,
            timeframe=self._timeframe(timeframe),
        )
        raw_bars = self._client.get_stock_bars(request).data.get(symbol, [])
        bars = [bar_from_alpaca(b, timeframe) for b in raw_bars]
        return sorted(bars, key=lambda b: b.timestamp)

    def start_stream(self, symbols: Sequence[str]) -> None:
        raise NotImplementedError("live streaming not built yet")

    def stop_stream(self) -> None:
        raise NotImplementedError("live streaming not built yet")
