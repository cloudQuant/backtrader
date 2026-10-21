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
from backtrader.research.errors import ConfigError, DatasetError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.inputs import prealign_bars
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
    aligned = prealign_bars(frame, research, name)
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


@pytest.mark.parametrize("runonce", (False, True))
def test_named_benchmark_binding_preserves_targets_gaps_recovery_and_feed_order(
    runonce: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    research, frames, grid_index = _fixture()
    expected_by_asset = {
        "AAA": (88.0, 87.0, float("nan"), 85.0, 84.0, float("nan")),
        "BBB": (188.0, float("nan"), float("nan"), 185.0, 184.0, float("nan")),
    }
    feed_orders = (
        (_BENCHMARK, "BBB", "AAA"),
        ("AAA", _BENCHMARK, "BBB"),
    )
    observed_by_order = []

    for feed_order in feed_orders:
        cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
        for name in feed_order:
            cerebro.adddata(_aligned_feed(frames[name], research, name), name=name)
        _add_strategy(cerebro, research)
        writes = _count_broker_writes(cerebro, monkeypatch)
        strategy = cerebro.run(runonce=runonce, preload=True)[0]
        assert writes == {"submit": 0, "cancel": 0}

        factor = strategy.factor_instances["spread"]
        assert isinstance(factor, FactorIndicator)
        assert tuple(data._name for data in factor.datas) == _TARGETS
        assert tuple(data._name for data in factor.available_datas) == feed_order
        assert tuple(data._name for data in factor.target_datas) == _TARGETS
        assert tuple(data._name for data in factor.outputs) == _TARGETS
        assert _BENCHMARK not in {data._name for data in factor.outputs}

        targets = tuple(strategy._target_datas)
        benchmark = next(data for data in strategy.datas if data._name == _BENCHMARK)
        target_bindings = factor.field_lines("target_close")
        benchmark_bindings = factor.field_lines("benchmark_close")
        assert len(target_bindings) == len(_TARGETS)
        assert all(line is data.close for line, data in zip(target_bindings, targets))
        assert len(benchmark_bindings) == len(_TARGETS)
        assert all(line is benchmark_bindings[0] for line in benchmark_bindings)
        for got, wanted in zip(benchmark_bindings[0].array, benchmark.close.array):
            if math.isnan(float(wanted)):
                assert math.isnan(float(got))
            else:
                assert float(got) == pytest.approx(float(wanted))

        full_values = {}
        for asset, data in zip(_TARGETS, targets):
            actual = tuple(
                float(value)
                for value in factor.output_for(data, "factor").get(size=len(grid_index))
            )
            expected = (float("nan"), float("nan")) + expected_by_asset[asset]
            assert len(actual) == len(expected)
            for got, wanted in zip(actual, expected):
                if math.isnan(wanted):
                    assert math.isnan(got)
                else:
                    assert got == pytest.approx(wanted)
            full_values[asset] = actual

        diagnostics = factor.lifecycle_diagnostics
        assert diagnostics["call_count"] == len(grid_index)
        assert diagnostics["grid_count"] == len(grid_index)
        assert diagnostics["grid_matches"]

        dataset = strategy.get_dataset()
        panel = dataset.raw_factors
        expected_index = pd.MultiIndex.from_product(
            [grid_index[2:], _TARGETS], names=("time", "asset")
        )
        assert panel.index.equals(expected_index)
        assert tuple(panel.columns) == ("spread",)
        assert set(panel.index.get_level_values("asset")) == set(_TARGETS)
        assert _BENCHMARK not in set(panel.index.get_level_values("asset"))
        for asset, values in expected_by_asset.items():
            actual = tuple(panel.loc[(time, asset), "spread"] for time in grid_index[2:])
            for got, wanted in zip(actual, values):
                if math.isnan(wanted):
                    assert math.isnan(float(got))
                else:
                    assert float(got) == pytest.approx(wanted)

        availability = dataset.availability
        assert availability.at[(grid_index[4], "AAA", "spread"), "reason"] == "NO_CURRENT_BAR"
        assert availability.at[(grid_index[5], "AAA", "spread"), "reason"] == "READY"
        assert availability.at[(grid_index[7], "AAA", "spread"), "reason"] == "NO_CURRENT_BAR"
        assert availability.at[(grid_index[3], "BBB", "spread"), "reason"] == "NO_CURRENT_BAR"
        assert availability.at[(grid_index[4], "BBB", "spread"), "reason"] == "NO_CURRENT_BAR"
        assert availability.at[(grid_index[7], "BBB", "spread"), "reason"] == "NO_CURRENT_BAR"
        observed_by_order.append(full_values)

    for asset in _TARGETS:
        for first, second in zip(observed_by_order[0][asset], observed_by_order[1][asset]):
            assert math.isnan(first) == math.isnan(second)
            if math.isfinite(first):
                assert first == pytest.approx(second)


@pytest.mark.parametrize("unsupported_clock", ("live", "replay", "mixed_timeframe"))
def test_unsupported_feed_clocks_fail_before_engine_iteration(
    unsupported_clock: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    research, frames, _ = _fixture()
    cerebro = bt.Cerebro(stdstats=False)
    for name in (_BENCHMARK, "BBB", "AAA"):
        feed_class = None
        timeframe = None
        if unsupported_clock == "live" and name == "AAA":
            feed_class = _LivePandasData
        elif unsupported_clock == "mixed_timeframe" and name == _BENCHMARK:
            timeframe = bt.TimeFrame.Minutes
        feed = _aligned_feed(
            frames[name],
            research,
            name,
            feed_class=feed_class,
            timeframe=timeframe,
        )
        if unsupported_clock == "replay" and name == "BENCH":
            cerebro.replaydata(feed, name=name)
        else:
            cerebro.adddata(feed, name=name)
    _add_strategy(cerebro, research)
    _stop_before_clock_iteration(cerebro, monkeypatch)

    with pytest.raises(ConfigError) as caught:
        cerebro.run(runonce=False, preload=False)

    assert caught.value.code == "UNSUPPORTED_CLOCK"
    assert not getattr(cerebro, "runstrats", ())


@pytest.mark.parametrize(
    "bindings,feed_names",
    (
        ({"target_close": "feed:target:close"}, (_TARGETS[0], _TARGETS[1], _BENCHMARK)),
        (
            {
                "target_close": "feed:target:close",
                "benchmark_close": "feed:MISSING:close",
            },
            (_TARGETS[0], _TARGETS[1]),
        ),
    ),
    ids=("missing-required-binding", "missing-required-feed"),
)
def test_missing_required_binding_or_named_feed_is_typed_missing_input(
    bindings: Mapping[str, Any],
    feed_names: Tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    research, frames, _ = _fixture()
    cerebro = bt.Cerebro(stdstats=False)
    for name in feed_names:
        cerebro.adddata(_aligned_feed(frames[name], research, name), name=name)
    _add_strategy(cerebro, research, factor_spec=_factor_spec(bindings))
    _stop_before_clock_iteration(cerebro, monkeypatch)

    with pytest.raises(DatasetError) as caught:
        cerebro.run(runonce=False, preload=False)

    assert caught.value.code == "MISSING_INPUT"
    assert not getattr(cerebro, "runstrats", ())
