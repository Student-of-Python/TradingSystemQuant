'''
tests/unit/test_market_bar.py
'''
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.data.domain.enums import TimeResolution
from src.data.domain.value import MarketBar

TS = datetime(2026, 11, 3, 14, 30, tzinfo=timezone.utc)


def make(**overrides):
    fields = dict(
        symbol="AAPL", timestamp=TS, resolution=TimeResolution.DAILY,
        open="100", high="105", low="99", close="104", volume="1000",
    )
    fields.update(overrides)
    return MarketBar(**fields)


def test_valid_bar_builds():
    assert make().close == Decimal("104")


def test_prices_are_exact_decimals():
    bar = make(open=0.1, low=0.1, high=0.3, close=0.2)
    assert bar.open == Decimal("0.1")


def test_timestamp_converted_to_utc():
    est = timezone(timedelta(hours=-5))
    bar = make(timestamp=datetime(2026, 11, 3, 9, 30, tzinfo=est))
    assert bar.timestamp == TS
    assert bar.timestamp.tzinfo == timezone.utc


def test_bar_is_frozen():
    with pytest.raises(FrozenInstanceError):
        make().close = Decimal("1")


def test_missing_symbol():
    with pytest.raises(ValueError):
        make(symbol="")


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        make(timestamp=datetime(2026, 11, 3, 14, 30))


@pytest.mark.parametrize("overrides", [
    {"open": "0", "low": "0"},
    {"close": "-1", "low": "-1"},
])
def test_non_positive_prices(overrides):
    with pytest.raises(ValueError):
        make(**overrides)


def test_negative_volume():
    with pytest.raises(ValueError):
        make(volume="-1")


@pytest.mark.parametrize("bad", ["nan", "inf", "abc"])
def test_non_numeric_or_non_finite(bad):
    with pytest.raises(ValueError):
        make(close=bad)


def test_high_below_close():
    with pytest.raises(ValueError):
        make(high="103")


def test_low_above_open():
    with pytest.raises(ValueError):
        make(low="101")


def test_from_dict_parses_iso_string():
    bar = MarketBar.from_dict({
        "symbol": "MSFT", "timestamp": "2026-11-03T14:30:00+00:00", "resolution": "DAILY",
        "open": "100", "high": "105", "low": "99", "close": "104", "volume": "1000",
    })
    assert bar.timestamp == TS


def test_from_dict_missing_field():
    with pytest.raises(ValueError, match="close"):
        MarketBar.from_dict({"symbol": "AAPL", "timestamp": TS, "resolution": "DAILY",
                             "open": 1, "high": 1, "low": 1, "volume": 1})
