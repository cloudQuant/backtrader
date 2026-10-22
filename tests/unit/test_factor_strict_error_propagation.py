"""Strict factor failures stay typed across native Backtrader callbacks."""

import pandas as pd
import pytest

import backtrader as bt
from backtrader.errors import ResearchConfigError as ConfigError, FactorComputationError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research import align_to_grid
from backtrader.research.operators import Multiply, OperatorInputError, OperatorReason
from backtrader.research.specs import FactorSpec, ResearchSpec


class _StrictProbeChild(bt.Indicator):
    lines = ("value",)
    params = (("mode", "divide"),)

    def __init__(self):
        super().__init__()
        if self.p.mode == "divide":
            self._probe = self.data.close / 0.0
        elif self.p.mode == "overflow":
            self._probe = self.data.close * 1.0e308

    def next(self):
        if self.p.mode == "unexpected":
            raise LookupError("synthetic child failure")
        if self.p.mode == "nan":
            self.lines.value[0] = float("nan")
        else:
            self.lines.value[0] = self._probe[0]


class _StrictProbeFactor(FactorIndicator):
    lines = ("value",)
    params = (("mode", "divide"),)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.child = _StrictProbeChild(self.data, mode=self.p.mode)

    def next(self):
        output = self.outputs[self.datas[0]].value
        output[0] = self.child.lines.value[0]


class _StrictBoundSourceFactor(FactorIndicator):
    lines = ("value",)
    formula_fields = ("close",)
    required_fields = formula_fields
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.child = Multiply(self.field_lines("close")[0], 1.0)

    def next(self):
        data = self.target_datas[0]
        value = self.child.lines.value[0]
        reason = OperatorReason(int(self.child.lines.reason[0]))
        self.outputs[data].value[0] = value
        self.record_availability(
            data,
            ready=True,
            valid=reason is OperatorReason.READY,
            reason=reason.name,
            line="value",
        )


class _StrictConstructorFailureChild(bt.Indicator):
    lines = ("value",)

    def __init__(self):
        super().__init__()
        raise LookupError("synthetic child constructor failure")


class _StrictConstructorFailureFactor(FactorIndicator):
    lines = ("value",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.child = _StrictConstructorFailureChild(self.data)

    def next(self):
        self.outputs[self.target_datas[0]].value[0] = self.child.lines.value[0]


def _research_inputs(values=(1.5, 2.0)):
    index = pd.date_range("2026-01-05", periods=len(values), freq="D", tz="UTC", name="close_time")
    frame = pd.DataFrame(
        {
            "open": values,
            "high": [value + 1.0 for value in values],
            "low": [value - 1.0 for value in values],
            "close": values,
            "volume": [100.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=index,
    )
    grid = pd.DataFrame(
        {"open_time": index - pd.Timedelta(minutes=1)},
        index=index,
    )
    research = ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=("asset-0",),
        source_timezone="UTC",
        snapshot_id="strict-error-test-v1",
        price_basis="synthetic unadjusted test units",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        groups={"asset-0": "synthetic"},
    )
    return research, frame


def _run_factor(mode, runonce, values=(1.5, 2.0)):
    research, frame = _research_inputs(values)
    factor = FactorSpec(
        name="strict_probe",
        indicator=_StrictProbeFactor,
        panel_line="value",
        params={"mode": mode},
    )
    cerebro = bt.Cerebro(stdstats=False)
    feed = align_to_grid(frame, research, "asset-0").feed
    cerebro.adddata(feed, name="asset-0")
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    return cerebro.run(runonce=runonce, preload=True)[0]


def _run_bound_source(source_value, runonce):
    research, frame = _research_inputs((source_value, 2.0))
    feed = align_to_grid(frame, research, "asset-0", data_version="strict-error-fixture-v1").feed
    return _run_bound_feed(research, feed, runonce)


def _run_bound_feed(research, feed, runonce):
    factor = FactorSpec(
        name="bound_source",
        indicator=_StrictBoundSourceFactor,
        panel_line="value",
        field_bindings={"close": "feed:target:close"},
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(feed, name="asset-0")
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    return cerebro.run(runonce=runonce, preload=True)[0]


def _renamed_pandas_feed(source_value, mapping):
    research, frame = _research_inputs((source_value, 2.0))
    aligned_feed = align_to_grid(
        frame, research, "asset-0", data_version="strict-error-fixture-v1"
    ).feed
    renamed = aligned_feed.p.dataname.rename(columns={"close": "settle"})
    close_mapping = "settle" if mapping == "name" else renamed.columns.get_loc("settle")
    feed = bt.feeds.PandasData(dataname=renamed, close=close_mapping)
    feed._factor_research_alignment_v1 = aligned_feed._factor_research_alignment_v1
    return research, feed


def _run_constructor_failure(runonce):
    research, frame = _research_inputs()
    factor = FactorSpec(
        name="strict_constructor",
        indicator=_StrictConstructorFailureFactor,
        panel_line="value",
    )
    cerebro = bt.Cerebro(stdstats=False)
    feed = align_to_grid(frame, research, "asset-0").feed
    cerebro.adddata(feed, name="asset-0")
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    return cerebro.run(runonce=runonce, preload=True)[0]


def _run_uninspectable_csv_source(tmp_path, runonce):
    research, frame = _research_inputs()
    aligned_feed = align_to_grid(frame, research, "asset-0").feed
    source = tmp_path / "synthetic.csv"
    source.write_text(
        "2026-01-05 00:00:00,1.5,2.5,0.5,inf,100,0\n" "2026-01-06 00:00:00,2.0,3.0,1.0,2.0,100,0\n",
        encoding="ascii",
    )
    feed = bt.feeds.GenericCSVData(
        dataname=str(source),
        dtformat="%Y-%m-%d %H:%M:%S",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=6,
    )
    feed._factor_research_alignment_v1 = aligned_feed._factor_research_alignment_v1
    return _run_bound_feed(research, feed, runonce)


@pytest.mark.parametrize("runonce", (False, True))
@pytest.mark.parametrize(
    ("mode", "cause_type"),
    (("divide", ZeroDivisionError), ("overflow", ArithmeticError), ("unexpected", LookupError)),
)
def test_native_child_failures_raise_contextual_factor_errors(runonce, mode, cause_type):
    with pytest.raises(FactorComputationError) as caught:
        _run_factor(mode, runonce)

    error = caught.value
    assert error.code == "FACTOR_COMPUTATION_FAILED"
    assert error.factor == "strict_probe"
    assert error.asset == "asset-0"
    assert error.phase in {"next", "once", "once_via_next"}
    assert isinstance(error.__cause__, cause_type)


@pytest.mark.parametrize("runonce", (False, True))
def test_explicit_nan_remains_a_missing_factor_value(runonce):
    strategy = _run_factor("nan", runonce)

    raw_factors = strategy.get_panel().factors
    assert len(raw_factors) == 2
    assert raw_factors["strict_probe"].isna().all()


@pytest.mark.parametrize("runonce", (False, True))
def test_factor_dependency_contexts_are_isolated(runonce):
    research, frame = _research_inputs()
    factors = {
        name: FactorSpec(
            name=name,
            indicator=_StrictProbeFactor,
            panel_line="value",
            params={"mode": "nan"},
        )
        for name in ("first", "second")
    }
    cerebro = bt.Cerebro(stdstats=False)
    feed = align_to_grid(frame, research, "asset-0").feed
    cerebro.adddata(feed, name="asset-0")
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategy = cerebro.run(runonce=runonce, preload=True)[0]

    first, second = (strategy.factor_instances[name] for name in ("first", "second"))
    first_context = first._factor_strict_context
    second_context = second._factor_strict_context
    assert first_context is not second_context
    assert first_context.factor == "first"
    assert second_context.factor == "second"
    assert first.child._factor_strict_context is first_context
    assert second.child._factor_strict_context is second_context


@pytest.mark.parametrize("runonce", (False, True))
@pytest.mark.parametrize("source_value", (float("inf"), float("-inf")))
def test_bound_source_infinity_raises_contextual_factor_error(runonce, source_value):
    with pytest.raises(FactorComputationError) as caught:
        _run_bound_source(source_value, runonce)

    error = caught.value
    assert error.code == "FACTOR_COMPUTATION_FAILED"
    assert error.factor == "bound_source"
    assert error.asset == "asset-0"
    assert error.phase == "construct"
    assert isinstance(error.__cause__, OperatorInputError)










@pytest.mark.parametrize("runonce", (False, True))
def test_child_constructor_exception_is_contextual(runonce):
    with pytest.raises(FactorComputationError) as caught:
        _run_constructor_failure(runonce)

    error = caught.value
    assert error.code == "FACTOR_COMPUTATION_FAILED"
    assert error.factor == "strict_constructor"
    assert error.asset == "asset-0"
    assert error.phase == "init"
    assert isinstance(error.__cause__, LookupError)


class _OrdinaryInfinityReader(bt.Strategy):
    def __init__(self):
        self.values = []

    def next(self):
        self.values.append(float(self.data.close[0]))


def test_strict_failure_context_does_not_leak_into_a_following_ordinary_strategy():
    with pytest.raises(FactorComputationError):
        _run_factor("divide", runonce=False)

    index = pd.date_range("2026-01-05", periods=2, freq="D", tz="UTC", name="close_time")
    frame = pd.DataFrame(
        {
            "open": [1.0, 1.0],
            "high": [2.0, 2.0],
            "low": [0.0, 0.0],
            "close": [float("inf"), float("inf")],
            "volume": [100.0, 100.0],
            "openinterest": [0.0, 0.0],
        },
        index=index,
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="ordinary")
    cerebro.addstrategy(_OrdinaryInfinityReader)
    strategy = cerebro.run(runonce=False, preload=True)[0]

    assert strategy.values == [0.0, 0.0]
