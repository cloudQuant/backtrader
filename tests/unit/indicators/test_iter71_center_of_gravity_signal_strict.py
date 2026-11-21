import math,pandas as pd,pytest,backtrader as bt
from backtrader.errors import FactorComputationError
from backtrader.research import align_to_grid
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec,ResearchSpec
from backtrader.strategies.factor_strategy import FactorStrategy
@pytest.mark.parametrize('once',[False,True])
@pytest.mark.parametrize('mode',['missing','overflow'])
def test_real_strict_factor(once,mode):
 idx=pd.date_range('2024-01-01',periods=35,freq='min',tz='UTC',name='close_time')
 vals=[100.+i*.3 for i in range(35)]
 if mode=='missing':vals[20]=math.nan
 else:vals=[1e200]*35
 f=pd.DataFrame({'open':vals,'high':vals,'low':vals,'close':vals,'volume':[1.]*35},index=idx)
 research=ResearchSpec(grid=pd.DataFrame({'open_time':idx-pd.Timedelta(minutes=1)},index=idx),start=idx[0],end=idx[-1],targets=('asset',),source_timezone='UTC',snapshot_id='cog-lab',price_basis='synthetic',calendar_id='synthetic',frequency='1min',feed_time_kind='close_time',groups={'asset':'market'})
 seen=[]
 class Factor(FactorIndicator):
  lines=('factor',);formula_fields=required_fields=('close',);lookback_h=0
  def __init__(self):
   super().__init__();self.child=bt.indicators.CenterOfGravityIndicator(self.data,period=3,smooth_period=2,point=.01);seen.append(self)
  def next(self):self.outputs[self.datas[0]].factor[0]=self.child.state[0]
 c=bt.Cerebro(stdstats=False,runonce=once);c.adddata(align_to_grid(f,research,'asset').feed,name='asset');s=FactorSpec(name='cog',indicator=Factor,panel_line='factor',field_bindings={'close':'feed:target:close'},mode='native');c.addstrategy(FactorStrategy,research=research,factors={'cog':s})
 if mode=='overflow':
  with pytest.raises(FactorComputationError) as caught:c.run(preload=True)
  assert isinstance(caught.value.__cause__,ArithmeticError);assert seen and seen[0]._factor_strict_context.failed
 else:
  c.run(preload=True);assert seen and not seen[0]._factor_strict_context.failed
  a=seen[0].child.state.array;assert all(math.isnan(v) for v in a[20:24]);assert math.isfinite(a[-1])
