'''


This module holds events. An event is an immutable object that represents something that has already occured.


'''
from __future__ import annotations
from dataclasses import dataclass

'''
Base Event
'''

@dataclass(frozen = True)
class Event:
    '''Base event'''
    ...


'''
DATA EVENTS
'''

@dataclass(frozen = True)
class MarketBarEvent:
    '''
        #TODO: Complete
    '''
    ...

    def __post_init__(self):
        ... #Simple Data Validation.

    @classmethod
    def from_dict(cls, data: dict[str, float | int | str]) -> MarketBarEvent:
        '''Conversion from dictionary'''
        ...


'''
STRATEGY EVENTS
'''

@dataclass(frozen = True)
class SignalEvent:
    '''
        #TODO: Complete
    '''
    ...