'''
tests/unit/test_market_bar.py
'''
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.data.domain.enums import TimeResolution
from src.data.domain.errors import InvalidMarketDataError
from src.data.domain.value import MarketBar

TS = datetime(2026, 11, 3, 14, 30, tzinfo=timezone.utc)


def make(**overrides):
    fields = dict(
        symbol="AAPL", timestamp=TS, resolution=TimeResolution.DAILY,
        open="100", high="105", low="99", close="104", volume="1000",
    )
    fields.update(overrides)
    return MarketBar(**fields)


# ---- happy path / normalization ----

def test_valid_bar_builds():
    bar = make()
    assert bar.close == Decimal("104")
    assert bar.resolution is TimeResolution.DAILY


def test_prices_become_decimal_without_float_noise():
    bar = make(open=0.1, low=0.1, high=0.3, close=0.2)
    assert bar.open == Decimal("0.1")
    assert all(isinstance(getattr(bar, f), Decimal) for f in ("open", "high", "low", "close", "volume"))


def test_symbol_is_stripped_and_uppercased():
    assert make(symbol="  aapl ").symbol == "AAPL"


def test_timestamp_converted_to_utc():
    est = timezone(timedelta(hours=-5))
    bar = make(timestamp=datetime(2026, 11, 3, 9, 30, tzinfo=est))
    assert bar.timestamp == TS
    assert bar.timestamp.tzinfo == timezone.utc


def test_bar_is_frozen():
    with pytest.raises(FrozenInstanceError):
        make().close = Decimal("1")


def test_equal_bars_are_equal_and_hashable():
    assert make() == make()
    assert len({make(), make()}) == 1


def test_flat_bar_allowed():
    make(open="5", high="5", low="5", close="5", volume="0")


# ---- invariants ----

@pytest.mark.parametrize("symbol", ["", "   ", None])
def test_missing_symbol(symbol):
    with pytest.raises(InvalidMarketDataError):
        make(symbol=symbol)


def test_naive_timestamp_rejected():
    with pytest.raises(InvalidMarketDataError):
        make(timestamp=datetime(2026, 11, 3, 14, 30))


def test_resolution_must_be_enum():
    with pytest.raises(InvalidMarketDataError):
        make(resolution="DAILY")


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
@pytest.mark.parametrize("bad", ["0", "-1"])
def test_non_positive_prices(field, bad):
    with pytest.raises(InvalidMarketDataError):
        make(**{field: bad, "low": bad} if field != "high" else {field: bad})


def test_negative_volume():
    with pytest.raises(InvalidMarketDataError):
        make(volume="-1")


@pytest.mark.parametrize("bad", ["nan", "inf", "abc", True, None])
def test_non_numeric_or_non_finite(bad):
    with pytest.raises(InvalidMarketDataError):
        make(close=bad)


def test_high_below_close():
    with pytest.raises(InvalidMarketDataError):
        make(high="103")


def test_high_below_low():
    with pytest.raises(InvalidMarketDataError):
        make(open="100", close="100", high="100", low="101")


def test_low_above_open():
    with pytest.raises(InvalidMarketDataError):
        make(low="101")


def test_vwap_must_be_inside_range():
    assert make(vwap="102").vwap == Decimal("102")
    with pytest.raises(InvalidMarketDataError):
        make(vwap="110")


@pytest.mark.parametrize("bad", [-1, 1.5, True])
def test_bad_trade_count(bad):
    with pytest.raises(InvalidMarketDataError):
        make(trade_count=bad)


def test_error_is_a_value_error():
    '''callers that just catch ValueError still work'''
    with pytest.raises(ValueError):
        make(volume="-1")


# ---- from_dict / to_dict ----

def test_from_dict_parses_iso_string():
    bar = MarketBar.from_dict({
        "symbol": "msft", "timestamp": "2026-11-03T14:30:00+00:00", "resolution": "DAILY",
        "open": "100", "high": "105", "low": "99", "close": "104", "volume": "1000",
    })
    assert bar.symbol == "MSFT"
    assert bar.timestamp == TS


def test_from_dict_missing_field():
    with pytest.raises(InvalidMarketDataError, match="close"):
        MarketBar.from_dict({"symbol": "AAPL", "timestamp": TS, "resolution": "DAILY",
                             "open": 1, "high": 1, "low": 1, "volume": 1})


def test_from_dict_bad_resolution():
    with pytest.raises(InvalidMarketDataError, match="resolution"):
        MarketBar.from_dict({**make().to_dict(), "resolution": "WEEKLY"})


def test_to_dict_round_trip():
    bar = make(vwap="101.25", trade_count=42)
    assert MarketBar.from_dict(bar.to_dict()) == bar
