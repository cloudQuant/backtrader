"""Rank-style contract, visible missing data and strict overflow."""
import math
import pandas as pd
import pytest
import backtrader as bt
from backtrader.indicators.contrib.spearman_rank_correlation_histogram import SpearmanRankCorrelationHistogram

PERIOD=5

def reference(prices, direction):
    if any(math.isnan(x) for x in prices):return (math.nan,math.nan)
    q=[int(round(x*100)) for x in prices]
    ranks=[1+sum(y>x if direction else y<x for y in q)+(sum(y==x for y in q)-1)/2 for x in q]
    val=1-6*sum((rank-(i+1))**2 for i,rank in enumerate(ranks))/(len(q)**3-len(q))
    col=(4 if val>.5 else 3) if val>0 else ((0 if val<-.5 else 1) if val<0 else 2)
    return val,float(col)

def values():
    return [round(100 + math.sin(i*.48)*2 + i*.03,2) if i % 6 else 100.0 for i in range(48)]

def run(v, *, once=False, replay=False, direction=True):
    d=pd.date_range('2022-01-01',periods=len(v),freq='D')
    if replay:
        ts=[day+pd.Timedelta(hours=h) for day in d for h in (9,10)]
        p=[x for val in v for x in (val-.10,val)]
    else:ts,p=d,v
    frame=pd.DataFrame({name:p for name in ('open','high','low','close')},index=ts)
    class S(bt.Strategy):
        def __init__(self):
            self.ind=SpearmanRankCorrelationHistogram(self.data,range_n=PERIOD,direction=direction)
            self.prices=[]; self.samples=[]
        def prenext(self):self.rec()
        def nextstart(self):self.rec()
        def next(self):self.rec()
        def rec(self):
            value=float(self.data.close[0])
            if len(self.prices)==len(self.data):self.prices[-1]=value
            else:self.prices.append(value)
            self.samples.append((list(self.prices),float(self.ind.value[0]),float(self.ind.color[0])))
    c=bt.Cerebro(runonce=once,preload=not replay,stdstats=False)
    data=bt.feeds.PandasData(dataname=frame,timeframe=bt.TimeFrame.Minutes if replay else bt.TimeFrame.Days,compression=60 if replay else 1)
    if replay:c.replaydata(data,timeframe=bt.TimeFrame.Days,compression=1)
    else:c.adddata(data)
    c.addstrategy(S);return c.run()[0]

def check(a,b):
    if math.isnan(b):assert math.isnan(a)
    else:assert a==pytest.approx(b,rel=1e-12,abs=1e-12)

@pytest.mark.parametrize('once',[False,True])
@pytest.mark.parametrize('direction',[False,True])
@pytest.mark.parametrize('missing',[False,True])
def test_reference_and_visible_nan_recovery(once,direction,missing):
    data=values()
    if missing:data[20]=math.nan
    result=run(data,once=once,direction=direction)
    assert result.ind._minperiod==PERIOD+2
    for i,(v,col) in enumerate(zip(result.ind.value.array,result.ind.color.array)):
        exp=(math.nan,math.nan) if i<PERIOD+1 else reference(list(reversed(data[i-PERIOD+1:i+1])),direction)
        check(v,exp[0]);check(col,exp[1])
    assert math.isfinite(result.ind.value.array[-1])

@pytest.mark.parametrize('direction',[False,True])
def test_replay_each_revision(direction):
    result=run(values(),replay=True,direction=direction)
    assert len(result.samples)>=95
    for prices,v,c in result.samples:
        exp=(math.nan,math.nan) if len(prices)<PERIOD+2 else reference(list(reversed(prices[-PERIOD:])),direction)
        check(v,exp[0]);check(c,exp[1])

@pytest.mark.parametrize('once',[False,True])
@pytest.mark.parametrize('prior_nan',[False,True])
def test_strict_factor_intermediate_scale_overflow(once,prior_nan):
    from backtrader.errors import FactorComputationError
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames,_research_feed,_research_spec
    data=_frames(periods=25)['asset-0'].copy();data.loc[data.index[13],'close']=1e308
    if prior_nan:data.loc[data.index[12],'close']=math.nan
    research=_research_spec({'asset-0':data})
    class F(FactorIndicator):
        lines=('factor',);formula_fields=required_fields=('close',);lookback_h=0
        def __init__(self):super().__init__();self.ind=SpearmanRankCorrelationHistogram(self.data,range_n=PERIOD)
        def next(self):self.outputs[self.datas[0]].factor[0]=self.ind.value[0]
    c=bt.Cerebro(stdstats=False,runonce=once);c.adddata(_research_feed(data,research,'asset-0'),name='asset-0')
    c.addstrategy(FactorStrategy,research=research,factors={'f':FactorSpec(name='f',indicator=F,panel_line='factor',field_bindings={'close':'feed:target:close'},mode='native')})
    with pytest.raises(FactorComputationError) as error:c.run(preload=True)
    assert isinstance(error.value.__cause__, ArithmeticError)

@pytest.mark.parametrize('once',[False,True])
@pytest.mark.parametrize('positive',[False,True])
@pytest.mark.parametrize('used',[False,True],ids=['unused-infinite','used-infinite'])
def test_strict_only_reads_threshold_for_active_sign(once,positive,used):
    from backtrader.errors import FactorComputationError
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames,_research_feed,_research_spec
    data=_frames(periods=25)['asset-0'].copy();data.loc[:,'close']=[100.+i for i in range(len(data))]
    research=_research_spec({'asset-0':data})
    class F(FactorIndicator):
        lines=('factor',);formula_fields=required_fields=('close',);lookback_h=0
        def __init__(self):
            super().__init__();self.ind=SpearmanRankCorrelationHistogram(self.data,range_n=PERIOD,direction=positive,
                in_high_level=math.inf if positive==used else .5,in_low_level=math.inf if positive!=used else -.5)
        def next(self):self.outputs[self.datas[0]].factor[0]=self.ind.value[0]
    c=bt.Cerebro(stdstats=False,runonce=once);c.adddata(_research_feed(data,research,'asset-0'),name='asset-0')
    c.addstrategy(FactorStrategy,research=research,factors={'f':FactorSpec(name='f',indicator=F,panel_line='factor',field_bindings={'close':'feed:target:close'},mode='native')})
    if used:
        with pytest.raises(FactorComputationError) as error:c.run(preload=True)
        assert type(error.value.__cause__) is ArithmeticError
    else:c.run(preload=True)

@pytest.mark.parametrize('once',[False,True])
@pytest.mark.parametrize('n',[0,1])
def test_legacy_zero_denominator_unchanged(once,n):
    v=values();d=pd.date_range('2023-01-01',periods=len(v));frame=pd.DataFrame({k:v for k in ('open','high','low','close')},index=d)
    class S(bt.Strategy):
        def __init__(self):self.ind=SpearmanRankCorrelationHistogram(self.data,range_n=n)
    c=bt.Cerebro(stdstats=False,runonce=once);c.adddata(bt.feeds.PandasData(dataname=frame));c.addstrategy(S)
    with pytest.raises(ZeroDivisionError):c.run()
