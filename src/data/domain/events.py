'''
src/data/domain/base_event.py
'''
from dataclasses import dataclass
from src.core import BaseEvent

@dataclass(frozen=True)
class MarketBarEvent(BaseEvent):
    '''
        #TODO: Complete
    '''
    ...
