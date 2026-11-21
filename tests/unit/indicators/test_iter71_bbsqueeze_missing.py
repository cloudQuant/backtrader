"""Independent BBSqueeze values and missing-input classification."""
import math
import statistics

import numpy as np
import pandas as pd
import pytest
import backtrader as bt
from backtrader.indicators.contrib.bb_squeeze_indicator import BBSqueezeIndicator

BB, KC, MOM, DEV, MULT = 8, 7, 3, 2.0, 1.5

def frame(n=110):
    close=[100 + i*.01 + 2*math.sin(i*.23) + .2*math.cos(i*.09) for i in range(n)]
    return pd.DataFrame(dict(open=[v-.15 for v in close], high=[v+.4+(i%5)*.1 for i,v in enumerate(close)],
        low=[v-.5-(i%3)*.1 for i,v in enumerate(close)],close=close,volume=[1.]*n),
        index=pd.date_range('2024-01-01',periods=n,freq='min'))

def oracle(high,low,close):
    atrs=[math.nan]*len(close)
    tr=[math.nan]+[max(high[i],close[i-1])-min(low[i],close[i-1]) for i in range(1,len(close))]
    if len(close)>KC:
        atrs[KC]=sum(tr[1:KC+1])/KC
        for i in range(KC+1,len(close)):
            atrs[i]=atrs[i-1]*(1-1/KC)+tr[i]/KC
    out=[]
    for i in range(max(BB-1,KC,MOM),len(close)):
        vals=close[i-BB+1:i+1]
        mid=sum(vals)/BB
        sd=statistics.pstdev(vals)
        top=mid+DEV*sd; bot=mid-DEV*sd
        sma=sum(close[i-KC+1:i+1])/KC
        kup=sma+MULT*atrs[i]; klo=sma-MULT*atrs[i]
        out.append((i+1,1. if top-bot < kup-klo else -1.,close[i]-close[i-MOM]))
    return out

def run(f, mode=False, replay=False, kc_mult=MULT):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind=BBSqueezeIndicator(self.data,bb_period=BB,kc_period=KC,mom_period=MOM,kc_mult=kc_mult)
            self.rows=[]
        def next(self):
            i=self.ind
            self.rows.append((len(self.data),float(i.bb.top[0]),float(i.bb.bot[0]),float(i.sma[0]),
                float(i.atr[0]),float(i.squeeze[0]),float(i.momentum[0])))
    c=bt.Cerebro(stdstats=False)
    d=bt.feeds.PandasData(dataname=f,timeframe=bt.TimeFrame.Minutes)
    if replay:c.replaydata(d,timeframe=bt.TimeFrame.Minutes,compression=3)
    else:c.adddata(d)
    c.addstrategy(Probe)
    return c.run(runonce=mode,preload=True)[0].rows

@pytest.mark.parametrize('mode',[False,True])
def test_clean_formula(mode):
    f=frame(); rows=run(f,mode)
    expected=oracle(f.high.tolist(),f.low.tolist(),f.close.tolist())
    assert rows[0][0]==max(BB,KC+1,MOM+1)
    assert len(rows)==len(expected)
    assert {row[5] for row in rows}=={-1.,1.}
    for row,(n,sq,mom) in zip(rows,expected):
        assert row[0]==n and row[5]==sq
        assert row[6]==pytest.approx(mom,rel=1e-12,abs=1e-12)

@pytest.mark.parametrize('mode',[False,True])
@pytest.mark.parametrize('field',['open','high','low','close'])
def test_missing_visible_components(mode,field):
    f=frame(); f.loc[f.index[40],field]=math.nan
    rows=run(f,mode)
    invalid=[]
    for n,top,bot,sma,atr,sq,mom in rows:
        bw=top-bot; kw=(sma+MULT*atr)-(sma-MULT*atr)
        if not math.isfinite(bw) or not math.isfinite(kw):
            invalid.append(n); assert math.isnan(sq),n
        else:
            assert sq==(1. if bw<kw else -1.),n
        expected=f.close.iloc[n-1]-f.close.iloc[n-1-MOM]
        if math.isnan(expected):assert math.isnan(mom),n
        else: assert mom==pytest.approx(expected),n
    if field=='open':assert not invalid
    elif field=='close':
        assert invalid==list(range(41,49))
        assert math.isfinite(rows[-1][5])
    else:
        assert invalid==list(range(41,len(f)+1))  # Wilder ATR does not reseed

def test_replay_visible_components():
    rows=run(frame(240),replay=True)
    assert len(rows)>len({row[0] for row in rows})
    for n,top,bot,sma,atr,sq,_ in rows:
        bw=top-bot; kw=(sma+MULT*atr)-(sma-MULT*atr)
        assert sq==(1. if bw<kw else -1.),n

def test_replay_independent_aggregate_history():
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind=BBSqueezeIndicator(self.data,bb_period=BB,kc_period=KC,mom_period=MOM)
            self.rows=[]
        def next(self):
            data=self.data
            series=[[float(getattr(data,k)[-i]) for i in range(len(data)-1,-1,-1)]
                    for k in ('high','low','close')]
            expected=oracle(*series)[-1]
            self.rows.append((len(data),float(self.ind.squeeze[0]),float(self.ind.momentum[0]),expected))
    c=bt.Cerebro(stdstats=False)
    c.replaydata(bt.feeds.PandasData(dataname=frame(240),timeframe=bt.TimeFrame.Minutes),
                 timeframe=bt.TimeFrame.Minutes,compression=3)
    c.addstrategy(Probe);rows=c.run(runonce=False)[0].rows
    assert len(rows)>len(set(r[0] for r in rows))
    for n,sq,mom,expected in rows:
        assert n==expected[0] and sq==expected[1]
        assert mom==pytest.approx(expected[2],rel=1e-12,abs=1e-12)

@pytest.mark.parametrize('mode',[False,True])
def test_short_history(mode):
    assert not run(frame(max(BB,KC+1,MOM+1)-1),mode)

@pytest.mark.parametrize('mode',[False,True])
def test_nan_keltner_multiplier_is_not_signal(mode):
    rows=run(frame(),mode,kc_mult=math.nan)
    assert rows and all(math.isnan(row[5]) for row in rows)
    assert all(math.isfinite(row[6]) for row in rows)

class Multiplier:
    def __init__(self):
        self.mul_calls=0
        self.float_calls=0
    def __mul__(self, value):
        self.mul_calls+=1
        return MULT*value
    def __getattribute__(self, name):
        if name=='__class__':
            raise AssertionError('parameter class must not be dynamically inspected')
        return object.__getattribute__(self,name)
    def __float__(self):
        self.float_calls+=1
        raise AssertionError('multiplication-only parameter must not be coerced')

class DerivedFloat32(np.float32):
    def __float__(self):
        raise AssertionError('NumPy scalar subclass must not be coerced via __float__')
    def item(self):
        raise AssertionError('NumPy scalar subclass item must not be overridden')

class DerivedInfiniteFloat32(DerivedFloat32):
    def __array_ufunc__(self, *args, **kwargs):
        raise AssertionError('guard must not invoke subclass ufunc hooks')

@pytest.mark.parametrize('mode',[False,True])
def test_custom_multiplier_plain_path_is_not_coerced(mode):
    m=Multiplier(); actual=run(frame(),mode,kc_mult=m)
    expected=run(frame(),mode,kc_mult=MULT)
    assert actual==expected and m.float_calls==0 and m.mul_calls==2*len(actual)

@pytest.mark.parametrize('mode',[False,True])
@pytest.mark.parametrize('case',['mult_pos_inf','mult_neg_inf','numpy16_inf','numpy32_inf','numpy64_inf',
                                 'numpy32_subclass_pos_inf','numpy32_subclass_neg_inf','numpy32_subclass_finite',
                                 'mult_overflow','missing','high_missing','mult_nan','custom'])
def test_real_factor_strict(mode,case):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec,ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    f=frame();f.index=f.index.tz_localize('UTC')
    if case in ('mult_pos_inf','mult_neg_inf','numpy16_inf','numpy32_inf','numpy64_inf',
                'numpy32_subclass_pos_inf','numpy32_subclass_neg_inf'):
        for col in ('open','high','low','close'):f[col]=100.
    elif case=='missing':f.loc[f.index[40],'close']=math.nan
    elif case=='high_missing':f.loc[f.index[40],'high']=math.nan
    idx=f.index.rename('close_time')
    research=ResearchSpec(grid=pd.DataFrame({'open_time':idx-pd.Timedelta(minutes=1)},index=idx),
        start=idx[0],end=idx[-1],targets=('asset',),source_timezone='UTC',snapshot_id='bb-squeeze-strict',
        price_basis='synthetic',calendar_id='synthetic',frequency='1min',feed_time_kind='close_time',groups={'asset':'market'})
    values=[]; factors=[]
    class Factor(FactorIndicator):
        lines=('factor',);formula_fields=required_fields=('open','high','low','close');lookback_h=0
        def __init__(self):
            super().__init__()
            mult={'mult_pos_inf':math.inf,'mult_neg_inf':-math.inf,
                  'numpy16_inf':np.float16(math.inf),'numpy32_inf':np.float32(-math.inf),
                  'numpy64_inf':np.float64(math.inf),'mult_overflow':1e308,
                  'numpy32_subclass_pos_inf':DerivedInfiniteFloat32(math.inf),
                  'numpy32_subclass_neg_inf':DerivedInfiniteFloat32(-math.inf),
                  'numpy32_subclass_finite':DerivedFloat32(MULT),
                  'mult_nan':math.nan,'custom':Multiplier()}.get(case,MULT)
            self.ind=BBSqueezeIndicator(self.data,bb_period=BB,kc_period=KC,mom_period=MOM,kc_mult=mult)
            factors.append(self)
        def next(self):
            value=float(self.ind.squeeze[0]);values.append(value);self.outputs[self.datas[0]].factor[0]=value
    c=bt.Cerebro(stdstats=False,runonce=mode);c.adddata(align_to_grid(f,research,'asset').feed,name='asset')
    bindings={k:'feed:target:'+k for k in Factor.formula_fields}
    spec=FactorSpec(name='sq',indicator=Factor,panel_line='factor',field_bindings=bindings,mode='native')
    c.addstrategy(FactorStrategy,research=research,factors={'sq':spec})
    if case in ('missing','high_missing','mult_nan','custom','numpy32_subclass_finite'):
        c.run(preload=True);assert factors and not factors[0]._factor_strict_context.failed
        if case in ('custom','numpy32_subclass_finite'):
            m=factors[0].ind.p.kc_mult
            if case=='custom':assert m.float_calls==0 and m.mul_calls>0
            expected=oracle(f.high.tolist(),f.low.tolist(),f.close.tolist())
            prewarm=len(values)-len(expected)
            assert prewarm>=0 and all(math.isnan(v) for v in values[:prewarm])
            assert values[prewarm:]==[row[1] for row in expected]
        else:
            assert any(math.isnan(v) for v in values)
            if case=='missing':assert math.isfinite(values[-1])
            else:assert math.isnan(values[-1])
    else:
        with pytest.raises(FactorComputationError) as exc:c.run(preload=True)
        assert exc.value.code=='FACTOR_COMPUTATION_FAILED' and isinstance(exc.value.__cause__,ArithmeticError)
        assert factors and factors[0]._factor_strict_context.failed
