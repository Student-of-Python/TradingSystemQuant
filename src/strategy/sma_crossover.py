'''
src/strategy/sma_crossover.py
'''
from decimal import Decimal

from src.strategy.domain.enums import StrategyAction
from src.strategy.domain.value import StrategyOutput


class SmaCrossOverStrategy:
    '''Simple SMA crossover strategy'''

    def __init__(
        self,
        symbol: str,
        short_window: int = 20,
        long_window: int = 50,
        units: Decimal = Decimal("1"),
    ):
        self._symbol = symbol
        self._short = short_window
        self._long = long_window
        self._units = units
        self._closes: list[Decimal] = []
        self._prev_short: Decimal | None = None
        self._prev_long: Decimal | None = None

    @property
    def strategy_id(self) -> str:
        return f"sma_crossover_{self._short}_{self._long}"

    def on_warmup(self, historical_bars) -> None:
        for bar in historical_bars:
            if bar.symbol != self._symbol:
                continue
            self._closes.append(bar.close)
            if len(self._closes) > self._long:
                self._closes.pop(0)
        if len(self._closes) >= self._long:
            self._prev_short = self._avg(self._short)
            self._prev_long = self._avg(self._long)

    def on_bar(self, bar) -> StrategyOutput | None:
        if bar.symbol != self._symbol:
            return None

        self._closes.append(bar.close)
        if len(self._closes) > self._long:
            self._closes.pop(0)
        if len(self._closes) < self._long:
            return None

        short_sma = self._avg(self._short)
        long_sma = self._avg(self._long)

        action = None
        if self._prev_short is not None and self._prev_long is not None:
            if self._prev_short <= self._prev_long and short_sma > long_sma:
                action = StrategyAction.BUY
            elif self._prev_short >= self._prev_long and short_sma < long_sma:
                action = StrategyAction.SELL

        self._prev_short = short_sma
        self._prev_long = long_sma

        if action is None:
            return None

        return StrategyOutput(
            symbol=self._symbol,
            action=action,
            units=self._units,
            confidence=Decimal("1"),
            strategy_name=self.strategy_id,
            price=bar.close,
        )

    def _avg(self, window: int) -> Decimal:
        values = self._closes[-window:]
        return sum(values, Decimal("0")) / Decimal(window)
