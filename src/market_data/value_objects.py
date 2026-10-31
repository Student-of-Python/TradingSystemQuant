'''
market_data/value_objects.py
'''
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen = True)
class MarketBar:
    '''#TODO: Complete '''
    ...

    def __post_init__(self):
        ... #Simple Data Validation.

    @classmethod
    def from_dict(cls, data: dict[str, float | int | str]) -> MarketBar:
        '''Conversion from dictionary'''
        ...
