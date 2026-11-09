'''
tests/unit/test_data_manager.py
'''
from datetime import datetime, timezone

from src.core.router import EventRouter
from src.data.domain.enums import TimeResolution
from src.data.domain.events import MarketBarEvent
from src.data.domain.value import MarketBar
from src.data.manager import DataManager


def bar(symbol, day):
    return MarketBar(symbol=symbol, timestamp=datetime(2026, 11, day, tzinfo=timezone.utc),
                     resolution=TimeResolution.DAILY,
                     open="100", high="105", low="99", close="104", volume="1000")


class FakeProvider:
    '''Stands in for any adapter -- the manager only knows the MarketDataProvider protocol'''
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def get_historical_bars(self, symbol, start, end, timeframe=TimeResolution.DAILY):
        self.calls.append((symbol, timeframe))
        return [b for b in self.bars if b.symbol == symbol]


def drain(router):
    seen = []
    router.subscribe(MarketBarEvent, seen.append)
    while router._queue:
        router.dispatch_next()
    return seen


START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 30, tzinfo=timezone.utc)


def test_warmup_publishes_one_event_per_bar():
    router = EventRouter()
    provider = FakeProvider([bar("AAPL", 3), bar("AAPL", 4)])
    count = DataManager(provider, router).warmup(["AAPL"], START, END)
    assert count == 2
    assert [e.bar for e in drain(router)] == [bar("AAPL", 3), bar("AAPL", 4)]


def test_warmup_interleaves_symbols_by_time():
    router = EventRouter()
    provider = FakeProvider([bar("AAPL", 3), bar("AAPL", 4), bar("MSFT", 3), bar("MSFT", 4)])
    DataManager(provider, router).warmup(["MSFT", "AAPL"], START, END)
    order = [(e.bar.symbol, e.bar.timestamp.day) for e in drain(router)]
    assert order == [("AAPL", 3), ("MSFT", 3), ("AAPL", 4), ("MSFT", 4)]


def test_warmup_passes_timeframe_through():
    provider = FakeProvider([])
    DataManager(provider, EventRouter()).warmup(["AAPL"], START, END, TimeResolution.MINUTE)
    assert provider.calls == [("AAPL", TimeResolution.MINUTE)]


def test_warmup_with_no_data_publishes_nothing():
    router = EventRouter()
    assert DataManager(FakeProvider([]), router).warmup(["AAPL"], START, END) == 0
    assert drain(router) == []
