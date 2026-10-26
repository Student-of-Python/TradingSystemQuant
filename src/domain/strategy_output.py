from dataclasses import dataclass

from src.domain.events import Metric, MetricEvent, SignalEvent


@dataclass(frozen=True)
class StrategyOutput:
    symbol: str
    action: str          # BUY, SELL, or HOLD
    units: float
    confidence: float
    strategy_name: str
    metrics: list[Metric]


def split_output(output: StrategyOutput) -> tuple[SignalEvent, MetricEvent]:
    signal = SignalEvent(
        output.symbol,
        output.action,
        output.units,
        output.confidence,
        output.strategy_name,
    )
    metric = MetricEvent(output.symbol, output.strategy_name, list(output.metrics))
    return signal, metric
