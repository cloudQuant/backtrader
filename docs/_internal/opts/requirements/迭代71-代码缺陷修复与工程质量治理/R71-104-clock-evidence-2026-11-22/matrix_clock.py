import math,hashlib,json,pandas as pd,backtrader as bt
rows=[]
for mode,bounded in [('next',False),('once',False),('next',True),('replay',False),('replay',True)]:
 for asynchronous in (False,True):
  n=160;idx=pd.date_range('2024-01-01',periods=n,freq='min');values=[100.+i*.1+math.sin(i*.17) for i in range(n)]
  df=pd.DataFrame({'open':values,'high':[x+1 for x in values],'low':[x-1 for x in values],'close':values,'volume':[1.]*n},index=idx)
  other=df.iloc[[i for i in range(n) if not asynchronous or i%3!=0]].copy()
  class S(bt.Strategy):
   def __init__(self):
    self.expr=(self.data0.close+1.)/(self.data1.close+2.);self.ind=bt.ind.SMA(self.expr,period=5);self.trace=[]
   def next(self):self.trace.append((len(self.data0),len(self.data1),float(self.ind[0])))
  c=bt.Cerebro(stdstats=False,runonce=mode=='once',exactbars=int(bounded),preload=not bounded and mode!='replay')
  c.adddata(bt.feeds.PandasData(dataname=df,timeframe=bt.TimeFrame.Minutes))
  src=bt.feeds.PandasData(dataname=other,timeframe=bt.TimeFrame.Minutes)
  if mode=='replay':c.replaydata(src,timeframe=bt.TimeFrame.Minutes,compression=4)
  else:c.adddata(src)
  c.addstrategy(S)
  try:
   s=c.run()[0];v=('returned',len(s.trace),hashlib.sha256(repr(s.trace).encode()).hexdigest())
  except Exception as e:v=('exception',type(e).__name__,str(e))
  rows.append((mode,bounded,asynchronous,v))
print(json.dumps(rows))
