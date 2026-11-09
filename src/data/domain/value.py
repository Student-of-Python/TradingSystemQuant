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
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        # frozen, so normalize with object.__setattr__
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(timezone.utc))
        for name in ("open", "high", "low", "close", "volume"):
            object.__setattr__(self, name, _to_decimal(getattr(self, name), name))
        if self.vwap is not None:
            object.__setattr__(self, "vwap", _to_decimal(self.vwap, "vwap"))

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
            return cls(
                symbol=str(data["symbol"]),
                timestamp=timestamp,
                resolution=TimeResolution(data["resolution"]),
                open=data["open"],
                high=data["high"],
                low=data["low"],
                close=data["close"],
                volume=data["volume"],
                vwap=data.get("vwap"),
                trade_count=data.get("trade_count"),
            )
        except KeyError as e:
            raise ValueError(f"missing field {e}") from None
