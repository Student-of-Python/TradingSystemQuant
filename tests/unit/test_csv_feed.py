'''
tests/unit/test_csv_feed.py
'''
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.data.adapters.csv_feed import CsvDataFeed
from src.data.domain.enums import TimeResolution

HEADER = "symbol,timestamp,resolution,open,high,low,close,volume,vwap,trade_count\n"
START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 30, tzinfo=timezone.utc)


def write(tmp_path, body):
    p = tmp_path / "bars.csv"
    p.write_text(HEADER + body)
    return CsvDataFeed(p)


def test_reads_bars_oldest_first(tmp_path):
    feed = write(tmp_path,
                 "AAPL,2026-11-04T00:00:00+00:00,DAILY,101,106,100,105,1200,,\n"
                 "AAPL,2026-11-03T00:00:00+00:00,DAILY,100,105,99,104,1000,102.5,37\n")
    bars = feed.get_historical_bars("AAPL", START, END)
    assert [b.close for b in bars] == [Decimal("104"), Decimal("105")]
    assert bars[0].vwap == Decimal("102.5") and bars[0].trade_count == 37
    assert bars[1].vwap is None and bars[1].trade_count is None


def test_filters_symbol_timeframe_and_range(tmp_path):
    feed = write(tmp_path,
                 "AAPL,2026-11-03T00:00:00+00:00,DAILY,100,105,99,104,1000,,\n"
                 "MSFT,2026-11-03T00:00:00+00:00,DAILY,100,105,99,104,1000,,\n"
                 "AAPL,2026-11-03T14:30:00+00:00,MINUTE,100,105,99,104,10,,\n"
                 "AAPL,2026-10-01T00:00:00+00:00,DAILY,100,105,99,104,1000,,\n")
    bars = feed.get_historical_bars("AAPL", START, END, TimeResolution.DAILY)
    assert len(bars) == 1
    assert bars[0].timestamp == datetime(2026, 11, 3, tzinfo=timezone.utc)


def test_bad_row_fails_with_line_number(tmp_path):
    feed = write(tmp_path,
                 "AAPL,2026-11-03T00:00:00+00:00,DAILY,100,105,99,104,1000,,\n"
                 "AAPL,2026-11-04T00:00:00+00:00,DAILY,100,90,99,104,1000,,\n")
    with pytest.raises(ValueError, match="line 3"):
        feed.get_historical_bars("AAPL", START, END)


def test_no_streaming(tmp_path):
    with pytest.raises(NotImplementedError):
        write(tmp_path, "").start_stream(["AAPL"])
