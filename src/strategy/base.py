'''
src/strategy/base.py
'''
from typing import Protocol, Sequence

from src.data.domain.events import MarketBarEvent
from src.strategy.domain.value import StrategyOutput


class Strategy(Protocol):
    '''
    Protocol for strategies
    '''

    @property
    def strategy_id(self) -> str:
        ...

    def on_warmup(self, historical_bars: Sequence[MarketBarEvent]) -> None:
        # This is a sequence of bars and not a DataFrame because the Protocol must stay library-free accordign to the desgin.md file. 
        # Pandas/numpy can still be used inside a concrete strategy, not in this contract. I think keeping it like this can handle any type of stratergy.
        '''Warms strategy up with historical data'''
        ...


    def on_bar(self, bar: MarketBarEvent) -> StrategyOutput | None:
        '''Strategy output based on a new market bar'''
        ...
