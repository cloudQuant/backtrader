"""R71-159/160 focused indicator windows, extracted from the mixed public suite."""
import datetime as dt
import math
import pytest
import backtrader as bt
import backtrader.indicators.basicops as basicops_mod
import backtrader.indicators.deviation as deviation_mod

class _SyntheticFeed(bt.feed.DataBase):
    """Deterministic in-memory feed for real Cerebro parity tests."""

    params = (("input_values", ()), ("raw_close_infinities", False))

    def __init__(self):
        super().__init__()
        self._index = 0

    def _load(self):
        if self._index >= len(self.p.input_values):
            return False

        value = float(self.p.input_values[self._index])
        moment = dt.datetime(2026, 1, 1) + dt.timedelta(minutes=self._index)
        self.lines.datetime[0] = bt.date2num(moment)
        self.lines.open[0] = value
        self.lines.high[0] = value + 1.0 if math.isfinite(value) else value
        self.lines.low[0] = value - 1.0 if math.isfinite(value) else value
        self.lines.close[0] = value
        if self.p.raw_close_infinities and math.isinf(value):
            self.lines.close.array[-1] = value
        self.lines.volume[0] = 10.0 + (self._index % 7)
        self.lines.openinterest[0] = 0.0
        self._index += 1
        return True


def _sample_values(count, *, offset=0.0):
    return [
        offset + ((i * 17) % 37 - 18) * 0.125 + (i % 5) * 0.0001
        for i in range(count)
    ]


def _assert_bit_exact_sequence(actual, expected):
    assert len(actual) == len(expected)
    for idx, (a, e) in enumerate(zip(actual, expected)):
        if math.isnan(e):
            assert math.isnan(a), f"index {idx}: expected NaN, got {a!r}"
        else:
            assert a == e, f"index {idx}: {a!r} != {e!r}"
            if a == 0.0:
                assert math.copysign(1.0, a) == math.copysign(1.0, e), f"index {idx}: zero sign"



# ===========================================================================
# R71-159: basicops SumN / AnyN / AllN runonce parity & boundaries
# ===========================================================================


def _run_indicator(values, indicator_cls, *, period, runonce, exactbars=0, raw_inf=False, **kwargs):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = indicator_cls(self.data.close, period=period, **kwargs)
            self.recorded = []

        def _rec(self):
            self.recorded.append(float(self.ind[0]))

        def prenext(self):
            self._rec()

        def nextstart(self):
            self._rec()

        def next(self):
            self._rec()

        def stop(self):
            self.raw_array = list(self.ind.lines[0].array)

    cerebro = bt.Cerebro(
        stdstats=False,
        runonce=runonce,
        preload=not exactbars,
        exactbars=exactbars,
    )
    cerebro.adddata(
        _SyntheticFeed(input_values=values, raw_close_infinities=raw_inf), name="SYNTH"
    )
    cerebro.addstrategy(Probe)
    (strat,) = cerebro.run()
    return strat


@pytest.mark.parametrize("period", (1, 15, 31, 32, 48, 64, 128))
@pytest.mark.parametrize("offset", (0.0, 1e8), ids=("near-zero", "large-offset"))
def test_r71_159_sumn_runonce_matches_runnext_and_fsum_oracle(period, offset):
    values = _sample_values(320, offset=offset)
    expected = [
        float("nan") if i < period - 1 else math.fsum(values[i - period + 1 : i + 1])
        for i in range(len(values))
    ]

    runnext = _run_indicator(values, bt.indicators.SumN, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, bt.indicators.SumN, period=period, runonce=True).raw_array

    _assert_bit_exact_sequence(runnext, expected)
    _assert_bit_exact_sequence(runonce, expected)
    _assert_bit_exact_sequence(runonce, runnext)


@pytest.mark.parametrize("period", (32, 64))
def test_r71_159_sumn_catastrophic_cancellation_and_nan_recovery(period):
    values = ([1e16, 1.0, -1e16, 0.125, -0.125, 1e-16, -1e-16, 3.0] * 30)[:240]
    values[70] = float("nan")
    values[160] = float("nan")

    expected = [
        float("nan") if i < period - 1 else math.fsum(values[i - period + 1 : i + 1])
        for i in range(len(values))
    ]
    runnext = _run_indicator(values, bt.indicators.SumN, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, bt.indicators.SumN, period=period, runonce=True).raw_array

    _assert_bit_exact_sequence(runonce, expected)
    _assert_bit_exact_sequence(runonce, runnext)
    # Verify finite recovery after NaN exits the window.
    assert math.isfinite(runonce[70 + period])
    assert math.isfinite(runonce[160 + period])


def test_r71_159_sumn_upstream_warmup_nan_chunks_qbuffer_and_subclass_fallback():
    values = _sample_values(220, offset=50.0)

    # Upstream SMA produces 14 leading NaN bars.
    class UpstreamProbe(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=15)
            self.sumn = bt.indicators.SumN(self.sma, period=32)

        def stop(self):
            self.result = list(self.sumn.lines[0].array)

    def run_upstream(runonce):
        c = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
        c.adddata(_SyntheticFeed(input_values=values))
        c.addstrategy(UpstreamProbe)
        return c.run()[0].result

    _assert_bit_exact_sequence(run_upstream(True), run_upstream(False))

    # Arbitrary chunked once() calls match a single full pass bit-for-bit.
    full = _run_indicator(values, bt.indicators.SumN, period=32, runonce=True).raw_array
    strat = _run_indicator(values, bt.indicators.SumN, period=32, runonce=False)
    dst = strat.ind.lines[0].array
    for i in range(len(dst)):
        dst[i] = float("nan")
    for start, end in ((0, 10), (10, 31), (31, 32), (32, 100), (100, len(values))):
        strat.ind.once(start, end)
    _assert_bit_exact_sequence(list(dst), full)

    # QBuffer (exactbars=1) parity.
    q_strat = _run_indicator(values, bt.indicators.SumN, period=32, runonce=False, exactbars=1)
    _assert_bit_exact_sequence(q_strat.recorded, full)

    # Subclass and monkeypatched module global must not qualify for SumN fast path.
    calls = []

    def tracking_fsum(window):
        calls.append(len(window))
        return math.fsum(window)

    class CustomSumN(bt.indicators.SumN):
        func = staticmethod(tracking_fsum)

    sub_strat = _run_indicator(values[:90], CustomSumN, period=32, runonce=True)
    assert len(calls) >= 90 - 31
    _assert_bit_exact_sequence(sub_strat.raw_array, full[:90])

    # Raw array infinities (+inf, -inf -> ValueError -> nan) & recovery.
    inf_vals = _sample_values(140, offset=10.0)
    inf_vals[40] = float("inf")
    inf_vals[45] = float("-inf")
    inf_strat = _run_indicator(
        inf_vals, bt.indicators.SumN, period=32, runonce=True, raw_inf=True
    )
    assert math.isinf(inf_strat.raw_array[40])
    assert math.isnan(inf_strat.raw_array[45])
    assert math.isfinite(inf_strat.raw_array[45 + 32])


def test_r71_159_sumn_monkeypatch_cannot_requalify_subclass(monkeypatch):
    calls = []

    class SubSumN(bt.indicators.SumN):
        def __init__(self):
            super().__init__()

    orig_fsum = math.fsum

    def spy_fsum(w):
        calls.append(len(w))
        return orig_fsum(w)

    SubSumN.func = staticmethod(spy_fsum)
    monkeypatch.setattr(basicops_mod, "SumN", SubSumN)

    values = _sample_values(80, offset=10.0)
    _run_indicator(values, SubSumN, period=32, runonce=True)
    assert len(calls) >= 80 - 31


@pytest.mark.parametrize("ind_cls", (bt.indicators.AnyN, bt.indicators.AllN))
@pytest.mark.parametrize("period", (5, 32, 64))
def test_r71_159_anyn_alln_runonce_matches_runnext_with_special_floats(ind_cls, period):
    values = [0.0] * 140
    for idx in (0, 35, 36, 70, 100, 101, 102):
        values[idx] = 1.0
    values[10] = -0.0
    values[50] = float("nan")
    if ind_cls is bt.indicators.AllN:
        for idx in range(70, 140):
            values[idx] = 2.0
        values[95] = -0.0
        values[120] = float("nan")

    runnext = _run_indicator(values, ind_cls, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, ind_cls, period=period, runonce=True).raw_array
    _assert_bit_exact_sequence(runonce, runnext)


# ===========================================================================
# R71-160: SMA & StandardDeviation rolling exact sums parity & boundaries
# ===========================================================================


@pytest.mark.parametrize("period", (1, 15, 16, 31, 32, 64, 128))
@pytest.mark.parametrize("offset", (0.0, 1e8), ids=("near-zero", "large-offset"))
def test_r71_160_sma_runonce_matches_runnext_and_fsum_oracle(period, offset):
    values = _sample_values(320, offset=offset)
    expected = [
        float("nan") if i < period - 1 else math.fsum(values[i - period + 1 : i + 1]) / period
        for i in range(len(values))
    ]

    runnext = _run_indicator(values, bt.indicators.SMA, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, bt.indicators.SMA, period=period, runonce=True).raw_array

    _assert_bit_exact_sequence(runnext, expected)
    _assert_bit_exact_sequence(runonce, expected)
    _assert_bit_exact_sequence(runonce, runnext)


@pytest.mark.parametrize("period", (16, 32, 64))
def test_r71_160_sma_cancellation_nan_recovery_chunks_and_short_data(period):
    values = ([1e16, 1.0, -1e16, 0.125, -0.125, 1e-16, -1e-16, 3.0] * 30)[:240]
    values[65] = float("nan")
    values[150] = float("nan")

    expected = [
        float("nan") if i < period - 1 else math.fsum(values[i - period + 1 : i + 1]) / period
        for i in range(len(values))
    ]
    runnext = _run_indicator(values, bt.indicators.SMA, period=period, runonce=False).raw_array
    runonce = _run_indicator(values, bt.indicators.SMA, period=period, runonce=True).raw_array

    _assert_bit_exact_sequence(runonce, expected)
    _assert_bit_exact_sequence(runonce, runnext)
    assert math.isfinite(runonce[65 + period])
    assert math.isfinite(runonce[150 + period])

    # Chunked once() calls match full pass bit-for-bit.
    strat = _run_indicator(values, bt.indicators.SMA, period=period, runonce=False)
    dst = strat.ind.lines[0].array
    for i in range(len(dst)):
        dst[i] = float("nan")
    for start, end in ((0, 5), (5, period - 1), (period - 1, period + 2), (period + 2, len(values))):
        strat.ind.once(start, end)
    _assert_bit_exact_sequence(list(dst), expected)

    # Short data (len < period) stays all NaN in both modes.
    short_vals = _sample_values(max(1, period - 3), offset=10.0)
    short_once = _run_indicator(short_vals, bt.indicators.SMA, period=period, runonce=True).raw_array
    short_next = _run_indicator(short_vals, bt.indicators.SMA, period=period, runonce=False).raw_array
    assert all(math.isnan(v) for v in short_once)
    assert all(math.isnan(v) for v in short_next)


def test_r71_160_sma_upstream_indicator_inf_and_overflow_fallback():
    values = _sample_values(220, offset=50.0)

    class NestedSMA(bt.Strategy):
        def __init__(self):
            self.inner = bt.indicators.SMA(self.data.close, period=15)
            self.outer = bt.indicators.SMA(self.inner, period=40)

        def stop(self):
            self.result = list(self.outer.lines[0].array)

    def run_nested(runonce):
        c = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
        c.adddata(_SyntheticFeed(input_values=values))
        c.addstrategy(NestedSMA)
        return c.run()[0].result

    _assert_bit_exact_sequence(run_nested(True), run_nested(False))

    # Raw array with +inf, -inf, and nan inside the same window yields NaN cleanly.
    mixed = _sample_values(120, offset=10.0)
    mixed[40] = float("inf")
    mixed[42] = float("-inf")
    mixed[44] = float("nan")
    mixed_strat = _run_indicator(
        mixed, bt.indicators.SMA, period=32, runonce=True, raw_inf=True
    )
    assert math.isnan(mixed_strat.raw_array[44])
    assert math.isfinite(mixed_strat.raw_array[44 + 32])

    # Finite overflow propagates OverflowError consistently in both modes.
    ovf = [1e308] * 80
    for mode in (False, True):
        with pytest.raises(OverflowError):
            _run_indicator(ovf, bt.indicators.SMA, period=32, runonce=mode)
        with pytest.raises(OverflowError):
            _run_indicator(ovf, bt.indicators.SumN, period=32, runonce=mode)


@pytest.mark.parametrize("period", (8, 15, 16, 20, 32, 48, 64, 128))
@pytest.mark.parametrize("offset", (0.0, 1e8), ids=("near-zero", "large-offset"))
@pytest.mark.parametrize("safepow", (True, False), ids=("safepow", "nosafepow"))
def test_r71_160_stddev_default_and_medium_periods_exact_parity(period, offset, safepow):
    values = _sample_values(300, offset=offset)

    runnext = _run_indicator(
        values, bt.indicators.StandardDeviation, period=period, runonce=False, safepow=safepow
    ).raw_array
    runonce = _run_indicator(
        values, bt.indicators.StandardDeviation, period=period, runonce=True, safepow=safepow
    ).raw_array

    _assert_bit_exact_sequence(runonce, runnext)


def test_r71_160_stddev_period20_cancellation_nan_recovery_upstream_and_subclass():
    # Catastrophic cancellation + multiple interior NaN gaps at default period=20.
    values = ([1e16, 1.0, -1e16, 1.0] * 40) + _sample_values(100, offset=100.0)
    values[50] = float("nan")
    values[140] = float("nan")

    runnext = _run_indicator(
        values, bt.indicators.StandardDeviation, period=20, runonce=False
    ).raw_array
    runonce = _run_indicator(
        values, bt.indicators.StandardDeviation, period=20, runonce=True
    ).raw_array
    _assert_bit_exact_sequence(runonce, runnext)
    assert math.isfinite(runonce[50 + 20])
    assert math.isfinite(runonce[140 + 20])

    # Upstream SMA leading NaN warmup feeding StandardDeviation(period=20).
    class UpstreamStdDev(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=15)
            self.sd = bt.indicators.StandardDeviation(self.sma, period=20)

        def stop(self):
            self.result = list(self.sd.lines[0].array)

    def run_up(runonce):
        c = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
        c.adddata(_SyntheticFeed(input_values=_sample_values(160, offset=50.0)))
        c.addstrategy(UpstreamStdDev)
        return c.run()[0].result

    _assert_bit_exact_sequence(run_up(True), run_up(False))

    # Subclass overriding _finish at period=20 must stay on original per-window path.
    class CountingStdDev(deviation_mod.StandardDeviation):
        def __init__(self):
            self.calls = 0
            super().__init__()

        def _finish(self, meansq, mean):
            self.calls += 1
            return super()._finish(meansq, mean)

    sub_strat = _run_indicator(_sample_values(80), CountingStdDev, period=20, runonce=True)
    assert sub_strat.ind.calls >= 80 - 19
    ref = _run_indicator(_sample_values(80), bt.indicators.StandardDeviation, period=20, runonce=False)
    _assert_bit_exact_sequence(sub_strat.raw_array, ref.raw_array)


@pytest.mark.parametrize("indicator_type", (bt.ind.SumN, bt.ind.AnyN, bt.ind.AllN, bt.ind.SMA, bt.ind.StandardDeviation))
def test_noncontiguous_overlapping_reverse_segments_against_head_window_contract(indicator_type):
    period = 32
    values = _sample_values(80, offset=10.0)
    values[7] = float("nan")
    values[49] = float("nan")
    indicator = _run_indicator(values, indicator_type, period=period, runonce=False).ind
    source = indicator.data.array
    target = indicator.lines[0].array
    while len(target) < 90:
        target.append(-12345.0)
    for i in range(len(target)):
        target[i] = -12345.0
    expected = [-12345.0] * len(target)
    for start, end in ((45, 70), (32, 48), (78, 90), (10, 20), (0, 0), (70, 63)):
        if indicator_type in (bt.ind.SumN, bt.ind.AnyN, bt.ind.AllN):
            if start < end:
                for i in range(start, end):
                    if i < period - 1 or i >= len(source):
                        expected[i] = float("nan")
                    else:
                        window = source[i - period + 1 : i + 1]
                        func = {bt.ind.SumN: math.fsum, bt.ind.AnyN: any, bt.ind.AllN: all}[indicator_type]
                        try:
                            expected[i] = float(func(window))
                        except (ValueError, TypeError):
                            expected[i] = float("nan")
        elif indicator_type is bt.ind.SMA:
            for i in range(min(period - 1, len(source))):
                expected[i] = float("nan")
            for i in range(max(period - 1, start), min(end, len(source))):
                window = source[i - period + 1 : i + 1]
                expected[i] = float("nan") if any(v != v for v in window) else math.fsum(window) / period
        else:
            for i in range(min(period - 1, len(target), end, len(source))):
                expected[i] = float("nan")
            for i in range(period - 1, min(end, len(source))):
                window = source[i - period + 1 : i + 1]
                if any(v != v for v in window):
                    expected[i] = float("nan")
                else:
                    mean = math.fsum(window) / period
                    meansq = math.fsum(v * v for v in window) / period
                    expected[i] = math.sqrt(abs(meansq - mean * mean))
        indicator.once(start, end)
        _assert_bit_exact_sequence(list(target), expected)
