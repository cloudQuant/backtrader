import builtins,hashlib,json,sys
import pandas as pd
import backtrader as bt
import backtrader.lineiterator as mod

original=mod.LineIteratorMixin._factor_strict_context_for_callback
stats={'calls':0,'self_id':0,'owner_id':0}
def wrapped(self):
    stats['calls']+=1
    return original(self)
def counted(obj):
    f=sys._getframe(1)
    if f.f_code is original.__code__:
        if obj is f.f_locals['self']:stats['self_id']+=1
        else:stats['owner_id']+=1
    return builtins.id(obj)
mod.LineIteratorMixin._factor_strict_context_for_callback=wrapped
mod.id=counted
class S(bt.Strategy):
    def __init__(self):
        self.ind=[bt.ind.SMA(self.data.close,period=p) for p in (5,6,7,8)]
        self.rows=[]
    def next(self):
        self.rows.append(tuple(float(x[0]) for x in self.ind))
f=pd.DataFrame({'open':[100+i*.1 for i in range(240)],'high':[101+i*.1 for i in range(240)],'low':[99+i*.1 for i in range(240)],'close':[100+i*.1 for i in range(240)],'volume':[1.]*240},index=pd.date_range('2024-01-01',periods=240,freq='min'))
c=bt.Cerebro(stdstats=False,runonce=False);c.adddata(bt.feeds.PandasData(dataname=f));c.addstrategy(S)
s=c.run()[0];print(json.dumps({'stats':stats,'rows':len(s.rows),'digest':hashlib.sha256(repr(s.rows).encode()).hexdigest()}),flush=True)
assert stats['calls'] and stats['self_id'] == stats['calls'], 'self id lookup repeated'

