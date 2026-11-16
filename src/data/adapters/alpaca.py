'''
src/data/adapters/alpaca.py

Anti-corruption layer for Alpaca. Alpaca's types stop here; everything leaving this file is a MarketBar.
'''
from functools import lru_cache
from datetime import datetime
from typing import Any, ClassVar, Sequence

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from src.data.domain.enums import TimeResolution
from src.data.domain.value import MarketBar


class AlpacaDataFeed:
    '''
    Alpaca market feed. Historical only for now.
    '''
    _TIMEFRAMES: ClassVar[dict[TimeResolution, TimeFrame]] = {
        TimeResolution.MINUTE: TimeFrame.Minute,
        TimeResolution.HOURLY: TimeFrame.Hour,
        TimeResolution.DAILY: TimeFrame.Day,
    }

    def __init__(self, api_key: str, secret_key: str, client: Any | None = None):
        if client is None:
            client = StockHistoricalDataClient(api_key, secret_key)
        self._client = client

    @staticmethod
    def bar_from_alpaca(raw: Any, resolution: TimeResolution) -> MarketBar:
        '''Translates one alpaca.data.models.Bar into a MarketBar.'''
        return MarketBar.from_dict({
            "symbol": raw.symbol,
            "timestamp": raw.timestamp,
            "resolution": resolution,
            "open": raw.open,
            "high": raw.high,
            "low": raw.low,
            "close": raw.close,
            "volume": raw.volume,
            "vwap": getattr(raw, "vwap", None),
            "trade_count": getattr(raw, "trade_count", None),
        })

    def get_historical_bars(self,
                            symbol: str,
                            start: datetime,
                            end: datetime,
                            timeframe: TimeResolution = TimeResolution.DAILY) -> Sequence[MarketBar]:
        '''Fetches historical bars to warm up a strategy, oldest first'''
        return list(self._get_historical_bars(symbol, start, end, timeframe))

    @lru_cache(maxsize=256)
    def _get_historical_bars(self,
                             symbol: str,
                             start: datetime,
                             end: datetime,
                             timeframe: TimeResolution) -> tuple[MarketBar, ...]:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            start=start,
            end=end,
            timeframe=self._TIMEFRAMES[timeframe],
        )
        raw_bars = self._client.get_stock_bars(request).data.get(symbol, [])
        bars = [self.bar_from_alpaca(b, timeframe) for b in raw_bars]
        return tuple(sorted(bars, key=lambda b: b.timestamp))

    def start_stream(self, symbols: Sequence[str]) -> None:
        raise NotImplementedError("live streaming not built yet")

    def stop_stream(self) -> None:
        raise NotImplementedError("live streaming not built yet")


def bar_from_alpaca(raw: Any, resolution: TimeResolution) -> MarketBar:
    '''Backward-compatible wrapper; prefer AlpacaDataFeed.bar_from_alpaca.'''
    return AlpacaDataFeed.bar_from_alpaca(raw, resolution)
