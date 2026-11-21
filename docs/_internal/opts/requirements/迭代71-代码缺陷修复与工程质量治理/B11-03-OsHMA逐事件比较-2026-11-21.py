import contextlib, io, json, hashlib, subprocess, sys, types
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p / ".git").exists()); sys.path.insert(0,str(ROOT))
import backtrader as bt
import tests.functional.strategies.trend_following.test_0147_1275_oshma as case
source=subprocess.check_output(['git','show','61d44ed747081e3bf9895b0b6d19cd9d1fc2c559:backtrader/indicators/contrib/hma.py'],cwd=ROOT).decode('utf-8')
m=types.ModuleType('backtrader.indicators.contrib._iter71_old_hma');m.__package__='backtrader.indicators.contrib';sys.modules[m.__name__]=m
exec(compile(source,'<iter71-old-hma>','exec'),m.__dict__)
config=case._bt_load_config(case._CONFIG,repo=case._REPO)
with contextlib.redirect_stdout(io.StringIO()): frame=case.load_backtest_frame(config)
new=bt.indicators.OsHMAIndicator

def run(cls, once):
 logs=[];orders=[];trades=[];steps=[]
 class Observed(case.OsHMAStrategy):
  def log(self,text): logs.append((bt.num2date(self.data.datetime[0]).isoformat(),text))
  def next(self):
   if len(steps)<3:steps.append((len(self.data),self.indicator.hist[0]))
   return super().next()
  def notify_order(self,o):
   orders.append((bt.num2date(self.data.datetime[0]).isoformat(),o.getstatusname(),o.isbuy(),o.created.size,o.executed.size,o.executed.price));return super().notify_order(o)
  def notify_trade(self,t):
   trades.append((bt.num2date(self.data.datetime[0]).isoformat(),t.status,t.size,t.price,t.pnl,t.pnlcomm));return super().notify_trade(t)
 original=case.OsHMAStrategy
 try:
  bt.indicators.OsHMAIndicator=cls;case.OsHMAStrategy=Observed
  engine=case.build_cerebro(config,frame)
  with contextlib.redirect_stdout(io.StringIO()): result=engine.run(runonce=once,preload=True)[0]
  return dict(logs=logs,orders=orders,trades=trades,steps=steps,metrics=case.extract_metrics(result,engine,frame,config))
 finally:bt.indicators.OsHMAIndicator=new;case.OsHMAStrategy=original

old=run(m.OsHMAIndicator,True); batch=run(new,True); event=run(new,False)
out={}
for name,r in [('old_once',old),('new_once',batch),('new_next',event)]:
 out[name]={'metrics':r['metrics'],'steps':r['steps'],'counts':{k:len(r[k]) for k in ('logs','orders','trades')},'hashes':{k:hashlib.sha256(json.dumps(r[k],ensure_ascii=True,separators=(',',':')).encode()).hexdigest() for k in ('logs','orders','trades')}}
for a,b,label in [(old,batch,'old_to_new'),(batch,event,'new_once_to_next')]:
 out[label]={}
 for k in ('logs','orders','trades'):
  x,y=a[k],b[k];first=next((i for i,(u,v) in enumerate(zip(x,y)) if u!=v),None)
  out[label][k]={'equal':x==y,'first_diff':first,'old':x[first] if first is not None else None,'new':y[first] if first is not None else None}
p=ROOT/'.codex-tmp/iter71_oshma_strategy_events.json';p.write_text(json.dumps(out,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8');print(json.dumps(out,indent=2,ensure_ascii=False,default=str))
