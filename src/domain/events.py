'''
src/domain/events.py

This module holds events. An event is an immutable object that represents something that has already occured.


'''
from dataclasses import dataclass

@dataclass(frozen = True)
class MarketBarEvent:
    '''
        #TODO: Complete
    '''
    ...


@dataclass(frozen = True)
class Metric:
    name: str
    value: float


@dataclass(frozen = True)
class SignalEvent:
    symbol: str
    action: str
    units: float
    confidence: float
    strategy_name: str


@dataclass(frozen = True)
class MetricEvent:
    symbol: str
    strategy_name: str
    metrics: list[Metric]