import math,sys,importlib.util
from pathlib import Path
import pandas as pd,pytest,backtrader as bt

def make_frame(n=80,missing=None):
 closes=[100+math.sin(i*.35)*4+i*.04 for i in range(n)]
 if missing is not None:closes[missing]=math.nan
 return pd.DataFrame({'open':[100.+i*.04 for i in range(n)],'high':[105.+i*.04 for i in range(n)],'low':[95.+i*.04 for i in range(n)],'close':closes,'volume':[10.]*n,'openinterest':[0.]*n},index=pd.date_range('2024-01-01',periods=n,freq='min'))

def run(frame,once,replay=False):
 class Probe(bt.Strategy):
  def __init__(self):self.i=bt.indicators.CenterOfGravityIndicator(self.data,period=3,smooth_period=2,point=.01);self.rows=[]
  def next(self):self.rows.append((len(self.data),float(self.data.close[0]),float(self.i.center[0]),float(self.i.signal[0]),float(self.i.state[0])))
 c=bt.Cerebro(stdstats=False,runonce=once,preload=not replay);feed=bt.feeds.PandasData(dataname=frame,timeframe=bt.TimeFrame.Minutes)
 if replay:c.replaydata(feed,timeframe=bt.TimeFrame.Minutes,compression=5)
 else:c.adddata(feed)
 c.addstrategy(Probe);return c.run()[0].rows

@pytest.mark.parametrize('once',[False,True])
def test_formula_and_missing_recovery(once):
 frame=make_frame(missing=24);rows=run(frame,once);observed_missing=False
 for length,_,center,signal,state in rows:
  i=length-1;xs=frame.close.tolist(); window=xs[i-2:i+1];prior=xs[i-3:i]
  def cog(w):return sum(w)/3*sum((j+1)*v for j,v in enumerate(w))/6/.01
  expected=cog(window); expected_signal=(expected+cog(prior))/2
  if math.isnan(expected) or math.isnan(expected_signal):
   observed_missing=True;assert math.isnan(state)
  else:
   assert center==pytest.approx(expected);assert signal==pytest.approx(expected_signal);assert state==(2 if expected<expected_signal else 1)
 assert observed_missing and math.isfinite(rows[-1][-1])

@pytest.mark.parametrize('once',[False,True])
@pytest.mark.parametrize('signal_bar',[0,1])
def test_real_strategy_nan_does_not_create_orders(once,signal_bar):
 path=Path('tests/functional/strategies/mean_reversion/test_0320_1296_center_of_gravity.py');spec=importlib.util.spec_from_file_location('cog_real_strategy',path);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
 class S(m.CenterOfGravityStrategy):
  def __init__(self):super().__init__();self.orders=[]
  def log(self,*args,**kwargs):pass
  def notify_order(self,o):self.orders.append((len(self.data),o.getstatusname(),o.isbuy()));super().notify_order(o)
  def next(self):super().next()
 closes=[200.-i*2 for i in range(40)];closes[16]=math.nan
 f=pd.DataFrame({'open':[200.-i*2 for i in range(40)],'high':[201.-i*2 for i in range(40)],'low':[199.-i*2 for i in range(40)],'close':closes,'volume':1.,'openinterest':0.},index=pd.date_range('2024-01-01',periods=40,freq='min'))
 c=bt.Cerebro(stdstats=False,runonce=once,preload=True);c.broker.setcash(1000000);c.adddata(bt.feeds.PandasData(dataname=f,timeframe=bt.TimeFrame.Minutes));c.addstrategy(S,period=3,smooth_period=2,signal_bar=signal_bar,point=.01,lot=.1);s=c.run()[0];assert s.orders==[]

def test_replay_missing_is_not_finite_signal():
 rows=run(make_frame(150,missing=61),False,replay=True);assert any(a[0]==b[0] for a,b in zip(rows,rows[1:]));bad=[row for row in rows if not math.isfinite(row[2]) or not math.isfinite(row[3])];assert bad
 assert all(math.isnan(row[-1]) for row in bad)
