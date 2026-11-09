'''
tests/unit/test_market_bar_event.py
'''
from datetime import datetime, timezone

import pytest

from src.core.router import EventRouter
from src.data.domain.enums import TimeResolution
from src.data.domain.errors import InvalidMarketDataError
from src.data.domain.events import MarketBarEvent
from src.data.domain.value import MarketBar

BAR = MarketBar(symbol="AAPL", timestamp=datetime(2026, 11, 3, tzinfo=timezone.utc),
                resolution=TimeResolution.DAILY,
                open="100", high="105", low="99", close="104", volume="1000")


def test_event_wraps_bar():
    event = MarketBarEvent(bar=BAR)
    assert event.bar is BAR
    assert event.symbol == "AAPL"
    assert event.event_tag.startswith("MarketBarEvent_")


def test_event_rejects_non_bar():
    with pytest.raises(InvalidMarketDataError):
        MarketBarEvent(bar={"symbol": "AAPL"})


def test_two_events_same_bar_have_different_ids():
    assert MarketBarEvent(bar=BAR).event_id != MarketBarEvent(bar=BAR).event_id


def test_event_flows_through_router():
    router = EventRouter()
    seen = []
    router.subscribe(MarketBarEvent, seen.append)
    router.publish(MarketBarEvent(bar=BAR))
    router.dispatch_next()
    assert [e.bar for e in seen] == [BAR]
