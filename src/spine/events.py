'''


This module holds events. An event is an immutable object that represents something that has already occured.


'''
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
class MarketBarEvent(Event):
    '''
        #TODO: Complete
    '''
    ...


'''
STRATEGY EVENTS
'''

@dataclass(frozen = True)
class SignalEvent(Event):
    '''
        #TODO: Complete
    '''
    ...