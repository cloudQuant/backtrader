from __future__ import annotations
import ast
import asyncio
import collections
import hashlib
import importlib.abc
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
REPO = Path(r'D:\source_code\backtrader')
SOURCE = Path(r'D:\temp\ac41-63-store-write-narrow-audit-20260927\fresh-replay\backtrader\stores\btapistore.py')
OUT = Path(r'D:\temp\ac41-63-store-write-narrow-audit-20260927')
sha = lambda b: hashlib.sha256(b).hexdigest().upper()
source_bytes = SOURCE.read_bytes()
tree = ast.parse(source_bytes, filename=str(SOURCE))

# Source-only sink inventory, without importing or executing the repository source.
sink_names = {
    'submit_order','create_order','cancel_order','ReqOrderInsert','ReqOrderAction',
    '_send_native_order_insert','_send_native_order_action',
    'async_make_order','async_cancel_order','_invoke_sdk_command',
    '_enqueue_order_command','_enqueue_sdk_command','_enqueue_ctp_managed_cancel',
}
class SinkVisitor(ast.NodeVisitor):
    def __init__(self): self.stack=[]; self.rows=[]
    def visit_ClassDef(self,node):
        self.stack.append('class '+node.name); self.generic_visit(node); self.stack.pop()
    def visit_FunctionDef(self,node):
        self.stack.append('def '+node.name); self.generic_visit(node); self.stack.pop()
    def visit_AsyncFunctionDef(self,node):
        self.stack.append('async '+node.name); self.generic_visit(node); self.stack.pop()
    def visit_Call(self,node):
        func=node.func
        if isinstance(func,ast.Attribute) and func.attr in sink_names:
            self.rows.append({'line':node.lineno,'scope':' > '.join(self.stack),'call':ast.unparse(func)})
        self.generic_visit(node)
visitor=SinkVisitor(); visitor.visit(tree)

# Guard optional SDK/native imports. The tested entry is the freshly patched A028 copy.
blocked=[]
class BlockLoader(importlib.abc.Loader):
    def create_module(self,spec): return None
    def exec_module(self,module): raise AssertionError('forbidden optional import: '+module.__name__)
class ImportBlocker(importlib.abc.MetaPathFinder):
    prefixes=('bt_api_py','_ctp','thostmduserapi','thosttraderapi','_thostmduserapi','_thosttraderapi')
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==p or fullname.startswith(p+'.') for p in self.prefixes):
            blocked.append(fullname)
            return importlib.util.spec_from_loader(fullname,BlockLoader())
        return None
sys.meta_path.insert(0,ImportBlocker())

# Load only the target Store file from the isolated replay. Its ordinary pure-Python
# internal support modules resolve from the current repo; package __init__ files are skipped.
for name, folder in (
    ('backtrader', REPO/'backtrader'),
    ('backtrader.stores', REPO/'backtrader'/'stores'),
    ('backtrader.utils', REPO/'backtrader'/'utils'),
):
    pkg=types.ModuleType(name); pkg.__path__=[str(folder)]; pkg.__package__=name
    sys.modules[name]=pkg
spec=importlib.util.spec_from_file_location('backtrader.stores.btapistore',SOURCE)
module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
BtApiStore=module.BtApiStore
assert not blocked, f'blocked SDK/native import attempted: {blocked}'

class FakeCtpDirectApi:
    """Fake route-labelled CTP API; methods stop at local counters."""
    exchange_kwargs={'CTP___TEST': {}}
    def __init__(self): self.calls=[]
    def submit_order(self,payload):
        self.calls.append(('api.submit_order','CTP___TEST'))
        return self.ReqOrderInsert(payload)
    def ReqOrderInsert(self,payload):
        self.calls.append(('fake.ReqOrderInsert','CTP___TEST'))
        return {'ok':True,'order_id':'fake-1'}
    def cancel_order(self,order_ref,dataname=None):
        self.calls.append(('api.cancel_order','CTP___TEST'))
        return self.ReqOrderAction(order_ref,dataname)
    def ReqOrderAction(self,order_ref,dataname):
        self.calls.append(('fake.ReqOrderAction','CTP___TEST'))
        return {'ok':True,'cancelled':True}

# Candidate 1: public legacy Store methods accept a route-mismatched injected CTP API
# because provider='binance' makes the CTP classifier return False.
direct_api=FakeCtpDirectApi()
direct=object.__new__(BtApiStore)
direct.provider='binance'; direct.backend='direct'; direct._config={}; direct._api_kwargs={}
direct._sdk_exchanges={}; direct._sdk_routes={}; direct._managed_execution_adapter=None
direct._sdk_mode=False; direct._sdk_execution_config={}; direct._api=direct_api
direct._connected=True; direct._funding_restart_blocked_by_worker=False
direct._restart_blocked_by_worker=False; direct._restart_blocked_by_close=False; direct._sdk_configured=True
direct.emit_runtime_event=lambda *a,**k: None
direct.sanitize_exception=lambda exc: None
direct._order_to_payload=lambda order: {'symbol':'FAKE','side':'buy','size':1}
direct._extract_external_order_id=lambda response: response.get('order_id')
direct._submit_response_looks_accepted=lambda response: True
direct._cancel_response_error=lambda response: None
assert direct._is_ctp_write_provider() is False
assert direct.sdk_api is direct_api
submit_response=direct.submit_order(SimpleNamespace(ref='bt-1'))
cancel_response=direct.cancel_order_ref('fake-1',dataname='FAKE')
assert submit_response['ok'] is True and cancel_response['cancelled'] is True
assert direct_api.calls == [
    ('api.submit_order','CTP___TEST'),('fake.ReqOrderInsert','CTP___TEST'),
    ('api.cancel_order','CTP___TEST'),('fake.ReqOrderAction','CTP___TEST'),
]

# Control: correctly labelled built-in CTP Store public legacy entry points fail closed.
proper_api=FakeCtpDirectApi()
proper=object.__new__(BtApiStore)
proper.provider='ctp'; proper.backend='direct'; proper._config={}; proper._api_kwargs={}
proper._sdk_exchanges={}; proper._sdk_routes={}; proper._managed_execution_adapter=None
proper._sdk_mode=False; proper._sdk_execution_config={}; proper._api=proper_api
proper._connected=True; proper._funding_restart_blocked_by_worker=False
proper.emit_runtime_event=lambda *a,**k: None
proper.sanitize_exception=lambda exc: None
proper._order_to_payload=lambda order: {'symbol':'FAKE','side':'buy','size':1}
proper._extract_external_order_id=lambda response: response.get('order_id')
proper._submit_response_looks_accepted=lambda response: True
proper._cancel_response_error=lambda response: None
proper_errors=[]
for operation in ('submit','cancel'):
    try:
        if operation=='submit': proper.submit_order(SimpleNamespace(ref='ctp-1'))
        else: proper.cancel_order_ref('fake-1',dataname='FAKE')
    except module.BtApiStoreError as exc:
        proper_errors.append((operation,str(exc)))
assert len(proper_errors)==2 and proper_api.calls==[]
class FakeMutableSdkApi:
    def __init__(self): self.exchange_kwargs={'BINANCE': {}}; self.calls=[]
    def poll_event(self): return None
    async def async_make_order(self,venue,request,**kwargs):
        self.calls.append(('fake.async_make_order',venue,tuple(self.exchange_kwargs)))
        return {'ok':True,'operation':'submit'}
    async def async_cancel_order(self,venue,request,**kwargs):
        self.calls.append(('fake.async_cancel_order',venue,tuple(self.exchange_kwargs)))
        return {'ok':True,'operation':'cancel'}
    async def async_query_order(self,venue,request,**kwargs): return {'ok':True,'items':[]}

# Candidate 2: reproduce the constructor's shallow route snapshot, then mutate the
# retained injected client's public route table from BINANCE to CTP.
mutable_api=FakeMutableSdkApi()
sdk=object.__new__(BtApiStore)
sdk.provider='btapi'; sdk.backend='direct'; sdk._config={}; sdk._api_kwargs={}
sdk._sdk_exchanges=dict(mutable_api.exchange_kwargs) # same derivation as init at A028: line 3550
sdk._sdk_routes={}; sdk._managed_execution_adapter=None; sdk._sdk_mode=True
sdk._sdk_execution_config={'market_data_only':False}; sdk._api=mutable_api
sdk._connected=True; sdk._funding_restart_blocked_by_worker=False
sdk._restart_blocked_by_worker=False; sdk._restart_blocked_by_close=False; sdk._sdk_configured=True
sdk.emit_runtime_event=lambda *a,**k: None
sdk.sanitize_exception=lambda exc: None
sdk._command_health=collections.Counter(); sdk._command_last_error=''
sdk._sdk_broker_event=lambda venue,event: event
sdk._enqueue_order_command=lambda order: {'queued':True,'via':'local fake queue'}
sdk._start_command_worker=lambda: None
sdk._sdk_cancel_request=lambda ref,dataname: (
    'CTP___TEST', SimpleNamespace(client_order_id='fake-client',symbol='FAKE')
)
sdk._sdk_local_refs={}; sdk._sdk_client_refs={}
sdk._cancel_queued_opening_before_send=lambda *a: None
sdk._enqueue_sdk_command=lambda *a,**k: {'queued':True,'via':'local fake queue'}
assert sdk._is_ctp_write_provider() is False
mutable_api.exchange_kwargs.clear(); mutable_api.exchange_kwargs['CTP___TEST']={}
assert sdk._is_ctp_write_provider() is False # stale self._sdk_exchanges remains BINANCE
assert sdk._is_ctp_session_provider() is True # dynamic _ctp_sdk_venues reads current API exchange_kwargs
assert sdk.sdk_api is mutable_api # public raw-client accessor still hands it out
queued_submit=sdk.submit_order(SimpleNamespace(ref='bt-sdk-1',info={}))
queued_cancel=sdk.cancel_order_ref('fake-client',dataname='FAKE')
assert queued_submit['queued'] and queued_cancel['queued']
submit_completion=asyncio.run(sdk._execute_sdk_command({
    'operation':'submit','receipt_id':'fake-s1','bt_order_ref':'bt-sdk-1',
    'client_order_id':'fake-client','symbol':'FAKE','venue':'CTP___TEST',
    'priority':'open','request':object(),'session_generation':1,
    'risk_incident_epoch_at_enqueue':0,
}))
cancel_completion=asyncio.run(sdk._execute_sdk_command({
    'operation':'cancel','receipt_id':'fake-c1','bt_order_ref':'bt-sdk-1',
    'client_order_id':'fake-client','symbol':'FAKE','venue':'CTP___TEST',
    'priority':'cancel','request':object(),'session_generation':1,
    'risk_incident_epoch_at_enqueue':0,
}))
assert submit_completion['success'] and cancel_completion['success']
assert mutable_api.calls == [
    ('fake.async_make_order','CTP___TEST',('CTP___TEST',)),
    ('fake.async_cancel_order','CTP___TEST',('CTP___TEST',)),
]
assert not blocked, f'blocked SDK/native import attempted: {blocked}'

result={
 'schema':'ac41-63-store-write-narrow-fake-audit.v1',
 'source':str(SOURCE),'source_sha256':sha(source_bytes),
 'base_source_sha256':'A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D',
 'frozen_r3_patch_sha256':'C1550368359A159F18CE6777F6377CCA83DA7F948DE81B99D8DE86BEEE6CCAD3',
 'candidate_sha256_expected':'00D31700B8554E954C52A748E2DBA09CB781DAED403EEC82AA750D1844513F55',
 'optional_imports_blocked':blocked,'ast_write_sink_calls':visitor.rows,
 'findings':[
   {'id':'route-mismatched-injected-direct-api','status':'FAKE_REPRODUCED_CONDITIONAL_BYPASS','store_route':'provider=binance, backend=direct','injected_api_route':'CTP___TEST','public_calls':['BtApiStore.submit_order','BtApiStore.cancel_order_ref'],'trace':['submit_order','_submit_order_legacy','_ensure_api_ready','api.submit_order','fake ReqOrderInsert shim','cancel_order_ref','_cancel_order_ref_legacy','_ensure_api_ready','api.cancel_order','fake ReqOrderAction shim'],'classification':'_is_ctp_write_provider returns False because non-btapi/direct provider identity is trusted; the injected API route is not consulted.','fake_calls':direct_api.calls,'limit':'Only local fake CTP-labelled API hooks ran; this demonstrates Store-to-API reachability, not vendor/native acceptance.'},
   {'id':'mutable-api-route-snapshot-toctou','status':'FAKE_REPRODUCED_CONDITIONAL_BYPASS','initial_api_route':'BINANCE','post_init_api_route':'CTP___TEST','public_calls':['BtApiStore.submit_order','BtApiStore.cancel_order_ref'],'trace':['constructor-style dict snapshot of api.exchange_kwargs into _sdk_exchanges','mutate retained api.exchange_kwargs to CTP___TEST','_is_ctp_write_provider remains False','public submit/cancel enqueue paths accept','_execute_sdk_command -> _invoke_sdk_command -> fake async_make_order/async_cancel_order'],'classifier_mismatch':{'_is_ctp_write_provider':False,'_is_ctp_session_provider':True,'sdk_api_returns_raw_api':True},'queued_responses':[queued_submit,queued_cancel],'fake_calls':mutable_api.calls,'completions':[submit_completion,cancel_completion],'limit':'No worker thread or provider SDK/native code ran; worker sink was invoked manually with fake queue commands after public Store enqueue accepted them.'},
 ],
 'negative_scope_check':{'ctp_direct_wrapper_native_insert_and_action_methods':'A028+r3 body is unconditional BtApiStoreError; higher-level CtpClientWrapper submit/cancel route only through those closed methods.','ctp_gateway_wrapper_direct_methods':'guarded by _ensure_direct_writes_allowed; CTP/suffixed CTP route flag computed closed.','r3_generic_queue_and_generic_sdk_sink':'existing guards were not claimed as new findings.','managed_ctp_dispatcher_branch':'known unresolved typed-adapter authority surface, excluded per task.'},
 'correctly_labelled_ctp_control':{'errors':proper_errors,'fake_calls':proper_api.calls}, 'no_real_io':True,'main_tree_modified':False,'tests_used':'direct local-fake Python assertions only; no pytest, SDK, native import, config, credentials, network or provider access.'
}
out=OUT/'narrow-audit-results.json'; out.write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
print(json.dumps({'source_sha256':result['source_sha256'],'candidate_matches_manifest':result['source_sha256']==result['candidate_sha256_expected'],'direct_public_fake_calls':direct_api.calls,'toctou_fake_calls':mutable_api.calls,'classification':result['findings'][1]['classifier_mismatch'],'ast_sink_call_count':len(visitor.rows),'ast_sinks':visitor.rows,'blocked_imports':blocked,'result_path':str(out),'result_sha256':sha(out.read_bytes())},indent=2))



