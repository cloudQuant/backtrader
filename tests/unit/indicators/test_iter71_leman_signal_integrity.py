import math

import backtrader as bt
import pandas as pd
import pytest


def fixture(size=40, missing=None):
    dates = pd.date_range('2024-01-01', periods=size, freq='min')
    center = [100 + math.sin(i * .7) * 4 + i * .02 for i in range(size)]
    result = pd.DataFrame({
        'open': center,
        'high': [x + 1.0 + (i % 3) * .2 for i, x in enumerate(center)],
        'low': [x - 1.0 - (i % 5) * .2 for i, x in enumerate(center)],
        'close': center,
        'volume': [1.0] * size,
        'openinterest': [0.0] * size,
    }, index=dates)
    if missing is not None:
        field, row = missing
        result.loc[dates[row], field] = float('nan')
    return result


def reference(frame, period, point):
    high, low = list(frame.high), list(frame.low)
    buy, sell = [], []
    for index in range(len(frame)):
        if index < 2 * period + 2:
            buy.append(float('nan'))
            sell.append(float('nan'))
            continue
        highs = high[index - 2 * period - 1:index]
        lows = low[index - 2 * period - 1:index]
        h1 = highs[-period:]
        h2 = highs[-2 * period:-period]
        h3 = highs[-period - 1:-1]
        h4 = highs[:period]
        l1 = lows[-period:]
        l2 = lows[-2 * period:-period]
        l3 = lows[-period - 1:-1]
        l4 = lows[:period]
        if any(math.isnan(x) for x in highs):
            buy.append(float('nan'))
        else:
            buy.append(high[index - 1] + point if max(h3) <= max(h4) and max(h1) > max(h2) else 0.0)
        if any(math.isnan(x) for x in lows):
            sell.append(float('nan'))
        else:
            sell.append(low[index - 1] - point if min(l3) >= min(l4) and min(l1) < min(l2) else 0.0)
    return buy, sell


def run(frame, period, runonce):
    seen = []

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.LeManSignalIndicator(self.data, lperiod=period, point=.01)
            seen.append(self.ind)

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    cerebro.run()
    return seen[0]


@pytest.mark.parametrize('runonce', [False, True])
@pytest.mark.parametrize('period', [1, 3, 5])
@pytest.mark.parametrize('missing', [None, ('high', 15), ('low', 15)])
def test_formula_and_minperiod(runonce, period, missing):
    frame = fixture(missing=missing)
    indicator = run(frame, period, runonce)
    assert indicator._minperiod == 2 * period + 3
    for actual, expected in zip(indicator.lines, reference(frame, period, .01)):
        values = list(actual.array)
        assert len(values) == len(expected)
        for actual_value, expected_value in zip(values, expected):
            assert (math.isnan(actual_value) and math.isnan(expected_value)) or actual_value == pytest.approx(expected_value)


@pytest.mark.parametrize('runonce', [False, True])
def test_short_input_remains_unready(runonce):
    indicator = run(fixture(size=8), 3, runonce)
    assert indicator._minperiod == 9
    assert all(math.isnan(value) for line in indicator.lines for value in line.array)


@pytest.mark.parametrize('runonce', [False, True])
@pytest.mark.parametrize('field,row,output_index,line', [
    ('high', 5, 11, 'buy_arrow'),
    ('low', 8, 15, 'sell_arrow'),
])
def test_missing_window_does_not_produce_an_arrow(runonce, field, row, output_index, line):
    indicator = run(fixture(missing=(field, row)), 3, runonce)
    assert math.isnan(getattr(indicator.lines, line).array[output_index])


@pytest.mark.parametrize('runonce', [False, True])
def test_strict_factor_propagates_missing_high(runonce):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    frame = fixture(missing=('high', 15))
    index = frame.index.tz_localize('UTC').rename('close_time')
    frame.index = index
    research = ResearchSpec(
        grid=pd.DataFrame({'open_time': index - pd.Timedelta(minutes=1)}, index=index),
        start=index[0], end=index[-1], targets=('asset',), source_timezone='UTC',
        snapshot_id='test', price_basis='synthetic', calendar_id='synthetic',
        frequency='1min', feed_time_kind='close_time', groups={'asset': 'market'},
    )
    seen = []

    class Factor(FactorIndicator):
        lines = ('factor',)
        formula_fields = required_fields = ('high', 'low')
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.ind.LeManSignalIndicator(self.data, lperiod=3, point=.01)
            seen.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.buy_arrow[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=runonce)
    cerebro.adddata(align_to_grid(frame, research, 'asset').feed, name='asset')
    spec = FactorSpec(name='test', indicator=Factor, panel_line='factor',
                      field_bindings={k: 'feed:target:' + k for k in Factor.formula_fields},
                      mode='native')
    cerebro.addstrategy(FactorStrategy, research=research, factors={'test': spec})
    cerebro.run()
    assert all(math.isnan(seen[0].child.buy_arrow.array[i]) for i in range(16, 23))
    assert math.isfinite(seen[0].child.buy_arrow.array[23])
    assert not seen[0]._factor_strict_context.failed
