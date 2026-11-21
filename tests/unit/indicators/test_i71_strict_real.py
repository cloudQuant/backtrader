import math
import types

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import FactorComputationError
from backtrader.research import align_to_grid
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec, ResearchSpec
from backtrader.strategies.factor_strategy import FactorStrategy


def run_factor(mode, method, missing=False, prices=None, return_child=False, variant=None):
    n = 40
    ix = pd.date_range('2024-01-01', periods=n, freq='min', tz='UTC', name='close_time')
    v = [100 + i * .11 + math.sin(i * .7) * 3 for i in range(n)]
    frame = pd.DataFrame({
        'open': v, 'high': [x + 1 + i % 4 * .12 for i, x in enumerate(v)],
        'low': [x - 1 - i % 3 * .09 for i, x in enumerate(v)],
        'close': v, 'volume': [1.] * n, 'openinterest': [0.] * n,
    }, index=ix)
    if missing:
        for row, field in [(17, 'low'), (24, 'high'), (27, 'close')]:
            frame.loc[ix[row], field] = float('nan')
    if prices is not None:
        for field, value in prices.items():
            frame[field] = value
    research = ResearchSpec(
        grid=pd.DataFrame({'open_time': ix - pd.Timedelta(minutes=1)}, index=ix),
        start=ix[0], end=ix[-1], targets=('asset',), source_timezone='UTC',
        snapshot_id='test', price_basis='synthetic', calendar_id='synthetic',
        frequency='1min', feed_time_kind='close_time', groups={'asset': 'market'},
    )
    seen = []
    secondary = align_to_grid(frame, research, 'asset').feed if variant else None

    class CrossFeedThreshold:
        def __float__(self):
            return float(secondary.close[0])

    class CrossFeedSubclass(bt.ind.StochasticHistogramIndicator):
        alias = ()

        def next(self):
            float(secondary.close[0])
            return super().next()

    def instance_next(indicator):
        float(secondary.close[0])
        return bt.ind.StochasticHistogramIndicator.next(indicator)

    def instance_fast(indicator, index, high, low, close):
        return 30.0

    class Factor(FactorIndicator):
        lines = ('factor',)
        formula_fields = required_fields = ('high', 'low', 'close')
        lookback_h = 0

        def __init__(self):
            super().__init__()
            indicator = CrossFeedSubclass if variant == 'subclass' else bt.ind.StochasticHistogramIndicator
            threshold = CrossFeedThreshold() if variant == 'threshold' else 60
            self.child = indicator(
                self.data, k_period=3, slowing=3, d_period=3, ma_method=method,
                high_level=threshold,
            )
            if variant == 'instance_next':
                self.child.next = types.MethodType(instance_next, self.child)
            if variant == 'instance_fast':
                self.child._fast_k_at = types.MethodType(instance_fast, self.child)
            seen.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.main[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=mode == 'once')
    cerebro.adddata(align_to_grid(frame, research, 'asset').feed, name='asset')
    if secondary is not None:
        cerebro.adddata(secondary, name='clock')
    spec = FactorSpec(name='test', indicator=Factor, panel_line='factor',
                      field_bindings={k: 'feed:target:' + k for k in Factor.formula_fields},
                      mode='native')
    cerebro.addstrategy(FactorStrategy, research=research, factors={'test': spec})
    cerebro.run(preload=mode == 'once')
    if return_child:
        return seen[0].child, seen[0]._factor_strict_context
    return [list(line.array) for line in seen[0].child.lines]


@pytest.mark.parametrize('method', ['sma', 'ema', 'smma', 'lwma'])
@pytest.mark.parametrize('missing', [False, True])
def test_factor_next_once_full_series(method, missing):
    left = run_factor('next', method, missing)
    right = run_factor('once', method, missing)
    for a, b in zip(left, right):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            assert (math.isnan(x) and math.isnan(y)) or x == pytest.approx(y)


@pytest.mark.parametrize('mode', ['next', 'once'])
@pytest.mark.parametrize('prices', [
    {'high': 1e308, 'low': -1e308, 'close': 0.0},
    {'high': 0.0, 'low': -1e308, 'close': 1e308},
    {'high': 2e307, 'low': 0.0, 'close': 1e307},
    {'high': 1e-308, 'low': 0.0, 'close': 1e306},
    {'high': 1.0, 'low': 0.0, 'close': 1e306},
])
def test_factor_rejects_finite_intermediate_overflow(mode, prices):
    with pytest.raises(FactorComputationError) as caught:
        run_factor(mode, 'sma', prices=prices)
    assert isinstance(caught.value.__cause__, ArithmeticError)


def test_strict_once_restores_line_positions_on_exception():
    from backtrader.research.strict import computation_scope

    child, context = run_factor('once', 'ema', return_child=True)
    source = child.data.high
    original = source.array[12]
    source.array[12] = float('inf')
    for line in child.lines:
        for index in range(10, 15):
            line.array[index] = -123.0
    lines = list(child.data.lines) + list(child.lines)
    positions = [(line._idx, line.lencount) for line in lines]
    try:
        with pytest.raises(FactorComputationError), computation_scope(context, 'once'):
            child.once(10, 15)
    finally:
        source.array[12] = original
    assert [(line._idx, line.lencount) for line in lines] == positions
    assert child.main.array[10] != -123.0
    assert child.main.array[11] != -123.0
    assert child.main.array[12] == -123.0


def test_strict_once_preserves_subclass_batch_dispatch():
    result = run_factor('once', 'ema', variant='subclass')
    assert result[0][10] == pytest.approx(72.34216462018432)


def test_strict_once_preserves_existing_cross_feed_threshold_error():
    with pytest.raises(FactorComputationError) as caught:
        run_factor('once', 'ema', variant='threshold')
    assert isinstance(caught.value.__cause__, IndexError)


def test_strict_once_preserves_instance_next_override_dispatch():
    result = run_factor('once', 'ema', variant='instance_next')
    assert result[0][10] == pytest.approx(72.34216462018432)


def test_strict_once_preserves_instance_fast_override_dispatch():
    result = run_factor('once', 'ema', variant='instance_fast')
    assert result[0][10] == 30.0
