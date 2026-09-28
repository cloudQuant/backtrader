from __future__ import annotations
import json, sys
from types import ModuleType
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
calls=[]
class FakeGatewayClient:
 def __init__(self, **kwargs): self.kwargs=kwargs
 def connect(self): return None
 def disconnect(self): return None
 def get_balance(self): return {'cash': 1.0, 'value': 1.0}
 def submit_order(self, payload): calls.append(('submit_order',payload)); return {'fake':'sent'}
 def cancel_order(self, *args, **kwargs): calls.append(('cancel_order',args,kwargs)); return {'fake':'sent'}
root=ModuleType('bt_api_py'); root.__path__=[]
gateway=ModuleType('bt_api_py.gateway'); gateway.__path__=[]
client=ModuleType('bt_api_py.gateway.client'); client.__file__='<in-memory synthetic fake>'; client.GatewayClient=FakeGatewayClient
sys.modules.update({'bt_api_py':root,'bt_api_py.gateway':gateway,'bt_api_py.gateway.client':client})
store=BtApiStore(provider='ib_web_gateway',backend='gateway',config={'exchange_type':'IB_WEB'})
store._ensure_api_ready()
wrapper=store._api
store.provider='ctp'
try:
 wrapper.submit_order({'id':'public-wrapper'})
except BtApiStoreError as exc:
 wrapper_rejected=str(exc)
else:
 raise AssertionError('wrapper should reject after Store route mutation')
assert calls==[]
raw_result=wrapper._client.submit_order({'id':'private-client'})
assert raw_result=={'fake':'sent'} and len(calls)==1
native_ctp_modules=[name for name in sys.modules if name.rsplit('.',1)[-1] in {'_ctp','ctp_wrap'}]
assert native_ctp_modules==[], native_ctp_modules
print(json.dumps({'provider_origin':'in-memory synthetic fake; no installed SDK import','public_wrapper':'rejected','public_wrapper_error':wrapper_rejected,'fake_provider_calls_after_wrapper':0,'private_store_api_client_access':'reachable in-process; fake call made','fake_provider_calls_after_private_probe':len(calls),'private_result':raw_result,'native_ctp_modules_loaded':native_ctp_modules},indent=2))
