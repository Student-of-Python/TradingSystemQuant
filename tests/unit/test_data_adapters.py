'''
tests/unit/test_data_adapters.py
'''
import ast
import pathlib
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.data.adapters.alpaca import bar_from_alpaca
from src.data.domain.enums import TimeResolution


def raw_bar(**overrides):
    fields = dict(symbol="AAPL", timestamp=datetime(2026, 11, 3, tzinfo=timezone.utc),
                  open=100.0, high=105.0, low=99.0, close=104.0, volume=1000.0,
                  vwap=102.5, trade_count=37.0)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_alpaca_bar_translates():
    bar = bar_from_alpaca(raw_bar(), TimeResolution.DAILY)
    assert bar.close == Decimal("104.0")
    assert bar.vwap == Decimal("102.5")


def test_alpaca_bar_without_optional_fields():
    raw = raw_bar()
    del raw.vwap, raw.trade_count
    bar = bar_from_alpaca(raw, TimeResolution.MINUTE)
    assert bar.vwap is None and bar.trade_count is None


def test_bad_vendor_data_is_rejected_at_the_boundary():
    with pytest.raises(ValueError):
        bar_from_alpaca(raw_bar(low=200.0), TimeResolution.DAILY)


def test_data_domain_is_pure_stdlib():
    '''Purity Rule from data/design.md: nothing outside stdlib + our own src in the domain'''
    allowed_third_party = set()
    domain = pathlib.Path(__file__).parents[2] / "src" / "data" / "domain"
    for path in domain.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                assert top == "src" or top in __import__("sys").stdlib_module_names or top in allowed_third_party, \
                    f"{path.name} imports {name}"
