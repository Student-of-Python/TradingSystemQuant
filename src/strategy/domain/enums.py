'''
src/strategy/domain/enums.py
'''
from enum import StrEnum

class StrategyAction(StrEnum):
    '''
        Actions a strategy can take
    '''

    BUY = 'BUY'
    SELL = 'SELL'
    HOLD = 'HOLD'
    LIQUIDATE = 'LIQUIDATE'