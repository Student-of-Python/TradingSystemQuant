'''
src/execution/domain/enums.py
'''

from enum import StrEnum


class OrderStatus(StrEnum):
    '''
    Where an order is in its lifecycle. Allowed moves live in order.ALLOWED_TRANSITIONS.
    '''
    PENDING_SUBMIT = 'PENDING_SUBMIT'      # Created, not yet acknowledged by the broker
    SUBMITTED = 'SUBMITTED'                # Broker accepted it, nothing filled yet
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'  # Some units filled, some remaining
    FILLED = 'FILLED'                      # Terminal: every unit filled
    CANCELED = 'CANCELED'                  # Terminal: canceled (may keep earlier partial fills)
    REJECTED = 'REJECTED'                  # Terminal: refused by the broker or by execution


class OrderSide(StrEnum):
    '''Direction of the order.'''
    BUY = 'BUY'
    SELL = 'SELL'


class OrderType(StrEnum):
    '''How the order is priced. MVP supports market orders only.'''
    MARKET = 'MARKET'
