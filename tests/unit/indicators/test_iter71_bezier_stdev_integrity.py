"""Independent Bezier window and missing-value behavior under Cerebro."""

import math
import statistics
import pandas as pd
import pytest
import backtrader as bt
from backtrader.indicators.contrib.bezier_st_dev_indicator import BezierStDevIndicator

BP, SP = 4, 5

def frame(n=90):
    close = [100 + i * .13 + math.sin(i * .27) * 3 + math.cos(i * .11) for i in range(n)]
    return pd.DataFrame({"open":[v + .3 for v in close], "high":[v + 1.1 for v in close],
                         "low":[v - 1.1 for v in close], "close":close, "volume":[1.] * n},
                        index=pd.date_range('2024-01-01', periods=n, freq='min'))

def reference(prices):
    coeff = [math.comb(BP, i) * .5 ** BP for i in range(BP + 1)]
    bz = [sum(prices[k+i] * coeff[i] for i in range(BP+1)) for k in range(SP+1)]
    now, prev = bz[:2]
    color = (1. if now > prev else 2. if now < prev else 0.) if math.isfinite(now) and math.isfinite(prev) else math.nan
    ds = [bz[i] - bz[i+1] for i in range(SP)]
    if not all(math.isfinite(x) for x in ds):
        return now, color, math.nan, math.nan
    lim = 2. * statistics.pstdev(ds)
    return now, color, now if ds[0] < -lim else 0., now if ds[0] > lim else 0.

def run(f, mode=False, replay=False, ipc=0):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = BezierStDevIndicator(self.data, bperiod=BP, std_period=SP, ipc=ipc)
            self.rows=[]
        def next(self):
            ds=self.data
            prices=[]
            for i in range(BP+SP+1):
                o,h,l,c = [float(getattr(ds,name)[-i]) for name in ('open','high','low','close')]
                prices.append((c, o, h, l, (h+l)/2., (h+l+c)/3., (h+l+c+c)/4.)[ipc])
            self.rows.append((len(ds), prices, *(float(x[0]) for x in (self.ind.bezier,self.ind.color,self.ind.bears,self.ind.bulls))))
    c=bt.Cerebro(stdstats=False)
    d=bt.feeds.PandasData(dataname=f,timeframe=bt.TimeFrame.Minutes)
    if replay: c.replaydata(d,timeframe=bt.TimeFrame.Minutes,compression=3)
    else: c.adddata(d)
    c.addstrategy(Probe)
    return c.run(runonce=mode,preload=True)[0].rows

@pytest.mark.parametrize('mode',[False,True])
@pytest.mark.parametrize('ipc',range(7))
def test_valid(mode,ipc):
    rows=run(frame(),mode,ipc=ipc)
    assert rows[0][0] == BP + SP + 3
    for n,prices,*vals in rows:
        assert vals == pytest.approx(reference(prices), rel=1e-10,abs=1e-10), n


@pytest.mark.parametrize('mode',[False,True])
def test_short_history_has_no_mature_callback(mode):
    assert not run(frame(BP + SP + 2),mode)

@pytest.mark.parametrize('mode',[False,True])
@pytest.mark.parametrize('ipc',range(7))
@pytest.mark.parametrize('field',['open','high','low','close'])
def test_nan(mode,ipc,field):
    f=frame(); f.loc[f.index[40],field]=math.nan
    rows=run(f,mode,ipc=ipc)
    for n,prices,*vals in rows:
        for actual,want in zip(vals,reference(prices)):
            if math.isnan(want):
                assert math.isnan(actual), (n, actual, want)
            else:
                assert actual == pytest.approx(want, rel=1e-10, abs=1e-10), n
    assert all(math.isfinite(value) for value in rows[-1][2:])
    selected = {0: {'close'}, 1: {'open'}, 2: {'high'}, 3: {'low'},
                4: {'high','low'}, 5: {'high','low','close'}, 6: {'high','low','close'}}[ipc]
    if field in selected:
        # Each output has its own dependency window: curve (5), color (6),
        # and derivative filters (10). The first later clean bar recovers.
        for n, _, curve, color, bears, bulls in rows:
            assert math.isnan(curve) == (41 <= n <= 45), n
            assert math.isnan(color) == (41 <= n <= 46), n
            assert math.isnan(bears) == (41 <= n <= 50), n
            assert math.isnan(bulls) == (41 <= n <= 50), n

def test_replay():
    rows=run(frame(240),replay=True)
    assert len(rows)>len({row[0] for row in rows})
    for n,prices,*vals in rows:
        assert vals == pytest.approx(reference(prices),rel=1e-10,abs=1e-10), n


def test_replay_visible_missing_window_and_recovery():
    f=frame(240)
    f.loc[f.index[150],'close']=math.nan
    rows=run(f,replay=True)
    saw_missing=False
    for n,prices,*vals in rows:
        for actual,want in zip(vals,reference(prices)):
            if math.isnan(want):
                saw_missing=True
                assert math.isnan(actual), (n, actual, want)
            else:
                assert actual == pytest.approx(want,rel=1e-10,abs=1e-10), n
    assert saw_missing
    assert all(math.isfinite(value) for value in rows[-1][2:])


@pytest.mark.parametrize('mode',[False,True])
@pytest.mark.parametrize('case',['price_sum','alternating_price_sum','zero_weight', 'variance_power', 'infinite_t', 'infinite_dk', 'missing'])
def test_strict_factor_overflow_and_missing(mode,case):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    f=frame(90)
    f.index=f.index.tz_localize('UTC')
    if case in ('price_sum','alternating_price_sum'):
        for name in ('open','high','low','close'):
            f[name] = [1e308 if case=='price_sum' or i % 2 else -1e308 for i in range(len(f))]
    elif case == 'zero_weight':
        f['close'] = 1e308
    elif case == 'variance_power':
        f['close'] = [1e200 if i % 2 else -1e200 for i in range(len(f))]
    elif case == 'missing':
        f.loc[f.index[40],'close'] = math.nan
    index=f.index.rename('close_time')
    research=ResearchSpec(grid=pd.DataFrame({'open_time':index-pd.Timedelta(minutes=1)},index=index),
        start=index[0], end=index[-1], targets=('asset',), source_timezone='UTC',
        snapshot_id='bezier-strict-test', price_basis='synthetic', calendar_id='synthetic',
        frequency='1min', feed_time_kind='close_time', groups={'asset':'market'})
    seen, values = [], []
    class Factor(FactorIndicator):
        lines=('factor',)
        formula_fields=required_fields=('open','high','low','close')
        lookback_h=0
        def __init__(self):
            super().__init__()
            self.child=BezierStDevIndicator(self.data, bperiod=BP, std_period=SP,
                ipc=6 if case in ('price_sum','alternating_price_sum') else 0,
                t_param=math.inf if case=='infinite_t' else (0.0 if case in ('zero_weight','variance_power') else 0.5),
                dk=math.inf if case=='infinite_dk' else 2.0)
            seen.append(self)
        def next(self):
            value=float(self.child.bulls[0])
            values.append(value)
            self.outputs[self.datas[0]].factor[0]=value
    c=bt.Cerebro(stdstats=False,runonce=mode)
    c.adddata(align_to_grid(f,research,'asset').feed,name='asset')
    bindings={field:'feed:target:'+field for field in Factor.formula_fields}
    spec=FactorSpec(name='bezier',indicator=Factor,panel_line='factor',field_bindings=bindings,mode='native')
    c.addstrategy(FactorStrategy,research=research,factors={'bezier':spec})
    if case=='missing':
        c.run(preload=True)
        assert seen and not seen[0]._factor_strict_context.failed
        assert any(math.isnan(value) for value in values)
        assert math.isfinite(values[-1])
    else:
        with pytest.raises(FactorComputationError) as caught:
            c.run(preload=True)
        assert caught.value.code=='FACTOR_COMPUTATION_FAILED'
        assert isinstance(caught.value.__cause__, ArithmeticError)
        assert seen and seen[0]._factor_strict_context.failed
