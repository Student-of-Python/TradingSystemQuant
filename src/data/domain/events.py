'''
src/data/domain/events.py
'''
from dataclasses import dataclass
from src.core import BaseEvent
from src.data.domain.value import MarketBar

@dataclass(frozen=True)
class MarketBarEvent(BaseEvent):
    bar: MarketBar
