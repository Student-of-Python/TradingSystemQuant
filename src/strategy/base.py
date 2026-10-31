'''
src/strategy/base.py
'''
from typing import Protocol, Sequence
from pandas import DataFrame
from src.spine.events import MarketBarEvent
from strategy_output import StrategyOutput
from src.market_data.value_objects import MarketBar

HistoricalData: TypeAlias = pd.DataFrame | Sequence[MarketBar] #Will most likely have to stick with Dataframe because conversion cost between MarketBar and Dataframe is too expensive?


class Strategy(Protocol): #We make this parent class instead?
    '''
    Protocol for strategies
    '''

    @property
    def strategy_id(self) -> str:
        ...

    def on_warmup(self, historical_bars: HistoricalData) -> None:
        '''Warms strategy up with historical data'''
        ...

    def on_bar(self, bar: MarketBarEvent) -> StrategyOutput | None:
        '''Strategy output based on a new market bar'''
        ...

    #TODO: Do we need any other interface methods for Strategy?


