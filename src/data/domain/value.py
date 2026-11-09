'''
src/data/domain/value.py

Pure stdlib. No vendor libraries in here (see data/design.md, Purity Rule).
'''
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from src.data.domain.enums import TimeResolution
from src.data.domain.errors import InvalidMarketDataError


def _to_decimal(value: Any, name: str) -> Decimal:
    '''Converts to Decimal through str so floats don't drag binary noise in (0.1 -> 0.1, not 0.1000000000000000055...)'''
    if isinstance(value, bool):
        raise InvalidMarketDataError(f"{name} can't be a bool")
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise InvalidMarketDataError(f"{name} is not a number: {value!r}") from None
    if not d.is_finite():
        raise InvalidMarketDataError(f"{name} must be finite, got {value!r}")
    return d


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketBar:
    '''
    One OHLCV bar for one symbol over one time window.

    symbol (str): Ticker, upper-cased.
    timestamp (datetime): Start of the bar window. Timezone-aware, stored in UTC.
    resolution (TimeResolution): Bar size.
    open/high/low/close (Decimal): Prices, > 0.
    volume (Decimal): Shares traded, >= 0.
    vwap (Decimal | None): Volume weighted avg price, if the vendor gives it.
    trade_count (int | None): Number of trades in the bar, if the vendor gives it.
    '''
    symbol: str
    timestamp: datetime
    resolution: TimeResolution
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    vwap: Decimal | None = None
    trade_count: int | None = None

    def __post_init__(self) -> None:
        # frozen dataclass -> normalize with object.__setattr__
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise InvalidMarketDataError("symbol is missing")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())

        if not isinstance(self.timestamp, datetime):
            raise InvalidMarketDataError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise InvalidMarketDataError("timestamp must be timezone-aware")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(timezone.utc))

        if not isinstance(self.resolution, TimeResolution):
            raise InvalidMarketDataError(f"resolution must be a TimeResolution, got {self.resolution!r}")

        for name in ("open", "high", "low", "close", "volume"):
            object.__setattr__(self, name, _to_decimal(getattr(self, name), name))
        if self.vwap is not None:
            object.__setattr__(self, "vwap", _to_decimal(self.vwap, "vwap"))

        if min(self.open, self.high, self.low, self.close) <= 0:
            raise InvalidMarketDataError("prices must be positive")
        if self.volume < 0:
            raise InvalidMarketDataError("volume can't be negative")
        if self.high < max(self.open, self.close, self.low):
            raise InvalidMarketDataError("high is below open/close/low")
        if self.low > min(self.open, self.close):
            raise InvalidMarketDataError("low is above open/close")
        # vwap is an average of trade prices inside the bar, so it has to sit in [low, high]
        if self.vwap is not None and not (self.low <= self.vwap <= self.high):
            raise InvalidMarketDataError("vwap is outside low/high")
        if self.trade_count is not None:
            if isinstance(self.trade_count, bool) or not isinstance(self.trade_count, int) or self.trade_count < 0:
                raise InvalidMarketDataError("trade_count must be a non-negative int")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketBar:
        '''Builds a bar from a plain dict (our canonical keys, not a vendor's).'''
        try:
            timestamp = data["timestamp"]
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            try:
                resolution = TimeResolution(data["resolution"])
            except ValueError:
                raise InvalidMarketDataError(f"unknown resolution {data['resolution']!r}") from None
            return cls(
                symbol=data["symbol"],
                timestamp=timestamp,
                resolution=resolution,
                open=data["open"],
                high=data["high"],
                low=data["low"],
                close=data["close"],
                volume=data["volume"],
                vwap=data.get("vwap"),
                trade_count=data.get("trade_count"),
            )
        except KeyError as e:
            raise InvalidMarketDataError(f"missing field {e}") from None

    def to_dict(self) -> dict[str, Any]:
        '''Inverse of from_dict. Decimals become strings so nothing gets lost.'''
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "resolution": self.resolution.value,
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
            "vwap": None if self.vwap is None else str(self.vwap),
            "trade_count": self.trade_count,
        }
