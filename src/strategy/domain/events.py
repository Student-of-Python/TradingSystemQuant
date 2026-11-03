'''
src/strategy/domain/events.py
'''
from src.core import BaseEvent
from dataclasses import dataclass
from decimal import Decimal
from enums import StrategyAction


@dataclass(frozen=True)
class SignalEvent(BaseEvent):
    '''
    SignalEvent occurs when a strategy yields a potential signal to take action in the marketr

    Symbol (str): Ticker
    '''
    symbol: str
    action: StrategyAction
    units: Decimal
    confidence: Decimal
    strategy_name: str



'''
Let's hold off on these for now -- Gleb
@dataclass(frozen=True)
class Metric:
    name: str
    value: float



@dataclass(frozen=True)
class MetricEvent(Event):
    symbol: str
    strategy_name: str
    metrics: list[Metric]

'''