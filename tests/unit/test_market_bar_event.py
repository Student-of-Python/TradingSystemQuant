'''
tests/unit/test_market_bar_event.py
'''
from datetime import datetime, timezone
from decimal import Decimal

from src.core.router import EventRouter
from src.data.domain.enums import TimeResolution
from src.data.domain.events import MarketBarEvent
from src.data.domain.value import MarketBar

BAR = MarketBar(symbol="AAPL", timestamp=datetime(2026, 11, 3, tzinfo=timezone.utc),
                resolution=TimeResolution.DAILY,
                open=Decimal("100"), high=Decimal("105"), low=Decimal("99"),
                close=Decimal("104"), volume=Decimal("1000"))


def test_event_flows_through_router():
    router = EventRouter()
    seen = []
    router.subscribe(MarketBarEvent, seen.append)
    router.publish(MarketBarEvent(bar=BAR))
    router.dispatch_next()
    assert [e.bar for e in seen] == [BAR]
