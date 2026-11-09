'''
src/data/adapters/csv_feed.py

Reads bars from a CSV file. For backtests and tests -- no network, no API keys.

Expected header (vwap / trade_count optional, may be blank):
symbol,timestamp,resolution,open,high,low,close,volume,vwap,trade_count
AAPL,2026-11-03T14:30:00+00:00,DAILY,100,105,99,104,1000,,
'''
import csv
from datetime import datetime
from pathlib import Path
from typing import Sequence

from src.data.domain.enums import TimeResolution
from src.data.domain.value import MarketBar


class CsvDataFeed:
    '''
    CSV market feed. A bad row fails the whole load (with the line number) instead of being skipped,
    so a backtest never silently runs on data with holes in it.
    '''

    def __init__(self, path: str | Path):
        self._path = Path(path)

    def _load(self) -> list[MarketBar]:
        bars = []
        with self._path.open(newline="") as f:
            # line 1 is the header, so data starts at line 2
            for line_no, row in enumerate(csv.DictReader(f), start=2):
                row = {k: (v if v != "" else None) for k, v in row.items()}
                if row.get("trade_count") is not None:
                    row["trade_count"] = int(row["trade_count"])
                try:
                    bars.append(MarketBar.from_dict(row))
                except ValueError as e:
                    raise ValueError(f"{self._path.name} line {line_no}: {e}") from None
        return bars

    def get_historical_bars(self,
                            symbol: str,
                            start: datetime,
                            end: datetime,
                            timeframe: TimeResolution = TimeResolution.DAILY) -> Sequence[MarketBar]:
        '''Bars for symbol/timeframe with start <= timestamp <= end, oldest first'''
        bars = [
            b for b in self._load()
            if b.symbol == symbol and b.resolution == timeframe and start <= b.timestamp <= end
        ]
        return sorted(bars, key=lambda b: b.timestamp)

    def start_stream(self, symbols: Sequence[str]) -> None:
        raise NotImplementedError("CSV feed is historical only")

    def stop_stream(self) -> None:
        raise NotImplementedError("CSV feed is historical only")
