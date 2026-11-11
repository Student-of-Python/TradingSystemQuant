'''
src/strategy/domain/value.py
'''
from dataclasses import dataclass
from decimal import Decimal

from src.strategy.domain.enums import StrategyAction


@dataclass(frozen=True)
class StrategyOutput:
    symbol: str
    action: StrategyAction
    units: Decimal
    confidence: Decimal
    strategy_name: str
    price: Decimal



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
