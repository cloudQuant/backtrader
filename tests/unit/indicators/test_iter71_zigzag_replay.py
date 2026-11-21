"""Real Cerebro regression for ZigZag pivot state on replay revisions."""
import math
import pandas as pd
import pytest
import backtrader as bt
from backtrader.errors import FactorComputationContext, FactorComputationError


def reference(highs,lows,depth,backstep,deviation):
    last_type=0; last_price=None; latest=0; age=999999; price=0.0
    for index in range(depth+backstep+1,len(highs)):
        shift=index-backstep
        high=highs[shift]; low=lows[shift]
        high_window=[highs[shift-j] for j in range(depth)]
        low_window=[lows[shift-j] for j in range(depth)]
        pivot=1 if high>=max(high_window) else -1 if low<=min(low_window) else 0
        selected=high if pivot==1 else low if pivot==-1 else None
        if pivot and (last_price is None or (pivot!=last_type and abs(selected-last_price)>=deviation) or (pivot==last_type==1 and selected>last_price) or (pivot==last_type==-1 and selected<last_price)):
            last_type=pivot; last_price=selected; latest=pivot; age=0; price=selected
        out=(latest,age,price) if age<999999 else (0,999999,price)
        if age<999999: age+=1
    return out


def data_frame():
    idx=pd.date_range('2024-01-01 09:01',periods=240,freq='min')
    xs=[100+4*math.sin(i/8)+i*.004 for i in range(len(idx))]
    return pd.DataFrame({'open':xs,'high':[x+.3 for x in xs],'low':[x-.3 for x in xs],'close':xs,'volume':[1.0]*len(xs)},index=idx)


def run(runonce,replay,depth,backstep,strict=False,data=None,poison=False):
    class PoisonedIndicator(bt.indicators.ZigZagRecentPivotSignal):
        def next(self):
            if len(self.data)==40:
                line=self.data.high
                line.array[line.idx-1]=math.inf
            return super().next()

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind=(PoisonedIndicator if poison else bt.indicators.ZigZagRecentPivotSignal)(self.data,depth=depth,backstep=backstep,deviation=1,point=.01)
            self.ctx=FactorComputationContext('zig',phase='next') if strict else None
            if strict: self.ind._factor_strict_context=self.ctx
            self.rows=[]
        def next(self):
            n=len(self.data); h=list(self.data.high.get(size=n)); l=list(self.data.low.get(size=n))
            self.rows.append((n,tuple(float(line[0]) for line in self.ind.lines),reference(h,l,depth,backstep,.01)))
    c=bt.Cerebro(stdstats=False,runonce=runonce,preload=not replay)
    feed=bt.feeds.PandasData(dataname=data_frame() if data is None else data,timeframe=bt.TimeFrame.Minutes)
    if replay:c.replaydata(feed,timeframe=bt.TimeFrame.Minutes,compression=5)
    else:c.adddata(feed)
    c.addstrategy(Probe)
    return c.run()[0]


@pytest.mark.parametrize('runonce',[False,True])
@pytest.mark.parametrize('depth,backstep',[(1,0),(3,0),(3,1),(5,3)])
@pytest.mark.parametrize('strict',[False,True])
def test_replay_each_revision_matches_recomputed_history(runonce,depth,backstep,strict):
    s=run(runonce,True,depth,backstep,strict)
    assert any(a[0]==b[0] for a,b in zip(s.rows,s.rows[1:]))
    assert s.ctx is None or not s.ctx.failed
    for length,actual,expected in s.rows: assert actual==expected,(length,actual,expected)


@pytest.mark.parametrize('runonce',[False,True])
@pytest.mark.parametrize('depth,backstep',[(1,0),(3,1),(5,3)])
@pytest.mark.parametrize('strict',[False,True])
def test_normal_each_bar_matches_independent_state_machine(runonce,depth,backstep,strict):
    s=run(runonce,False,depth,backstep,strict)
    assert s.ctx is None or not s.ctx.failed
    for length,actual,expected in s.rows: assert actual==expected,(length,actual,expected)


@pytest.mark.parametrize('runonce',[False,True])
def test_strict_invalid_feed_input_still_fails(runonce):
    with pytest.raises(FactorComputationError):run(runonce,False,3,1,True,poison=True)


@pytest.mark.parametrize('runonce',[False,True])
@pytest.mark.parametrize('backstep',[0,1])
def test_multifeed_unchanged_secondary_matches_its_own_history(runonce,backstep):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind=bt.indicators.ZigZagRecentPivotSignal(self.datas[1],depth=3,backstep=backstep,deviation=1,point=.01)
            self.rows=[]
        def next(self):
            d=self.datas[1]; n=len(d)
            h=list(d.high.get(size=n)); l=list(d.low.get(size=n))
            self.rows.append((n,tuple(float(line[0]) for line in self.ind.lines),reference(h,l,3,backstep,.01)))
    source=data_frame()
    c=bt.Cerebro(stdstats=False,runonce=runonce,preload=True)
    c.adddata(bt.feeds.PandasData(dataname=source,timeframe=bt.TimeFrame.Minutes))
    c.adddata(bt.feeds.PandasData(dataname=source.iloc[::3].copy(),timeframe=bt.TimeFrame.Minutes,compression=3))
    c.addstrategy(Probe); rows=c.run()[0].rows
    assert any(a[0]==b[0] for a,b in zip(rows,rows[1:]))
    for length,actual,expected in rows: assert actual==expected,(length,actual,expected)

@pytest.mark.parametrize('runonce',[False,True])
@pytest.mark.parametrize('poison',[False,True])
def test_real_factor_strategy_preserves_strict_feed_error(runonce,poison):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec,ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    data=data_frame().iloc[:60].copy()
    idx=data.index.tz_localize('UTC'); data.index=idx; data.index.name='close_time'
    research=ResearchSpec(grid=pd.DataFrame({'open_time':idx-pd.Timedelta(minutes=1)},index=idx),start=idx[0],end=idx[-1],targets=('asset',),source_timezone='UTC',snapshot_id='zigzag-test',price_basis='synthetic',calendar_id='synthetic',frequency='1min',feed_time_kind='close_time',groups={'asset':'market'})
    seen=[]
    class Poisoned(bt.indicators.ZigZagRecentPivotSignal):
        def next(self):
            if len(self.data)==40:
                line=self.data.high
                line.array[line.idx-1]=math.inf
            return super().next()
    class Factor(FactorIndicator):
        lines=('factor',);formula_fields=required_fields=('high','low');lookback_h=0
        def __init__(self):
            super().__init__()
            cls=Poisoned if poison else bt.indicators.ZigZagRecentPivotSignal
            self.child=cls(self.data,depth=3,backstep=1,deviation=1,point=.01)
            seen.append(self)
        def next(self):self.outputs[self.datas[0]].factor[0]=self.child.pivot_age[0]
    c=bt.Cerebro(stdstats=False,runonce=runonce)
    c.adddata(align_to_grid(data,research,'asset').feed,name='asset')
    spec=FactorSpec(name='zig',indicator=Factor,panel_line='factor',field_bindings={'high':'feed:target:high','low':'feed:target:low'},mode='native')
    c.addstrategy(FactorStrategy,research=research,factors={'zig':spec})
    if poison:
        with pytest.raises(FactorComputationError):c.run(preload=True)
        assert seen and seen[0]._factor_strict_context.failed
    else:
        c.run(preload=True)
        assert seen and not seen[0]._factor_strict_context.failed
