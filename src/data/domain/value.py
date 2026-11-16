'''
src/data/domain/value.py
'''
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from src.data.domain.enums import TimeResolution


def _to_decimal(value, name: str) -> Decimal:
    '''Converts through str so floats don't bring binary noise (0.1 stays 0.1)'''
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} is not a number: {value!r}") from None
    if not d.is_finite():
        raise ValueError(f"{name} must be finite")
    return d


@dataclass(frozen = True)
class MarketBar:
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

    def __post_init__(self):
        if not self.symbol:
            raise ValueError("symbol is missing")
        if not isinstance(self.timestamp, datetime):
            raise TypeError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.timestamp.utcoffset() != timezone.utc.utcoffset(self.timestamp):
            raise ValueError("timestamp must be UTC")
        if not isinstance(self.resolution, TimeResolution):
            raise TypeError("resolution must be a TimeResolution")
        for name in ("open", "high", "low", "close", "volume"):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
        if self.vwap is not None:
            if not isinstance(self.vwap, Decimal):
                raise TypeError("vwap must be a Decimal")
            if not self.vwap.is_finite():
                raise ValueError("vwap must be finite")
        if self.trade_count is not None and not isinstance(self.trade_count, int):
            raise TypeError("trade_count must be an int")

        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("prices must be positive")
        if self.volume < 0:
            raise ValueError("volume can't be negative")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is below open/close/low")
        if self.low > min(self.open, self.close):
            raise ValueError("low is above open/close")

    @classmethod
    def from_dict(cls, data: dict[str, float | int | str]) -> MarketBar:
        '''Conversion from dictionary'''
        try:
            timestamp = data["timestamp"]
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            if not isinstance(timestamp, datetime):
                raise ValueError("timestamp must be a datetime")
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone(timezone.utc)
            trade_count = data.get("trade_count")
            return cls(
                symbol=str(data["symbol"]),
                timestamp=timestamp,
                resolution=TimeResolution(data["resolution"]),
                open=_to_decimal(data["open"], "open"),
                high=_to_decimal(data["high"], "high"),
                low=_to_decimal(data["low"], "low"),
                close=_to_decimal(data["close"], "close"),
                volume=_to_decimal(data["volume"], "volume"),
                vwap=_to_decimal(data["vwap"], "vwap") if data.get("vwap") is not None else None,
                trade_count=int(trade_count) if trade_count is not None else None,
            )
        except KeyError as e:
            raise ValueError(f"missing field {e}") from None
