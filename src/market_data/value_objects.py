'''
market_data/value_objects.py
'''
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from src.market_data.enums import TimeResolution

@dataclass(frozen = True)
class MarketBar:
    symbol: str
    timestamp: datetime
    resolution: TimeResolution
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trade_count: int | None = None

    def __post_init__(self):
        if not self.symbol:
            raise ValueError("symbol is missing")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
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
                open=float(data["open"]),
                high=float(data["high"]),
                low=float(data["low"]),
                close=float(data["close"]),
                volume=float(data["volume"]),
                vwap=data.get("vwap"),
                trade_count=data.get("trade_count"),
            )
        except KeyError as e:
            raise ValueError(f"missing field {e}") from None
