'''
data/enums.py
'''
from enum import StrEnum


class TimeResolution(StrEnum):
    '''
    Time frame resolution of the data
    '''
    MINUTE = 'MINUTE'
    HOURLY = 'HOURLY'
    DAILY = 'DAILY'