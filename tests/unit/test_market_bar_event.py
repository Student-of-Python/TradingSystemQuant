'''
tests/unit/test_market_bar_event.py
'''
from datetime import datetime, timezone

from src.core.router import EventRouter
from src.data.domain.enums import TimeResolution
from src.data.domain.events import MarketBarEvent
from src.data.domain.value import MarketBar

BAR = MarketBar(symbol="AAPL", timestamp=datetime(2026, 11, 3, tzinfo=timezone.utc),
                resolution=TimeResolution.DAILY,
                open="100", high="105", low="99", close="104", volume="1000")


def test_event_flows_through_router():
    router = EventRouter()
    seen = []
    router.subscribe(MarketBarEvent, seen.append)
    router.publish(MarketBarEvent(bar=BAR))
    router.dispatch_next()
    assert [e.bar for e in seen] == [BAR]
