"""DerivativeIndicator DeMark missing-data and strict numeric regression."""
import math

import backtrader as bt
import pandas as pd
import pytest


def _frame(missing=None):
    count = 50
    opens = [100. + (i % 7) for i in range(count)]
    closes = [op + (1.0 if i % 3 == 0 else -1.0 if i % 3 == 1 else 0.0)
              for i, op in enumerate(opens)]
    frame = pd.DataFrame({"open": opens, "close": closes,
                          "high": [max(o, c) + 2 for o, c in zip(opens, closes)],
                          "low": [min(o, c) - 2 for o, c in zip(opens, closes)],
                          "volume": [10.] * count, "openinterest": [0.] * count},
                         index=pd.date_range('2024-01-02 09:00', periods=count, freq='min'))
    if missing:
        frame.iloc[19:21, frame.columns.get_loc(missing)] = math.nan
    return frame


def _run(frame, mode, execution):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind=bt.indicators.DerivativeIndicator(self.data, i_slowing=3, applied_price=mode)
            self.rows=[]
        def next(self):
            self.rows.append((len(self.data),
                              tuple(float(getattr(self.data, f)[0]) for f in ('open','high','low','close')),
                              tuple(float(getattr(self.data, f)[-3]) for f in ('open','high','low','close')),
                              float(self.ind.value[0])))
    replay=execution=='replay'
    engine=bt.Cerebro(stdstats=False,runonce=execution=='once',preload=not replay)
    data=bt.feeds.PandasData(dataname=frame,timeframe=bt.TimeFrame.Minutes)
    if replay: engine.replaydata(data,timeframe=bt.TimeFrame.Minutes,compression=2)
    else: engine.adddata(data)
    engine.addstrategy(Probe)
    return engine.run()[0].rows


def _price(row, mode):
    op,high,low,close=row
    if mode in (10,11):
        if not math.isfinite(op) or not math.isfinite(close): return math.nan
        if close>op: return high if mode==10 else (high+close)/2.
        if close<op: return low if mode==10 else (low+close)/2.
        return close
    if mode==0: return close
    if mode==1: return op
    if mode==2: return high
    if mode==3: return low
    if mode==4: return (high+low)/2.
    if mode==5: return (close+high+low)/3.
    if mode==6: return (2.*close+high+low)/4.
    if mode==8: return (op+close)/2.
    if mode==9: return (op+close+high+low)/4.
    raise AssertionError(mode)


def _verify(rows,mode):
    assert rows
    for bar,current,past,actual in rows:
        expected=100.*(_price(current,mode)-_price(past,mode))/3.
        if math.isnan(expected): assert math.isnan(actual),(bar,current,past,actual)
        else: assert actual==pytest.approx(expected),(bar,current,past,actual,expected)


@pytest.mark.parametrize('execution',['next','once','replay'])
@pytest.mark.parametrize('mode',[10,11])
def test_missing_open_unknown_now_and_at_lag_then_recovers(mode,execution):
    rows=_run(_frame('open'),mode,execution)
    _verify(rows,mode)
    assert any(math.isnan(row[1][0]) for row in rows)
    assert any(math.isnan(row[2][0]) for row in rows)
    assert math.isfinite(rows[-1][-1])


@pytest.mark.parametrize('execution',['next','once','replay'])
@pytest.mark.parametrize('mode',[0,2,3,4,5,6])
def test_unneeded_open_missing_does_not_invalidate_applied_price(mode,execution):
    rows=_run(_frame('open'),mode,execution)
    _verify(rows,mode)
    assert any(math.isnan(row[1][0]) and math.isfinite(row[-1]) for row in rows)


@pytest.mark.parametrize('execution',['next','once','replay'])
@pytest.mark.parametrize('mode',[0,1,2,3,4,5,6,8,9,10,11])
def test_applied_price_formula_for_valid_data(mode,execution):
    rows=_run(_frame(),mode,execution)
    _verify(rows,mode)
    assert rows[0][0] == 4
    if execution=='replay': assert any(a[0]==b[0] for a,b in zip(rows,rows[1:]))


@pytest.mark.parametrize('execution',['next','once','replay'])
@pytest.mark.parametrize('name,mode', [('PRICE_DEMARK',10),('PRICE_AVERAGE_DEMARK',11)])
def test_named_demark_modes_use_the_same_missing_contract(name,mode,execution):
    rows=_run(_frame('open'),name,execution)
    _verify(rows,mode)
    assert any(math.isnan(row[-1]) for row in rows)


def _strict_run(frame,mode,runonce):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _research_feed, _research_spec
    frame=frame.copy();frame.index=frame.index.tz_localize('UTC')
    for field in ('vwap','dollar_volume','cap','sector','industry','subindustry'): frame[field]=1.
    research=_research_spec({'asset-0':frame});instances=[]
    class Factor(FactorIndicator):
        lines=('factor',);formula_fields=required_fields=('close',);lookback_h=0
        def __init__(self):
            super().__init__();self.child=bt.indicators.DerivativeIndicator(self.data,i_slowing=3,applied_price=mode);instances.append(self)
        def next(self):self.outputs[self.datas[0]].factor[0]=self.child.value[0]
    engine=bt.Cerebro(stdstats=False,runonce=runonce)
    engine.adddata(_research_feed(frame,research,'asset-0'),name='asset-0')
    engine.addstrategy(FactorStrategy,research=research,factors={'deriv':FactorSpec(name='deriv',indicator=Factor,panel_line='factor',field_bindings={'close':'feed:target:close'},mode='native')})
    engine.run(preload=True)
    return instances[0].child.value.array


@pytest.mark.parametrize('runonce',[False,True])
@pytest.mark.parametrize('mode',[10,11])
def test_strict_missing_open_preserved_and_recovers(mode,runonce):
    values=_strict_run(_frame('open'),mode,runonce)
    assert math.isnan(values[19]) and math.isnan(values[22]) and math.isfinite(values[24])




@pytest.mark.parametrize('execution',['next','once'])
@pytest.mark.parametrize('mode',[10,11])
@pytest.mark.parametrize('bull,missing,selected',[(True,'high',True),(True,'low',False),
                                                (False,'low',True),(False,'high',False)])
def test_demark_only_requires_the_selected_extreme(execution,mode,bull,missing,selected):
    frame=_frame()
    frame.iloc[19,frame.columns.get_loc('open')]=100.
    frame.iloc[19,frame.columns.get_loc('close')]=102. if bull else 98.
    frame.iloc[19,frame.columns.get_loc('high')]=104.
    frame.iloc[19,frame.columns.get_loc('low')]=96.
    frame.iloc[19,frame.columns.get_loc(missing)]=math.nan
    rows=_run(frame,mode,execution)
    _verify(rows,mode)
    selected_now=next(row for row in rows if row[0]==20)
    selected_lag=next(row for row in rows if row[0]==23)
    assert math.isnan(selected_now[-1]) == selected
    assert math.isnan(selected_lag[-1]) == selected


@pytest.mark.parametrize('runonce',[False,True])
@pytest.mark.parametrize('mode',[10,11])
def test_original_strategy_does_not_trade_on_unknown_cross_and_recovers(runonce,mode):
    from tests.functional.strategies.trend_following.test_0098_0982_derivative import DerivativeStrategy
    import contextlib,io
    class Probe(DerivativeStrategy):
        def __init__(self):
            super().__init__();self.entries=[];self.signals=[]
        def _submit_entry(self,direction,reason):
            self.entries.append((len(self.signal_feed),direction))
            return super()._submit_entry(direction,reason)
        def next(self):
            if len(self.signal_feed)>=4:
                self.signals.append((len(self.signal_feed),float(self.indicator.value[0])))
            super().next()
    frame=_frame();frame.loc[:,['open','close','high','low']]=100.
    for idx in (18,25):
        frame.iloc[idx,frame.columns.get_indexer(['open','close','high','low'])]=[91.,90.,92.,89.]
    for idx in (19,26):
        frame.iloc[idx,frame.columns.get_indexer(['open','close','high','low'])]=[109.,110.,111.,108.]
    frame.iloc[19,frame.columns.get_loc('open')]=math.nan
    execution=frame.copy();execution.loc[:,['open','close','high','low']]=100.
    engine=bt.Cerebro(stdstats=False,runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=execution))
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe,i_slowing=3,applied_price=mode,signal_bar=1)
    with contextlib.redirect_stdout(io.StringIO()): result=engine.run(preload=True)[0]
    assert dict(result.signals)[19]<0 and math.isnan(dict(result.signals)[20])
    assert not any(bar==20 for bar,_ in result.entries)
    assert (27,-1) in result.entries


@pytest.mark.parametrize('mode',[0,6,11])
@pytest.mark.parametrize('runonce',[False,True])
def test_custom_price_hook_runs_before_any_lines_access(mode,runonce):
    class Custom(bt.indicators.DerivativeIndicator):
        def __init__(self):super().__init__();self.inside=False;self.price_seen=False;self.line_reads=0
        def __getattribute__(self,name):
            if name=='lines':
                state=object.__getattribute__(self,'__dict__')
                if state.get('inside',False):
                    state['line_reads']+=1
                    if not state.get('price_seen',False):raise RuntimeError('lines before price')
            return super().__getattribute__(name)
        def _price(self,ago=0):self.price_seen=True;return super()._price(ago)
        def next(self):
            self.inside=True;self.price_seen=False
            try:return super().next()
            finally:self.inside=False
    class Probe(bt.Strategy):
        def __init__(self):self.ind=Custom(self.data,i_slowing=3,applied_price=mode)
    engine=bt.Cerebro(stdstats=False,runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=_frame()));engine.addstrategy(Probe)
    result=engine.run(preload=True)[0]
    assert result.ind.line_reads == len(_frame())-3


@pytest.mark.parametrize('runonce',[False,True])
def test_price_override_can_return_nonfloat_arithmetic_object(runonce):
    class Number:
        def __float__(self):raise RuntimeError('unexpected conversion')
        def __eq__(self,other):raise RuntimeError('unexpected equality')
        def __sub__(self,other):return 0.125
    class Custom(bt.indicators.DerivativeIndicator):
        def _price(self,ago=0):return Number()
    class Probe(bt.Strategy):
        def __init__(self):self.ind=Custom(self.data,i_slowing=3)
    engine=bt.Cerebro(stdstats=False,runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=_frame()));engine.addstrategy(Probe)
    result=engine.run(preload=True)[0]
    assert result.ind.value[0] == 100.*0.125/3.

@pytest.mark.parametrize('runonce',[False,True])
def test_custom_price_temporary_released_before_line_write(runonce):
    import platform
    if platform.python_implementation() != 'CPython':
        pytest.skip('reference-counted temporary lifetime is CPython-specific')
    state={'inside':False,'released':False,'del_calls':0}
    class Delta:
        def __rmul__(self,value):return 0.125
        def __del__(self):state['released']=True;state['del_calls']+=1
    class Number:
        def __sub__(self,other):return Delta()
    class Custom(bt.indicators.DerivativeIndicator):
        def __getattribute__(self,name):
            if name=='lines' and state['inside'] and not state['released']:
                raise RuntimeError('temporary not released before lines access')
            return super().__getattribute__(name)
        def _price(self,ago=0):return Number()
        def next(self):
            state['inside']=True;state['released']=False
            try:return super().next()
            finally:state['inside']=False
    class Probe(bt.Strategy):
        def __init__(self):self.ind=Custom(self.data,i_slowing=3)
    engine=bt.Cerebro(stdstats=False,runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=_frame()));engine.addstrategy(Probe)
    result=engine.run(preload=True)[0]
    assert result.ind.value[0] == 0.125/3.
    assert state['del_calls'] == len(_frame())-3

@pytest.mark.parametrize('runonce',[False,True])
def test_normal_overflow_does_not_access_dynamic_lines_during_price(runonce):
    class Custom(bt.indicators.DerivativeIndicator):
        def __init__(self):super().__init__();self.in_price=False
        def __getattribute__(self,name):
            if name=='lines' and object.__getattribute__(self,'__dict__').get('in_price',False):
                raise RuntimeError('lines during price')
            return super().__getattribute__(name)
        def _price(self,ago=0):
            self.in_price=True
            try:return super()._price(ago)
            finally:self.in_price=False
    class Probe(bt.Strategy):
        def __init__(self):self.ind=Custom(self.data,i_slowing=3,applied_price=11)
    frame=_frame();frame.loc[:,'open']=1e307;frame.loc[:,'high']=1e308
    frame.loc[:,'low']=1e307;frame.loc[:,'close']=9e307
    engine=bt.Cerebro(stdstats=False,runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=frame));engine.addstrategy(Probe)
    result=engine.run(preload=True)[0]
    assert math.isnan(result.ind.value[0])

@pytest.mark.parametrize('runonce',[False,True])
@pytest.mark.parametrize('mode',[6,11])
def test_existing_strict_computed_overflow_remains_unresolved(mode,runonce):
    # Characterization only: finite source values overflow the applied price;
    # HEAD currently lets inf-inf become NaN in the strict factor. This test
    # records the open gap, not acceptance of that behavior.
    frame=_frame();frame.loc[:,'open']=1e307;frame.loc[:,'close']=1e308
    frame.loc[:,'high']=1e308;frame.loc[:,'low']=0.
    result=_strict_run(frame,mode,runonce)
    assert all(math.isnan(value) for value in result[3:])


@pytest.mark.parametrize('runonce',[False,True])
def test_existing_strict_finite_difference_overflow_still_raises(runonce):
    from backtrader.errors import FactorComputationError
    frame=_frame();frame.loc[:,'close']=1e308
    frame.loc[frame.index[::2],'close']=-1e308
    with pytest.raises(FactorComputationError) as caught:
        _strict_run(frame,0,runonce)
    assert isinstance(caught.value.__cause__,ArithmeticError)
