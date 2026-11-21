import math,pandas as pd,pytest,backtrader as bt
from backtrader.errors import FactorComputationError
from backtrader.research import align_to_grid
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec,ResearchSpec
from backtrader.strategies.factor_strategy import FactorStrategy
def frame(n=100, missing=None, zero_field=None):
    o = [100 + i * .2 for i in range(n)]
    close = [v + 2 * math.sin(i * .7) for i, v in enumerate(o)]
    result = pd.DataFrame({
        "open": o, "high": [max(a, b) + 1 for a, b in zip(o, close)],
        "low": [min(a, b) - 1 for a, b in zip(o, close)], "close": close,
        "volume": 1., "openinterest": 0.,
    }, index=pd.date_range("2024-01-01", periods=n, freq="min"))
    if zero_field is not None:
        result.loc[:, zero_field] = 0.
    if missing is not None:
        result.loc[result.index[39], missing] = math.nan
    return result
@pytest.mark.parametrize('once',[False,True])
@pytest.mark.parametrize('field',['open','high','low','close'])
def test_real_factor_missing_and_overflow(once,field):
 f=frame(65,missing=None if field=='overflow' else field,zero_field=None if field=='overflow' else field);f.index=f.index.tz_localize('UTC');idx=f.index.rename('close_time')
 if field=='overflow':
  for k in ('open','high','low','close'):f.loc[:,k]=1e308
 research=ResearchSpec(grid=pd.DataFrame({'open_time':idx-pd.Timedelta(minutes=1)},index=idx),start=idx[0],end=idx[-1],targets=('asset',),source_timezone='UTC',snapshot_id='trix-lab',price_basis='synthetic',calendar_id='synthetic',frequency='1min',feed_time_kind='close_time',groups={'asset':'market'})
 seen=[]
 class Factor(FactorIndicator):
  lines=('factor',);formula_fields=required_fields=('open','high','low','close');lookback_h=0
  def __init__(self):super().__init__();self.child=bt.indicators.TriXCandleIndicator(self.data,period=3);seen.append(self)
  def next(self):
   name={'open':'color','high':'h','low':'l','close':'color','overflow':'color'}[field]
   self.outputs[self.datas[0]].factor[0]=getattr(self.child.lines,name)[0]
 c=bt.Cerebro(stdstats=False,runonce=once);c.adddata(align_to_grid(f,research,'asset').feed,name='asset');bindings={k:'feed:target:'+k for k in Factor.formula_fields};s=FactorSpec(name='trixcandle',indicator=Factor,panel_line='factor',field_bindings=bindings,mode='native');c.addstrategy(FactorStrategy,research=research,factors={'trixcandle':s})
 if field=='overflow':
  with pytest.raises(FactorComputationError) as caught:c.run(preload=True)
  assert isinstance(caught.value.__cause__,ArithmeticError);assert seen and seen[0]._factor_strict_context.failed
 else:
  c.run(preload=True);assert seen and not seen[0]._factor_strict_context.failed
  name={'open':'color','high':'h','low':'l','close':'color'}[field];assert math.isnan(getattr(seen[0].child.lines,name).array[39])
