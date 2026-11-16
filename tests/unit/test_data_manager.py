'''
tests/unit/test_data_manager.py
'''
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.core.router import EventRouter
from src.data.domain.enums import TimeResolution
from src.data.domain.events import HistoricalBarsEvent
from src.data.domain.value import MarketBar
from src.data.manager import DataManager


def bar(symbol, day):
    return MarketBar(symbol=symbol, timestamp=datetime(2026, 11, day, tzinfo=timezone.utc),
                     resolution=TimeResolution.DAILY,
                     open=Decimal("100"), high=Decimal("105"), low=Decimal("99"),
                     close=Decimal("104"), volume=Decimal("1000"))


class FakeProvider:
    '''Stands in for any adapter -- the manager only knows the MarketDataProvider protocol'''
    def __init__(self, bars):
        self.bars = bars
        self.calls = []
        self.streamed_symbols = None
        self.stopped = False

    def get_historical_bars(self, symbol, start, end, timeframe=TimeResolution.DAILY):
        self.calls.append((symbol, timeframe))
        return [b for b in self.bars if b.symbol == symbol]

    def start_stream(self, symbols):
        self.streamed_symbols = tuple(symbols)

    def stop_stream(self):
        self.stopped = True


def drain(router):
    seen = []
    router.subscribe(HistoricalBarsEvent, seen.append)
    while router._queue:
        router.dispatch_next()
    return seen


START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 30, tzinfo=timezone.utc)


def test_warmup_publishes_one_history_event():
    router = EventRouter()
    provider = FakeProvider([bar("AAPL", 3), bar("AAPL", 4)])
    count = DataManager(provider, router).warmup(["AAPL"], START, END)
    assert count == 2
    events = drain(router)
    assert len(events) == 1
    assert events[0].bars == (bar("AAPL", 3), bar("AAPL", 4))


def test_warmup_interleaves_symbols_by_time():
    router = EventRouter()
    provider = FakeProvider([bar("AAPL", 3), bar("AAPL", 4), bar("MSFT", 3), bar("MSFT", 4)])
    DataManager(provider, router).warmup(["MSFT", "AAPL"], START, END)
    [event] = drain(router)
    order = [(b.symbol, b.timestamp.day) for b in event.bars]
    assert order == [("AAPL", 3), ("MSFT", 3), ("AAPL", 4), ("MSFT", 4)]


def test_warmup_passes_timeframe_through():
    provider = FakeProvider([])
    DataManager(provider, EventRouter()).warmup(["AAPL"], START, END, TimeResolution.MINUTE)
    assert provider.calls == [("AAPL", TimeResolution.MINUTE)]


def test_warmup_with_no_data_publishes_nothing():
    router = EventRouter()
    assert DataManager(FakeProvider([]), router).warmup(["AAPL"], START, END) == 0
    assert drain(router) == []


def test_start_uses_configured_stream_symbols():
    provider = FakeProvider([])
    DataManager(provider, EventRouter(), stream_symbols=["AAPL"]).start()
    assert provider.streamed_symbols == ("AAPL",)


def test_start_requires_symbols():
    with pytest.raises(ValueError, match="stream_symbols"):
        DataManager(FakeProvider([]), EventRouter()).start()
