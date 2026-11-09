'''
src/data/domain/errors.py
'''


class InvalidMarketDataError(ValueError):
    '''Raised when incoming market data breaks a domain invariant.'''
    pass
