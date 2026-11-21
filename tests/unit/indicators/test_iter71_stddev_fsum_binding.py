"""Dynamic fsum binding in StdDev's short and historical long-window paths."""

import builtins
import datetime as dt
import math
import os
import subprocess
import sys

import pytest

import backtrader as bt


class Feed(bt.feed.DataBase):
    params = (("count", 140),)

    def __init__(self):
        super().__init__()
        self.index = 0

    def _load(self):
        if self.index >= self.p.count:
            return False
        self.datetime[0] = bt.date2num(
            dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=self.index)
        )
        self.index += 1
        self.open[0] = self.high[0] = self.low[0] = self.close[0] = 100.0
        self.volume[0], self.openinterest[0] = 1.0, 0.0
        return True


def indicator(period):
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.StandardDeviation(self.data.close, period=period)

    c = bt.Cerebro(stdstats=False, runonce=False)
    c.adddata(Feed())
    c.addstrategy(Strategy)
    result = c.run()[0].ind
    for i in range(len(result.lines.stddev.array)):
        result.lines.stddev.array[i] = -1234.0
    return result


@pytest.mark.parametrize("period", [16, 20, 63, 64, 100])
def test_rebound_fsum_preserves_historical_inputs_and_result(monkeypatch, period):
    ind = indicator(period)
    original = math.fsum
    calls = []

    def altered(values):
        values = list(values)
        calls.append(values)
        return original(values) + 1.0

    monkeypatch.setattr(math, "fsum", altered)
    ind.once(period - 1, period + 8)
    assert len(calls) == 18
    expected_length = period if period < 64 else 1
    assert [len(value) for value in calls] == [expected_length] * 18
    expected = math.sqrt(abs((10000.0 + 1.0 / period) - (100.0 + 1.0 / period) ** 2))
    for value in ind.lines.stddev.array[period - 1 : period + 8]:
        assert value == expected


@pytest.mark.parametrize("period", [20, 64])
def test_rebound_fsum_failure_keeps_callback_count_and_written_prefix(monkeypatch, period):
    ind = indicator(period)
    original = math.fsum
    calls = []

    def altered(values):
        values = list(values)
        calls.append(values)
        if len(calls) == 3:
            raise ValueError("third fsum failure")
        return original(values) + 1.0

    monkeypatch.setattr(math, "fsum", altered)
    with pytest.raises(ValueError, match="third fsum failure"):
        ind.once(period - 1, period + 8)
    assert len(calls) == 3
    assert ind.lines.stddev.array[period - 1] != -1234.0
    assert list(ind.lines.stddev.array[period : period + 8]) == [-1234.0] * 8


@pytest.mark.parametrize("period", [20, 64])
def test_sqrt_callback_rebinding_fsum_is_seen_on_later_windows(monkeypatch, period):
    ind = indicator(period)
    original_fsum = math.fsum
    original_sqrt = math.sqrt
    calls = []
    sqrt_calls = []

    def changed(values):
        values = list(values)
        calls.append(values)
        return original_fsum(values) + 1.0

    def sqrt_and_replace(value):
        sqrt_calls.append(value)
        if len(sqrt_calls) == 1:
            monkeypatch.setattr(math, "fsum", changed)
        return original_sqrt(value)

    monkeypatch.setattr(math, "sqrt", sqrt_and_replace)
    ind.once(period - 1, period + 8)
    assert len(sqrt_calls) == 9
    assert len(calls) == 16
    assert [len(value) for value in calls] == [period if period < 64 else 1] * 16


@pytest.mark.parametrize("period", [20, 64])
def test_isfinite_rebinding_is_seen_only_where_historical_rolling_calls_it(monkeypatch, period):
    ind = indicator(period)
    original_fsum = math.fsum
    original_isfinite = math.isfinite
    calls = []
    checks = []

    def changed(values):
        values = list(values)
        calls.append(values)
        return original_fsum(values)

    def checked(value):
        checks.append(value)
        if len(checks) == 1:
            monkeypatch.setattr(math, "fsum", changed)
        return original_isfinite(value)

    monkeypatch.setattr(math, "isfinite", checked)
    ind.once(period - 1, period + 8)
    if period < 64:
        assert checks == [] and calls == []
    else:
        assert checks and len(calls) == 18


@pytest.mark.parametrize("period", [20, 64])
def test_preimport_fsum_replacement_does_not_become_a_trusted_native(period):
    code = r"""
import datetime as dt
import math
import sys
native = math.fsum
math.fsum = lambda values: native(values)
import backtrader as bt
math.fsum = native
class Feed(bt.feed.DataBase):
    def __init__(self):
        super().__init__()
        self.n = 0
    def _load(self):
        if self.n == 140: return False
        self.datetime[0] = bt.date2num(dt.datetime(2024, 1, 1) + dt.timedelta(days=self.n))
        self.n += 1
        self.open[0] = self.high[0] = self.low[0] = self.close[0] = 100.0
        self.volume[0] = self.openinterest[0] = 0.0
        return True
class Strategy(bt.Strategy):
    def __init__(self): self.ind = bt.ind.StandardDeviation(self.data.close, period=PERIOD)
c = bt.Cerebro(stdstats=False, runonce=False)
c.adddata(Feed())
c.addstrategy(Strategy)
ind = c.run()[0].ind
calls = []
def profile(frame, event, arg):
    if event == 'c_call' and arg is native: calls.append(1)
sys.setprofile(profile)
try: ind.once(PERIOD - 1, PERIOD + 8)
finally: sys.setprofile(None)
assert len(calls) == 18, len(calls)
""".replace("PERIOD", str(period))
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("period", [20, 64])
def test_real_factor_strategy_propagates_rebound_fsum_error(monkeypatch, period):
    import pandas as pd

    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    index = pd.date_range("2024-01-01", periods=140, freq="min", tz="UTC", name="close_time")
    frame = pd.DataFrame(dict.fromkeys(("open", "high", "low", "close"), 100.0), index=index)
    frame["volume"] = 1.0
    frame["openinterest"] = 0.0
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(minutes=1)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="test",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1min",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.ind.StandardDeviation(self.data.close, period=period)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=True)
    cerebro.adddata(align_to_grid(frame, research, "asset").feed, name="asset")
    spec = FactorSpec(
        name="std",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"std": spec})

    original_fsum = math.fsum

    def failing(values):
        if sys._getframe(1).f_code.co_filename.endswith("deviation.py"):
            raise ValueError("dynamic fsum failure")
        return original_fsum(values)

    monkeypatch.setattr(math, "fsum", failing)
    with pytest.raises(FactorComputationError) as error:
        cerebro.run(preload=True)
    assert isinstance(error.value.__cause__, ValueError)
    assert str(error.value.__cause__) == "dynamic fsum failure"


@pytest.mark.parametrize("period", [3, 20, 64])
@pytest.mark.parametrize("name", ["fsum", "sqrt", "isfinite"])
def test_missing_math_attribute_is_not_read_without_a_valid_window(monkeypatch, period, name):
    ind = indicator(period)
    monkeypatch.delattr(math, name)
    ind.once(0, 1)
    assert math.isnan(ind.lines.stddev.array[0])


@pytest.mark.parametrize("name", ["fsum", "sqrt", "isfinite"])
def test_reload_does_not_read_missing_math_attributes(name):
    code = r"""
import importlib
import math
import backtrader.indicators.deviation as module
delattr(math, NAME)
importlib.reload(module)
""".replace("NAME", repr(name))
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("period", [20, 64])
def test_missing_sqrt_preserves_fsum_calls_before_failure(monkeypatch, period):
    ind = indicator(period)
    original = math.fsum
    calls = []

    def observe(values):
        calls.append(list(values))
        return original(calls[-1])

    monkeypatch.setattr(math, "fsum", observe)
    monkeypatch.delattr(math, "sqrt")
    with pytest.raises(AttributeError, match="sqrt"):
        ind.once(0, period + 8)
    assert len(calls) == 2
    assert len(calls[0]) == (period if period < 64 else 1)


@pytest.mark.parametrize("period", [20, 64])
def test_missing_fsum_module_getattr_runs_only_at_original_call(monkeypatch, period):
    ind = indicator(period)
    calls = []

    def missing(name):
        calls.append(name)
        raise AttributeError(name)

    monkeypatch.delattr(math, "fsum")
    monkeypatch.setattr(math, "__getattr__", missing, raising=False)
    with pytest.raises(AttributeError, match="fsum"):
        ind.once(0, period + 8)
    assert calls == ["fsum"]


@pytest.mark.parametrize("period", [20, 64])
def test_dynamic_sqrt_getattr_runs_once_per_window(monkeypatch, period):
    ind = indicator(period)
    original = math.sqrt
    calls = []

    def missing(name):
        calls.append(name)
        if name == "sqrt":
            return original
        raise AttributeError(name)

    monkeypatch.delattr(math, "sqrt")
    monkeypatch.setattr(math, "__getattr__", missing, raising=False)
    ind.once(0, period + 3)
    assert calls == ["sqrt"] * 4


def test_reload_with_builtin_abs_missing():
    code = """
import builtins
import importlib
import backtrader.indicators.deviation as module
original = builtins.abs
del builtins.abs
try:
    importlib.reload(module)
finally:
    builtins.abs = original
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_reload_with_all_guarded_bindings_missing():
    code = """
import builtins
import importlib
import math
import backtrader.indicators.deviation as module
originals = [(math, name, getattr(math, name)) for name in ("fsum", "sqrt", "isfinite")]
originals.append((builtins, "abs", builtins.abs))
for owner, name, value in originals:
    delattr(owner, name)
try:
    importlib.reload(module)
finally:
    for owner, name, value in originals:
        setattr(owner, name, value)
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("period", [20, 64])
def test_missing_builtin_abs_preserves_fsum_calls_before_failure(monkeypatch, period):
    ind = indicator(period)
    original_fsum = math.fsum
    original_abs = builtins.abs
    calls = []

    def observe(values):
        calls.append(list(values))
        return original_fsum(calls[-1])

    monkeypatch.setattr(math, "fsum", observe)
    error = None
    del builtins.abs
    try:
        ind.once(0, period + 8)
    except NameError as exc:
        error = exc
    finally:
        builtins.abs = original_abs
    assert isinstance(error, NameError)
    assert len(calls) == (2 if period < 64 else 0)
