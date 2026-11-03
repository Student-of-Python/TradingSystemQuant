'''
src/strategy/domain/value.py
'''


from dataclasses import dataclass
from enums import StrategyAction
from decimal import Decimal

@dataclass(frozen=True)
class StrategyOutput:
    symbol: str
    action: StrategyAction # BUY, SELL, or HOLD
    units: Decimal #Decimal
    confidence: Decimal #Also more decimal
    strategy_name: str



'''def split_output(output: StrategyOutput) -> tuple[SignalEvent, MetricEvent]:
    signal = SignalEvent(
        output.symbol,
        output.action,
        output.units,
        output.confidence,
        output.strategy_name,
    )
    metric = MetricEvent(output.symbol, output.strategy_name, list(output.metrics))
    return signal, metric
'''