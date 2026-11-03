'''
src/core/results/enums.py
'''
from enum import StrEnum


class ErrorCode(StrEnum):
    '''
    Potential Errors system may encounter
    '''
    CONNECTION_FAILURE = 'CONNECTION_FAILURE'
    INVALID_DATA = 'INVALID_DATA'
    UNKNOWN_ERROR = 'UNKNOWN_ERROR'
    #TODO: Add more