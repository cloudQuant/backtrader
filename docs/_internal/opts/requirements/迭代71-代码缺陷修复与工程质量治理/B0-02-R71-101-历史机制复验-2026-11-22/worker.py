import datetime as dt,hashlib,importlib.abc,json,math,os,struct,sys,time,types
from pathlib import Path
root=Path(__file__).resolve().parent
version=sys.argv[1];bars=int(sys.argv[2]);instrumented=sys.argv[3]=='count'
os.environ['BACKTRADER_LIGHT_IMPORT']='1'
sys.path.insert(0,str(root/version))
blocked_names=[]
class Forbidden(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  banned=('bt_api_py','bt_api_base','bt_api_', 'backtrader.stores.', 'backtrader.brokers.btapi', 'backtrader.feeds.btapi','backtrader.execution','backtrader.factor_execution','backtrader.service')
  if any(fullname.startswith(x) for x in banned):
   blocked_names.append(fullname);raise RuntimeError('excluded_component_import')
  return None
sys.meta_path.insert(0,Forbidden())
# The historical package eagerly imports the optional stores namespace even in
# light mode.  Keep that unused namespace inert without loading its BtApiStore.
stores=types.ModuleType('backtrader.stores');stores.__path__=[];sys.modules['backtrader.stores']=stores
blocked_events=[]
def audit(event,args):
 if event in ('socket.connect','socket.bind','socket.getaddrinfo','subprocess.Popen','os.system'):
  blocked_events.append(event);raise RuntimeError('network_or_process_forbidden')
 if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
  path=os.path.normcase(os.path.abspath(os.fsdecode(args[0])))
  allowed=(os.path.normcase(str(root)),os.path.normcase(sys.base_prefix),os.path.normcase(os.path.abspath('C:/Windows/System32')))
  if not any(path==r or path.startswith(r+os.sep) for r in allowed):
   blocked_events.append('outside_root');raise RuntimeError('outside_root')
  name=os.path.basename(path).lower()
  if name=='.env' or name.startswith('.env.') or name in ('config.yaml','config.yml','credentials.json'):
   blocked_events.append('private_name');raise RuntimeError('private_input')
sys.addaudithook(audit)
import backtrader as bt
from backtrader.lineseries import LineSeries
counts={'_once_called':0,'_resolved_secondary_clock':0}
if instrumented:
 old_getattr=LineSeries.__getattr__
 def tracking(self,name):
  try:return old_getattr(self,name)
  except AttributeError:
   if name in counts:counts[name]+=1
   raise
 LineSeries.__getattr__=tracking
class Feed(bt.feed.DataBase):
 def __init__(self):super().__init__();self.k=0
 def _load(self):
  if self.k>=bars:return False
  value=100.0+(self.k%59)*0.11+(self.k%7)*0.07
  self.datetime[0]=bt.date2num(dt.datetime(2024,1,1)+dt.timedelta(minutes=self.k))
  self.open[0]=self.high[0]=self.low[0]=self.close[0]=value
  self.volume[0]=1.;self.openinterest[0]=0.;self.k+=1;return True
class Probe(bt.Strategy):
 def __init__(self):self.inds=[bt.ind.SMA(self.data.close,period=i) for i in range(10,26)];self.digest=hashlib.sha256();self.rows=0
 def next(self):
  vals=[float(x[0]) for x in self.inds]
  self.digest.update(struct.pack('!I16d',len(self),*vals));self.rows+=1
c=bt.Cerebro(stdstats=False,runonce=True,preload=True);c.adddata(Feed());c.addstrategy(Probe)
t0=time.perf_counter();s=c.run()[0];elapsed=time.perf_counter()-t0
out={'version':version,'bars':bars,'instrumented':instrumented,'elapsed':elapsed,'rows':s.rows,'signals_sha256':s.digest.hexdigest(),'arrays_sha256':hashlib.sha256(b''.join(x.lines[0].array.tobytes() for x in s.inds)).hexdigest(),'missing_attr':counts,'blocked_events':blocked_events,'excluded_import_attempts':blocked_names,'source':bt.__file__}
print(json.dumps(out),flush=True)
assert not blocked_names,'excluded component imported'
