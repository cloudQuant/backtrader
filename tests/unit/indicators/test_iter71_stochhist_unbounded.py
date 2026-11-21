"""Limited unbounded stochastic histogram warm-up regression checks."""

import math

import backtrader as bt
import pandas as pd
import pytest


def bars(n=40):
    close = [100.0 + i * 0.17 + (i * 7 % 13) * 0.31 for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [v + 0.4 + (i * 5 % 7) * 0.13 for i, v in enumerate(close)],
            "low": [v - 0.6 - (i * 3 % 5) * 0.19 for i, v in enumerate(close)],
            "close": close,
            "volume": [1.0] * n,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="D"),
    )


def reference(high, low, close, method):
    fasts, mains, signals = [], [], []

    def avg(values, period, prev):
        v = values[-1]
        if method == "ema":
            return (
                v if prev is None or math.isnan(prev) else prev + 2.0 / (period + 1.0) * (v - prev)
            )
        if method == "smma":
            return v if prev is None or math.isnan(prev) else ((period - 1.0) * prev + v) / period
        if method == "lwma":
            weights = list(range(1, len(values) + 1))
            return sum(v * w for v, w in zip(values, weights)) / sum(weights)
        return sum(values) / len(values)

    for i in range(len(close)):
        if i < 4:
            k = math.nan
        else:
            lo = min(low[i - 4 : i + 1])
            hi = max(high[i - 4 : i + 1])
            k = 100.0 * (close[i] - lo) / (hi - lo) if hi != lo else 50.0
        fasts.append(k)
        mains.append(avg(fasts[max(0, i - 2) : i + 1], 3, mains[-1] if mains else None))
        signals.append(avg(mains[max(0, i - 2) : i + 1], 3, signals[-1] if signals else None))
    return mains, signals


def equal(got, expected):
    assert len(got) == len(expected)
    for a, b in zip(got, expected):
        if math.isnan(b):
            assert math.isnan(a)
        else:
            assert a == pytest.approx(b, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("method", ["sma", "ema", "smma", "lwma"])
@pytest.mark.parametrize("missing", [False, True])
def test_full_unbounded_cerebro_series(method, missing):
    frame = bars()
    if missing:
        frame.iloc[15, frame.columns.get_loc("high")] = math.nan
        frame.iloc[20, frame.columns.get_loc("low")] = math.nan
        frame.iloc[24, frame.columns.get_loc("close")] = math.nan
    outputs = []
    for once in (False, True):

        class Strategy(bt.Strategy):
            def __init__(self):
                self.hist = bt.ind.StochasticHistogramIndicator(
                    self.data, k_period=5, slowing=3, d_period=3, ma_method=method
                )

        cerebro = bt.Cerebro(stdstats=False, runonce=once)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
        cerebro.addstrategy(Strategy)
        outputs.append(cerebro.run(preload=once)[0].hist)
    main, signal = reference(frame.high.tolist(), frame.low.tolist(), frame.close.tolist(), method)
    for ind in outputs:
        assert ind._minperiod == 13
        equal(list(ind.main.array)[12:], main[12:])
        equal(list(ind.signal.array)[12:], signal[12:])
    for name in ("main", "signal", "hist_base", "color_state"):
        equal(
            list(getattr(outputs[0].lines, name).array), list(getattr(outputs[1].lines, name).array)
        )


@pytest.mark.parametrize("method", ["ema", "smma"])
def test_replay_current_bar_matches_visible_history(method):
    frame = bars(100)
    frame.index = pd.date_range("2020-01-01", periods=100, freq="min")
    samples = []

    class Strategy(bt.Strategy):
        def __init__(self):
            self.hist = bt.ind.StochasticHistogramIndicator(
                self.data, k_period=5, slowing=3, d_period=3, ma_method=method
            )

        def next(self):
            pos = self.data.high.idx
            h = list(self.data.high.array)[: pos + 1]
            l = list(self.data.low.array)[: pos + 1]
            c = list(self.data.close.array)[: pos + 1]
            main, signal = reference(h, l, c, method)
            samples.append(
                (
                    len(self.data),
                    float(self.hist.main[0]),
                    float(self.hist.signal[0]),
                    main[-1],
                    signal[-1],
                )
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.replaydata(
        bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    cerebro.addstrategy(Strategy)
    cerebro.run()
    assert any(a[0] == b[0] for a, b in zip(samples, samples[1:]))
    for _, main, signal, want_main, want_signal in samples:
        assert main == pytest.approx(want_main, rel=1e-12, abs=1e-12)
        assert signal == pytest.approx(want_signal, rel=1e-12, abs=1e-12)


def test_rebound_parameter_manager_keeps_legacy_read_count(monkeypatch):
    from backtrader.parameters import ParameterManager

    old = ParameterManager.get
    counts = []
    target = []

    def wrapped(self, name, *args, **kwargs):
        if target and self is target[0] and name == "ma_method":
            counts.append(name)
        return old(self, name, *args, **kwargs)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.hist = bt.ind.StochasticHistogramIndicator(
                self.data, k_period=5, slowing=3, d_period=3, ma_method="ema"
            )
            target.append(self.hist.p._param_manager)

    monkeypatch.setattr(ParameterManager, "get", wrapped)
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=bars(24)))
    cerebro.addstrategy(Strategy)
    cerebro.run()
    assert len(counts) == 25


@pytest.mark.parametrize("method", ["ema", "smma"])
def test_faster_secondary_clock_does_not_advance_primary(method):
    primary = bars(24)
    secondary = bars(48)
    secondary.index = pd.date_range("2020-01-01", periods=48, freq="12h")
    samples = []

    class Strategy(bt.Strategy):
        def __init__(self):
            self.hist = bt.ind.StochasticHistogramIndicator(
                self.data0, k_period=5, slowing=3, d_period=3, ma_method=method
            )

        def next(self):
            pos = self.data0.high.idx
            high = list(self.data0.high.array)[: pos + 1]
            low = list(self.data0.low.array)[: pos + 1]
            close = list(self.data0.close.array)[: pos + 1]
            mains, signals = reference(high, low, close, method)
            samples.append(
                (
                    len(self.data0),
                    float(self.hist.main[0]),
                    float(self.hist.signal[0]),
                    mains[-1],
                    signals[-1],
                )
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=primary))
    cerebro.adddata(bt.feeds.PandasData(dataname=secondary))
    cerebro.addstrategy(Strategy)
    cerebro.run()
    assert any(a[0] == b[0] for a, b in zip(samples, samples[1:]))
    for _, main, signal, want_main, want_signal in samples:
        assert main == pytest.approx(want_main, rel=1e-12, abs=1e-12)
        assert signal == pytest.approx(want_signal, rel=1e-12, abs=1e-12)


def test_subclass_unrelated_legacy_name_is_not_called():
    class Custom(bt.ind.StochasticHistogramIndicator):
        alias = ()

        def _next_legacy(self):
            raise RuntimeError("unrelated subclass method")

    class Strategy(bt.Strategy):
        def __init__(self):
            self.hist = Custom(self.data, k_period=5, slowing=3, d_period=3)

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=bars(24)))
    cerebro.addstrategy(Strategy)
    cerebro.run()


@pytest.mark.parametrize(
    "field,bar,should_fail", [("high", 12, True), ("low", 12, True), ("high", 2, False)]
)
def test_strict_factor_preserves_legacy_input_window(field, bar, should_fail):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    n = 30
    index = pd.date_range("2024-01-01", periods=n, freq="min", tz="UTC", name="close_time")
    frame = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
            "openinterest": [0.0] * n,
        },
        index=index,
    )
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
        formula_fields = required_fields = ("high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.ind.StochasticHistogramIndicator(
                self.data, k_period=3, slowing=1, d_period=1
            )

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.main[0]

    feed = align_to_grid(frame, research, "asset").feed
    original = feed._load

    def injected_load():
        ok = original()
        if ok and len(feed) == bar:
            line = getattr(feed.lines, field)
            line.array[line.idx] = float("inf")
        return ok

    feed._load = injected_load
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.adddata(feed, name="asset")
    spec = FactorSpec(
        name="test",
        indicator=Factor,
        panel_line="factor",
        field_bindings={k: "feed:target:" + k for k in Factor.formula_fields},
        mode="native",
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"test": spec})
    if should_fail:
        with pytest.raises(FactorComputationError) as caught:
            cerebro.run()
        assert isinstance(caught.value.__cause__, ArithmeticError)
    else:
        cerebro.run()


def test_threshold_conversion_occurs_after_main_and_signal_writes():
    holder = {}
    samples = []

    class Threshold:
        def __float__(self):
            holder["indicator"].lines.main[0] = 7.0
            return 60.0

    class Strategy(bt.Strategy):
        def __init__(self):
            self.hist = bt.ind.StochasticHistogramIndicator(
                self.data, k_period=3, slowing=1, d_period=1, high_level=Threshold()
            )
            holder["indicator"] = self.hist

        def next(self):
            if len(self.data) == 10:
                samples.append((float(self.hist.main[0]), float(self.hist.signal[0])))

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=bars(30)))
    cerebro.addstrategy(Strategy)
    cerebro.run()
    assert len(samples) == 1
    assert samples[0][0] == 7.0
    assert math.isfinite(samples[0][1])


@pytest.mark.parametrize("field", ["high", "low"])
def test_direct_source_strict_context_without_scope_uses_legacy_read(field):
    from backtrader.errors import FactorComputationContext, FactorComputationError

    class Strategy(bt.Strategy):
        def __init__(self):
            self.hist = bt.ind.StochasticHistogramIndicator(
                self.data, k_period=3, slowing=1, d_period=1
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=bars(24)))
    cerebro.addstrategy(Strategy)
    hist = cerebro.run()[0].hist
    line = getattr(hist.data, field)
    old = line.array[line.idx]
    context = FactorComputationContext("test", phase="next")
    line._factor_strict_context = context
    line.array[line.idx] = float("inf")
    try:
        with pytest.raises(FactorComputationError) as caught:
            hist.next()
        assert isinstance(caught.value.__cause__, ArithmeticError)
    finally:
        line.array[line.idx] = old
        del line._factor_strict_context


def test_strict_context_preserves_wip_subclass_legacy_dispatch():
    from backtrader.errors import FactorComputationContext

    calls = []

    class Custom(bt.ind.StochasticHistogramIndicator):
        alias = ()

        def _fast_k_at(self, *args):
            return super()._fast_k_at(*args)

        def _next_legacy(self):
            calls.append("legacy")
            return super()._next_legacy()

    class Strategy(bt.Strategy):
        def __init__(self):
            self.hist = Custom(self.data, k_period=3, slowing=1, d_period=1)

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=bars(24)))
    cerebro.addstrategy(Strategy)
    hist = cerebro.run()[0].hist
    calls.clear()
    line = hist.data.high
    line._factor_strict_context = FactorComputationContext("test", phase="next")
    try:
        hist.next()
    finally:
        del line._factor_strict_context
    assert calls == ["legacy"]


@pytest.mark.parametrize("switch_after_first", [False, True])
def test_custom_threshold_feedback_uses_legacy_recurrence(switch_after_first):
    holder = {}
    samples = []

    class Threshold:
        def __float__(self):
            if not holder.get("changed"):
                holder["indicator"].lines.main[0] = 7.0
                holder["changed"] = True
            return 60.0

    class Strategy(bt.Strategy):
        def __init__(self):
            threshold = 60.0 if switch_after_first else Threshold()
            self.hist = bt.ind.StochasticHistogramIndicator(
                self.data, k_period=3, slowing=2, d_period=1, ma_method="ema", high_level=threshold
            )
            holder["indicator"] = self.hist

        def next(self):
            samples.append((len(self.data), float(self.hist.main[0])))
            if switch_after_first and len(self.data) == 8:
                self.hist.p.high_level = Threshold()
            if len(self.data) == (10 if switch_after_first else 9):
                self.hist.p.high_level = 60.0

    n = 15
    frame = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
        },
        index=pd.date_range("2024-01-01", periods=n, freq="min"),
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Strategy)
    cerebro.run()
    by_bar = dict(samples)
    first = 9 if switch_after_first else 8
    assert by_bar[first] == 7.0
    assert by_bar[first + 1] == pytest.approx(35.666666666666664)
    assert by_bar[first + 2] == pytest.approx(45.22222222222222)


def test_custom_threshold_failure_preserves_legacy_written_slots():
    holder = {}

    class Threshold:
        def __float__(self):
            raise RuntimeError("threshold failed")

    class Strategy(bt.Strategy):
        def __init__(self):
            self.hist = bt.ind.StochasticHistogramIndicator(
                self.data,
                k_period=3,
                slowing=2,
                d_period=1,
                ma_method="ema",
                high_level=Threshold(),
            )
            holder["indicator"] = self.hist

    n = 15
    frame = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
        },
        index=pd.date_range("2024-01-01", periods=n, freq="min"),
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Strategy)
    with pytest.raises(RuntimeError, match="threshold failed"):
        cerebro.run()
    hist = holder["indicator"]
    assert hist.main[0] == 50.0
    assert hist.signal[0] == 50.0
    assert math.isnan(hist.hist_base[0]) and math.isnan(hist.color_state[0])


@pytest.mark.parametrize(
    "name", ["main", "signal", "hist_base", "color_state", "high", "low", "close"]
)
def test_attached_strict_context_on_any_used_line_switches_to_legacy(name):
    from backtrader.errors import FactorComputationContext

    class Strategy(bt.Strategy):
        def __init__(self):
            self.hist = bt.ind.StochasticHistogramIndicator(
                self.data, k_period=3, slowing=1, d_period=1
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=bars(24)))
    cerebro.addstrategy(Strategy)
    hist = cerebro.run()[0].hist
    assert hist._stream_state_params is not None
    line = (
        getattr(hist.lines, name)
        if name in ("main", "signal", "hist_base", "color_state")
        else getattr(hist.data, name)
    )
    calls = []
    original = hist._next_legacy

    def wrapped():
        calls.append("legacy")
        return original()

    hist._next_legacy = wrapped
    line._factor_strict_context = FactorComputationContext("test", phase="next")
    try:
        hist.next()
    finally:
        del line._factor_strict_context
    assert calls == ["legacy"]
    assert hist._stream_force_legacy
