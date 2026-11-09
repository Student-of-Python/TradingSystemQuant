'''
src/data/domain/events.py
'''
from dataclasses import dataclass

from src.core import BaseEvent
from src.data.domain.errors import InvalidMarketDataError
from src.data.domain.value import MarketBar


@dataclass(frozen=True)
class MarketBarEvent(BaseEvent):
    '''
    Published when a new, validated bar has closed.

    bar (MarketBar): The bar. Already validated by MarketBar itself.
    '''
    bar: MarketBar

    def __post_init__(self) -> None:
        if not isinstance(self.bar, MarketBar):
            raise InvalidMarketDataError(f"bar must be a MarketBar, got {type(self.bar).__name__}")

    @property
    def symbol(self) -> str:
        '''Shortcut so subscribers can filter without reaching into .bar'''
        return self.bar.symbol
