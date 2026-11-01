'''
src/spine/events.py

This module holds events. An event is an immutable object that represents something that has already occured.
'''
from dataclasses import dataclass
from src.market_data.value_objects import MarketBar


'''
BASE EVENT
'''

@dataclass(frozen=True)
class Event:
    '''Base event'''
    ...


'''
DATA EVENTS
'''

@dataclass(frozen=True)
class MarketBarEvent(Event):
    bar: MarketBar


'''
STRATEGY EVENTS
'''

@dataclass(frozen=True)
class Metric:
    name: str
    value: float


@dataclass(frozen=True)
class SignalEvent(Event):
    symbol: str
    action: str
    units: float
    confidence: float
    strategy_name: str


@dataclass(frozen=True)
class MetricEvent(Event):
    symbol: str
    strategy_name: str
    metrics: list[Metric]
