"""Native factor binding, multi-feed clock, and gap-recovery contracts.

The expected spread values below are computed directly from the small input
tables.  The formula does not use the production operator nodes, and the
benchmark is deliberately absent from the research target universe.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Tuple

import pandas as pd
import pytest

import backtrader as bt
from backtrader.errors import ResearchConfigError as ConfigError, DatasetError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research import align_to_grid
from backtrader.research.specs import FactorSpec, ResearchSpec


_TARGETS = ("AAA", "BBB")
_BENCHMARK = "BENCH"
_FEED_MARKER = "_factor_research_alignment_v1"


class _TargetMinusBenchmark(FactorIndicator):
    """One scalar spread per target, reading the shared named benchmark."""

    lines = ("factor",)
    formula_fields = ("target_close", "benchmark_close")
    required_fields = formula_fields
    lookback_h = 0

    def next(self) -> None:
        target_lines = self.field_lines("target_close")
        benchmark_lines = self.field_lines("benchmark_close")
        for data, target_line, benchmark_line in zip(
            self.target_datas, target_lines, benchmark_lines
        ):
            target = float(target_line[0])
            benchmark = float(benchmark_line[0])
            if math.isfinite(target) and math.isfinite(benchmark):
                self.outputs[data].factor[0] = target - benchmark
                self.record_availability(data, ready=True, valid=True, reason="READY")
            else:
                self.outputs[data].factor[0] = float("nan")
                self.record_availability(data, ready=True, valid=False, reason="NONFINITE_INPUT")


class _LivePandasData(bt.feeds.PandasData):
    """Finite test feed that declares the unsupported live clock contract."""

    def islive(self) -> bool:
        return True


def _fixture() -> Tuple[ResearchSpec, Dict[str, pd.DataFrame], pd.DatetimeIndex]:
    grid_index = pd.date_range("2026-01-05", periods=8, freq="D", tz="UTC", name="close_time")
    grid = pd.DataFrame({"open_time": grid_index - pd.Timedelta(hours=6)}, index=grid_index)
    research = ResearchSpec(
        grid=grid,
        start=grid_index[2],
        end=grid_index[-1],
        targets=_TARGETS,
        source_timezone="UTC",
        snapshot_id="factor-binding-clock-known-answer-v1",
        price_basis="synthetic unadjusted USD close values",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"AAA": "equities", "BBB": "equities"},
    )

    def bars(indices: Tuple[int, ...], values: Tuple[float, ...]) -> pd.DataFrame:
        index = grid_index[list(indices)]
        close = list(values)
        return pd.DataFrame(
            {
                "open": [value - 0.5 for value in close],
                "high": [value + 1.0 for value in close],
                "low": [value - 1.0 for value in close],
                "close": close,
                "volume": [1000.0 + value for value in close],
                "openinterest": [0.0] * len(close),
            },
            index=index,
        )

    frames = {
        # Both target rows contain full OHLCV values except that BBB starts
        # late and ends early.  Its missing slots are created by prealignment.
        "AAA": bars(tuple(range(8)), tuple(100.0 + i for i in range(8))),
        "BBB": bars((2, 4, 5, 6), (202.0, 204.0, 205.0, 206.0)),
        # The benchmark starts late, misses grid 4, recovers at grid 5, and
        # ends before grid 7.  It must remain input-only throughout.
        _BENCHMARK: bars((2, 3, 5, 6), (14.0, 16.0, 20.0, 22.0)),
    }
    return research, frames, grid_index


def _factor_spec(bindings: Optional[Mapping[str, Any]] = None) -> FactorSpec:
    return FactorSpec(
        name="spread",
        indicator=_TargetMinusBenchmark,
        panel_line="factor",
        field_bindings=(
            {
                "target_close": "feed:target:close",
                "benchmark_close": "feed:BENCH:close",
            }
            if bindings is None
            else bindings
        ),
    )


def _aligned_feed(
    frame: pd.DataFrame,
    research: ResearchSpec,
    name: str,
    *,
    feed_class: Optional[type] = None,
    timeframe: Optional[int] = None,
    compression: int = 1,
) -> bt.feeds.PandasData:
    aligned = align_to_grid(frame, research, name)
    if feed_class is None and timeframe is None:
        return aligned.feed
    cls = feed_class or bt.feeds.PandasData
    params: Dict[str, Any] = {"dataname": aligned.frame}
    if timeframe is not None:
        params.update(timeframe=timeframe, compression=compression)
    feed = cls(**params)
    setattr(feed, _FEED_MARKER, getattr(aligned.feed, _FEED_MARKER))
    return feed


def _stop_before_clock_iteration(cerebro: bt.Cerebro, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make unsupported-clock cases test strategy preflight without looping."""

    def unexpected_loop(*args: Any, **kwargs: Any) -> None:
        pytest.fail("FactorStrategy entered a Cerebro clock loop before rejecting the clock")

    for name in ("_runonce", "_runnext", "_runonce_old", "_runnext_old"):
        monkeypatch.setattr(cerebro, name, unexpected_loop)


def _add_strategy(
    cerebro: bt.Cerebro,
    research: ResearchSpec,
    *,
    factor_spec: Optional[FactorSpec] = None,
) -> None:
    cerebro.addstrategy(
        FactorStrategy,
        research=research,
        factors={"spread": _factor_spec() if factor_spec is None else factor_spec},
    )


def _count_broker_writes(cerebro: bt.Cerebro, monkeypatch: pytest.MonkeyPatch) -> Dict[str, int]:
    counts = {"submit": 0, "cancel": 0}
    for method_name in counts:
        original = getattr(cerebro.broker, method_name)

        def counted(
            *args: Any,
            _name: str = method_name,
            _original: Any = original,
            **kwargs: Any,
        ) -> Any:
            counts[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(cerebro.broker, method_name, counted)
    return counts






