import hashlib,json,math,time
from pathlib import Path
import pandas as pd,backtrader as bt
assert Path(bt.__file__).resolve().is_relative_to(Path.cwd())
n=4500;idx=pd.date_range('2024-01-01',periods=n,freq='min');cl=[100.+i*.01+3*math.sin(i*.12) for i in range(n)]
f=pd.DataFrame({'open':cl,'high':[x+1 for x in cl],'low':[x-1 for x in cl],'close':cl,'volume':[1.]*n},index=idx)
class S(bt.Strategy):
 def __init__(self):
  self.expression=(self.data0.close+1.)/(self.data1.close+2.)
  self.inds=[bt.ind.SMA(self.expression,period=i+3) for i in range(12)];self.rows=[]
 def next(self):self.rows.append((len(self.data0),len(self.data1),*(x[0] for x in self.inds)))
c=bt.Cerebro(stdstats=False,runonce=False);c.adddata(bt.feeds.PandasData(dataname=f));c.adddata(bt.feeds.PandasData(dataname=f));c.addstrategy(S)
t=time.perf_counter();s=c.run()[0];elapsed=time.perf_counter()-t
print(json.dumps({'seconds':elapsed,'rows':len(s.rows),'digest':hashlib.sha256(repr(s.rows).encode()).hexdigest()}))
