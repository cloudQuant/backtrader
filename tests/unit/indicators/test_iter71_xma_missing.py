import math

import backtrader as bt
import pandas as pd
import pytest


def data(missing=None):
    n = 75
    idx = pd.date_range('2024-01-01', periods=n, freq='min')
    close = [100 + math.sin(i * .4) * 3 + .02 * i for i in range(n)]
    frame = pd.DataFrame({'open': close, 'high': [x + 1 for x in close],
                          'low': [x - 1 for x in close], 'close': close,
                          'volume': [1.] * n, 'openinterest': [0.] * n}, index=idx)
    if missing:
        frame.loc[idx[30], missing] = math.nan
    return frame


def reference(frame, window, length):
    result = [math.nan] * len(frame)
    raw = []
    first = window + length + 4
    for i in range(first, len(frame)):
        high = list(frame.high.iloc[i - window + 1:i + 1])
        low = list(frame.low.iloc[i - window + 1:i + 1])
        raw.append(math.nan if any(math.isnan(x) for x in high + low) else (max(high) + min(low)) / 2)
        tail = raw[-length:]
        result[i] = sum(tail) / length if len(tail) == length else raw[-1]
    return result


def run(frame, once):
    seen = []
    class S(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.TwoXmaIchimokuOscillator(
                self.data, up_period1=3, dn_period1=3, up_period2=4, dn_period2=4,
                x_length1=2, x_length2=4, point=1.0)
            seen.append(self.ind)
    c = bt.Cerebro(stdstats=False, runonce=once, preload=once)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(S)
    c.run()
    return seen[0]


@pytest.mark.parametrize('once', [False, True])
@pytest.mark.parametrize('missing', [None, 'high', 'low'])
def test_two_xma_formula_and_missing(once, missing):
    frame = data(missing)
    ind = run(frame, once)
    a = reference(frame, 3, 2)
    b = reference(frame, 4, 4)
    assert ind.xma1._minperiod == 10
    assert ind.xma2._minperiod == 13
    assert ind._minperiod == 13
    for child, expected in [(ind.xma1, a), (ind.xma2, b)]:
        assert len(child.array) == len(frame)
        for x, y in zip(child.array, expected):
            assert (math.isnan(x) and math.isnan(y)) or x == pytest.approx(y)
    for i in range(12, len(frame)):
        x, y = ind.line.array[i], a[i] - b[i]
        assert (math.isnan(x) and math.isnan(y)) or x == pytest.approx(y)
        if math.isnan(y) or (i > 12 and math.isnan(a[i - 1] - b[i - 1])):
            assert math.isnan(ind.color.array[i])


@pytest.mark.parametrize('once', [False, True])
@pytest.mark.parametrize('protect', [False, True])
def test_real_strategy_retains_prior_color_exit_and_protective_stop(once, protect):
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / 'functional/strategies/mean_reversion/test_0122_0389_exp_2xma_ichimoku_oscillator.py'
    spec = importlib.util.spec_from_file_location('xma_real_strategy', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    observed = []

    class S(module.Exp2XmaIchimokuOscillatorStrategy):
        def _prepare_entry_levels(self, *args, **kwargs):
            observed.append(('entry', len(self.data1) - 1))
            return super()._prepare_entry_levels(*args, **kwargs)

        def _check_exit_levels(self):
            result = super()._check_exit_levels()
            if self.order is not None:
                observed.append(('protective_exit', len(self.data1) - 1))
            return result

        def close(self, *args, **kwargs):
            observed.append(('close', len(self.data1) - 1))
            return super().close(*args, **kwargs)

        def next(self):
            index = len(self.data1) - 1
            if index == 30:
                observed.append(('state', self.position.size, float(self.osc.color[0]),
                                 float(self.osc.color[-1])))
                if protect:
                    self.stop_price = 0.0
            super().next()
            if index == 29:
                self.sell(size=.1)

    c = bt.Cerebro(stdstats=False, runonce=once, preload=once)
    c.broker.setcash(1_000_000)
    c.adddata(bt.feeds.PandasData(dataname=data()))
    c.adddata(bt.feeds.PandasData(dataname=data('high')))
    c.addstrategy(S, up_period1=3, dn_period1=3, up_period2=4, dn_period2=4,
                  x_length1=2, x_length2=4, point=1.0, signal_bar=0,
                  buy_pos_open=False, sell_pos_open=False, sell_pos_close=True)
    c.run()
    state = next(x for x in observed if x[0] == 'state')
    assert state[1] == pytest.approx(-.1)
    assert math.isnan(state[2]) and state[3] == 3.0
    assert ('close', 30) in observed
    assert (('protective_exit', 30) in observed) == protect
    assert ('entry', 30) not in observed


@pytest.mark.parametrize('once', [False, True])
def test_strict_factor_preserves_nan_and_recovers(once):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    frame = data('high')
    index = frame.index.tz_localize('UTC').rename('close_time')
    frame.index = index
    research = ResearchSpec(grid=pd.DataFrame({'open_time': index - pd.Timedelta(minutes=1)}, index=index),
                            start=index[0], end=index[-1], targets=('asset',), source_timezone='UTC',
                            snapshot_id='test', price_basis='synthetic', calendar_id='synthetic',
                            frequency='1min', feed_time_kind='close_time', groups={'asset': 'market'})
    seen = []
    class Factor(FactorIndicator):
        lines = ('factor',)
        formula_fields = required_fields = ('high', 'low')
        lookback_h = 0
        def __init__(self):
            super().__init__()
            self.child = bt.ind.TwoXmaIchimokuOscillator(
                self.data, up_period1=3, dn_period1=3, up_period2=4, dn_period2=4,
                x_length1=2, x_length2=4, point=1.0)
            seen.append(self)
        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.line[0]

    c = bt.Cerebro(stdstats=False, runonce=once, preload=once)
    c.adddata(align_to_grid(frame, research, 'asset').feed, name='asset')
    spec = FactorSpec(name='test', indicator=Factor, panel_line='factor', mode='native',
                      field_bindings={k: 'feed:target:' + k for k in Factor.formula_fields})
    c.addstrategy(FactorStrategy, research=research, factors={'test': spec})
    c.run()
    assert math.isnan(seen[0].child.line.array[31])
    assert math.isnan(seen[0].child.color.array[31])
    assert math.isfinite(seen[0].child.line.array[38])
    assert not seen[0]._factor_strict_context.failed


@pytest.mark.parametrize('once', [False, True])
def test_custom_series_value_does_not_require_float_conversion(once):
    class Number:
        def __init__(self, value):
            self.value = value

        def __lt__(self, other):
            return self.value < other.value

        def __gt__(self, other):
            return self.value > other.value

        def __add__(self, other):
            return self.value + other.value

        def __float__(self):
            raise RuntimeError('unexpected number conversion')

    class Custom(bt.ind.XmaIchimoku):
        def _series_value(self, mode, ago):
            return Number(100.0 + ago)

    seen = []
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = Custom(self.data, up_period=3, dn_period=3, x_length=2)
            seen.append(self.ind)

    c = bt.Cerebro(stdstats=False, runonce=once, preload=once)
    c.adddata(bt.feeds.PandasData(dataname=data()))
    c.addstrategy(Strategy)
    c.run()
    assert seen[0][0] == 99.0


@pytest.mark.parametrize('once', [False, True])
@pytest.mark.parametrize('kind', ['xma', 'oscillator'])
def test_existing_math_isnan_binding_is_not_used_for_finite_values(once, kind):
    def forbidden(value):
        raise RuntimeError('unexpected dynamic isnan call')

    class CustomXma(bt.ind.XmaIchimoku):
        def next(self):
            original = math.isnan
            math.isnan = forbidden
            try:
                return super().next()
            finally:
                math.isnan = original

    class CustomOsc(bt.ind.TwoXmaIchimokuOscillator):
        def next(self):
            original = math.isnan
            math.isnan = forbidden
            try:
                return super().next()
            finally:
                math.isnan = original

    seen = []
    class Strategy(bt.Strategy):
        def __init__(self):
            if kind == 'xma':
                self.ind = CustomXma(self.data, up_period=3, dn_period=3, x_length=2)
            else:
                self.ind = CustomOsc(self.data, up_period1=3, dn_period1=3,
                                     up_period2=4, dn_period2=4, x_length1=2, x_length2=4)
            seen.append(self.ind)

    c = bt.Cerebro(stdstats=False, runonce=once, preload=once)
    c.adddata(bt.feeds.PandasData(dataname=data()))
    c.addstrategy(Strategy)
    c.run()
    assert math.isfinite(seen[0][0])


@pytest.mark.parametrize('once', [False, True])
def test_oscillator_does_not_read_length_twice_in_next(once):
    class Custom(bt.ind.TwoXmaIchimokuOscillator):
        def __len__(self):
            if getattr(self, '_checklen', False):
                self._numlen += 1
                if self._numlen > 1:
                    raise RuntimeError('unexpected second len in next')
            return super().__len__()

        def next(self):
            self._numlen = 0
            self._checklen = True
            try:
                return super().next()
            finally:
                self._checklen = False

    seen = []
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = Custom(self.data, up_period1=3, dn_period1=3,
                              up_period2=4, dn_period2=4, x_length1=2, x_length2=4)
            seen.append(self.ind)

    c = bt.Cerebro(stdstats=False, runonce=once, preload=once)
    c.adddata(bt.feeds.PandasData(dataname=data()))
    c.addstrategy(Strategy)
    c.run()
    assert math.isfinite(seen[0].color[0])


@pytest.mark.parametrize('once', [False, True])
@pytest.mark.parametrize('integer', [False, True])
def test_long_wip_window_missing_and_recovery(once, integer):
    n = 440
    index = pd.date_range('2024-01-01', periods=n, freq='min')
    values = [float(i % 21 + 90) if integer else 90.3 + .13 * (i % 21) for i in range(n)]
    frame = pd.DataFrame({'open': values, 'high': values, 'low': values, 'close': values,
                          'volume': [1.] * n, 'openinterest': [0.] * n}, index=index)
    frame.loc[index[270], 'high'] = math.nan
    seen = []

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.XmaIchimoku(self.data, up_period=1, dn_period=1, x_length=128)
            seen.append(self.ind)

    c = bt.Cerebro(stdstats=False, runonce=once, preload=once)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Strategy)
    c.run()
    ind = seen[0]
    assert ind._minperiod == 134
    raw = []
    expected = [math.nan] * 133
    for i in range(133, n):
        raw.append(math.nan if i == 270 else values[i])
        tail = raw[-128:]
        expected.append(sum(tail) / 128 if len(tail) == 128 else raw[-1])
    for x, y in zip(ind.array, expected):
        assert (math.isnan(x) and math.isnan(y)) or x == pytest.approx(y, abs=1e-12)
    assert math.isnan(ind.array[397]) and math.isfinite(ind.array[398])
