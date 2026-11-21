import math

import backtrader as bt
import pandas as pd
import pytest


def prices(n=60, missing=None):
    index = pd.date_range('2024-01-01', periods=n, freq='min')
    closes = [100 + 0.12 * i + 1.6 * math.sin(i * 0.8) for i in range(n)]
    opens = [c + (-.8 if i % 3 == 0 else .8) for i, c in enumerate(closes)]
    frame = pd.DataFrame({
        'open': opens, 'high': [max(o, c) + 1 for o, c in zip(opens, closes)],
        'low': [min(o, c) - 1 for o, c in zip(opens, closes)], 'close': closes,
        'volume': [1.] * n, 'openinterest': [0.] * n,
    }, index=index)
    if missing:
        field, row = missing
        frame.loc[index[row], field] = float('nan')
    return frame


def calc(frame, period, gap):
    n = len(frame)
    out = [[float('nan')] * n for _ in range(3)]
    tr = [float('nan')]
    for i in range(1, n):
        high, low, prev = frame.high.iloc[i], frame.low.iloc[i], frame.close.iloc[i - 1]
        tr.append(max(high, prev) - min(low, prev))
    if n <= period:
        return out
    atr = sum(tr[1:period + 1]) / period
    for i in range(period, n):
        if i > period:
            atr = atr * (1.0 - 1.0 / period) + tr[i] / period
        if i < period + gap + 3:
            continue
        before, opening = frame.close.iloc[i - 1], frame.open.iloc[i]
        out[2][i] = atr
        if math.isnan(before) or math.isnan(opening):
            out[0][i] = out[1][i] = float('nan')
        else:
            out[0][i] = frame.high.iloc[i] + atr * 3.0 / 8.0 if before < opening - gap * .01 else 0.0
            out[1][i] = frame.low.iloc[i] - atr * 3.0 / 8.0 if before > opening + gap * .01 else 0.0
    return out


def run(frame, period, gap, runonce):
    seen = []

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.IGapIndicator(self.data, atr_period=period, size_gap=gap, point=.01)
            seen.append(self.ind)

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    cerebro.run()
    return seen[0]


@pytest.mark.parametrize('runonce', [False, True])
@pytest.mark.parametrize('period,gap', [(2, 1), (3, 2), (7, 5)])
@pytest.mark.parametrize('missing', [None, ('open', 30), ('close', 30)])
def test_formula_minperiod_and_missing(runonce, period, gap, missing):
    frame = prices(missing=missing)
    indicator = run(frame, period, gap, runonce)
    assert indicator._minperiod == period + gap + 4
    for line, expected in zip(indicator.lines, calc(frame, period, gap)):
        for actual, value in zip(line.array, expected):
            assert (math.isnan(actual) and math.isnan(value)) or actual == pytest.approx(value)


@pytest.mark.parametrize('runonce', [False, True])
def test_short_input_not_ready(runonce):
    indicator = run(prices(n=8), 3, 2, runonce)
    assert indicator._minperiod == 9
    assert all(math.isnan(v) for line in indicator.lines for v in line.array)


@pytest.mark.parametrize('runonce', [False, True])
@pytest.mark.parametrize('field,row,signal_index', [('open', 30, 30), ('close', 30, 31)])
def test_factor_strategy_observes_missing_gap(runonce, field, row, signal_index):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    frame = prices(missing=(field, row))
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
        formula_fields = required_fields = ('open', 'high', 'low', 'close')
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.ind.IGapIndicator(self.data, atr_period=3, size_gap=2, point=.01)
            seen.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.buy_signal[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=runonce)
    cerebro.adddata(align_to_grid(frame, research, 'asset').feed, name='asset')
    spec = FactorSpec(name='test', indicator=Factor, panel_line='factor',
                      field_bindings={k: 'feed:target:' + k for k in Factor.formula_fields},
                      mode='native')
    cerebro.addstrategy(FactorStrategy, research=research, factors={'test': spec})
    cerebro.run()
    indicator = seen[0].child
    assert math.isnan(indicator.buy_signal.array[signal_index])
    assert math.isnan(indicator.sell_signal.array[signal_index])
    assert not seen[0]._factor_strict_context.failed
