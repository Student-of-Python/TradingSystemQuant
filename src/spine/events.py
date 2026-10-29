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
class SignalEvent:
    '''
        #TODO: Complete
    '''
    ...