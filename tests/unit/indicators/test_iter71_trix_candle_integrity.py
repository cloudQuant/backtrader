import math,sys,importlib.util
from pathlib import Path
import pandas as pd,pytest,backtrader as bt

def frame(n=100,missing=None,zero_field=None):
 o=[100+i*.2 for i in range(n)];c=[x+2*math.sin(i*.7) for i,x in enumerate(o)];h=[max(a,b)+1 for a,b in zip(o,c)];l=[min(a,b)-1 for a,b in zip(o,c)]
 f=pd.DataFrame({'open':o,'high':h,'low':l,'close':c,'volume':1.,'openinterest':0.},index=pd.date_range('2024-01-01',periods=n,freq='min'))
 if zero_field is not None:f.loc[:,zero_field]=0.
 if missing is not None:f.loc[f.index[39],missing]=math.nan
 return f

def ema(values,p=3):
 out=[math.nan]*len(values);alpha=2/(p+1);first=next((i for i in range(len(values)-p+1) if all(math.isfinite(x) for x in values[i:i+p])),None)
 if first is None:return out
 idx=first+p-1;out[idx]=sum(values[first:idx+1])/p
 for i in range(idx+1,len(values)):out[i]=alpha*values[i]+(1-alpha)*out[i-1]
 return out

def trix(values):
 x=ema(ema(ema(values)));out=[math.nan]*len(values)
 for i in range(1,len(values)):
  if math.isfinite(x[i]) and math.isfinite(x[i-1]):out[i]=100*(x[i]/x[i-1]-1) if x[i-1]!=0 else 0.
 return out

def run(data,once,replay=False):
 class P(bt.Strategy):
  def __init__(self):self.ind=bt.indicators.TriXCandleIndicator(self.data,period=3);self.rows=[]
  def next(self):
   self.rows.append((len(self.data),tuple(float(getattr(self.data,k)[0]) for k in ('open','high','low','close')),tuple(float(v[0]) for v in self.ind.lines),tuple(float(getattr(self.ind,'trix_'+k)[0]) for k in ('open','high','low','close'))))
 c=bt.Cerebro(stdstats=False,runonce=once,preload=not replay);f=bt.feeds.PandasData(dataname=data,timeframe=bt.TimeFrame.Minutes)
 if replay:c.replaydata(f,timeframe=bt.TimeFrame.Minutes,compression=5)
 else:c.adddata(f)
 c.addstrategy(P);return c.run()[0].rows

@pytest.mark.parametrize('once',[False,True])
def test_clean_independent_triple_ema_formula(once):
 f=frame();r={k:trix(f[k].tolist()) for k in ('open','high','low','close')};rows=run(f,once);assert rows
 for length,src,out,_ in rows:
  i=length-1;o,h,l,c=(r[k][i] for k in ('open','high','low','close'));expected=(o,max(o,c,h),min(o,c,l),c,2 if o<c else 0 if o>c else 1)
  for actual,want in zip(out,expected):assert actual==pytest.approx(want,abs=1e-9,rel=1e-9)

@pytest.mark.parametrize('once',[False,True])
@pytest.mark.parametrize('field',['open','high','low','close'])
def test_nan_propagates_by_candle_dependency_in_zero_denominator_case(once,field):
 rows=run(frame(missing=field,zero_field=field),once);length,src,out,child=next(r for r in rows if r[0]==40)
 pos={'open':0,'high':1,'low':2,'close':3}[field];assert math.isnan(src[pos]);assert child[pos]==0.0
 assert math.isnan(out[pos])
 if field in ('open','close'):assert math.isnan(out[1]) and math.isnan(out[2]) and math.isnan(out[4])
 elif field=='high':assert math.isnan(out[1]) and math.isfinite(out[2]) and math.isfinite(out[4])
 else:assert math.isnan(out[2]) and math.isfinite(out[1]) and math.isfinite(out[4])

@pytest.mark.parametrize('once',[False,True])
def test_real_strategy_ignores_missing_color(once):
 p=Path('tests/functional/strategies/mean_reversion/test_0193_0968_trixcandle.py');spec=importlib.util.spec_from_file_location('trix_case_strategy',p);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
 class S(m.TriXCandleStrategy):
  def __init__(self):super().__init__();self.events=[]
  def log(self,*args,**kwargs):pass
  def next(self):
   self.p.buy_pos_open=len(self.data0_feed)>=40;self.p.sell_pos_open=len(self.data0_feed)>=40;super().next()
  def notify_order(self,o):self.events.append((len(self.data0_feed),o.getstatusname(),o.isbuy()));super().notify_order(o)
 f=frame(missing='open');c=bt.Cerebro(stdstats=False,runonce=once,preload=True);c.broker.setcash(1000000);c.adddata(bt.feeds.PandasData(dataname=f,timeframe=bt.TimeFrame.Minutes));c.addstrategy(S,trix_period=3,signal_bar=1,stop_loss_points=0,take_profit_points=0,fixed_lot=.1);s=c.run()[0];assert s.events==[];assert s.buy_signal_count==0 and s.sell_signal_count==0

@pytest.mark.parametrize('bad_index',[61,63])
def test_replay_close_nan_is_missing_and_same_bar_recovers(bad_index):
 f=frame(150);f.loc[f.index[bad_index],'close']=math.nan;rows=run(f,False,replay=True)
 indices=[i for i,r in enumerate(rows) if math.isnan(r[1][3])];assert len(indices)==1
 i=indices[0];assert math.isnan(rows[i][2][3]) and math.isnan(rows[i][2][4]);assert rows[i+1][0]==rows[i][0];assert math.isfinite(rows[i+1][2][3]) and math.isfinite(rows[i+1][2][4])
