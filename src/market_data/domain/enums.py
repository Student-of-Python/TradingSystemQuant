'''
market_data/enums.py
'''
from enum import StrEnum


class TimeResolution(StrEnum):
    MINUTE = 'MINUTE'
    HOURLY = 'HOURLY'
    DAILY = 'DAILY'