import ast,sys,types
from pathlib import Path
source=Path(r'D:\temp\iteration41-ctp-gateway-wrapper-default-deny-r2-store-r5-independent-qa-20260927\replay\backtrader\stores\btapistore.py')
tree=ast.parse(source.read_text(encoding='utf-8'),filename=str(source))
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_create_ctp_gateway_wrapper_class')
compiled=compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec')
class StoreError(RuntimeError): pass
class MissingError(RuntimeError): pass
for exchange in ('BINANCE','IB_WEB','OKX','MT5'):
 calls=[]
 class Fake:
  def __init__(self,**kwargs): calls.append(('init',dict(kwargs)))
  def submit_order(self,payload): calls.append(('submit',payload)); return {'ok':True}
  def cancel_order(self,ref,dataname=None): calls.append(('cancel',ref,dataname)); return {'ok':True}
 pkg=types.ModuleType('bt_api_py'); pkg.__path__=[]
 gw=types.ModuleType('bt_api_py.gateway'); gw.__path__=[]
 cli=types.ModuleType('bt_api_py.gateway.client'); cli.GatewayClient=Fake
 names=('bt_api_py','bt_api_py.gateway','bt_api_py.gateway.client')
 old={n:sys.modules.get(n) for n in names}
 sys.modules.update(dict(zip(names,(pkg,gw,cli))))
 try:
  ns={'BtApiStoreError':StoreError,'BtApiMissingDependencyError':MissingError,'_safe_log':lambda *a,**k:None}
  exec(compiled,ns)
  wrapper=ns['_create_ctp_gateway_wrapper_class']()(exchange_type=exchange)
  assert calls[0]==('init',{'exchange_type':exchange,'asset_type':'FUTURE'})
  wrapper.submit_order({'x':1}); wrapper.create_order(x=2); wrapper.cancel_order('r')
  assert [x[0] for x in calls]==['init','submit','submit','cancel']
  print(exchange,'delegation=PASS','calls=',[x[0] for x in calls])
 finally:
  for n,m in old.items():
   if m is None: sys.modules.pop(n,None)
   else: sys.modules[n]=m
