import os,sys,unittest.mock
from backtrader.stores import btapistore as store_module
from backtrader.stores.btapistore import BtApiStore,BtApiStoreError

class StrictEnvironmentProbe:
    def __init__(self, values=None, block=False): self.values=values or {}; self.reads=[]; self.block=block
    def get(self,key,default=None):
        self.reads.append(key)
        if self.block: raise AssertionError('environment read before CTP fail-closed: '+key)
        return self.values.get(key,default)
class Trap:
    def __init__(self,label): object.__setattr__(self,'label',label); object.__setattr__(self,'reads',[])
    def __getattr__(self,name): self.reads.append(name); raise AssertionError(self.label+' attribute read: '+name)
    def __str__(self): raise AssertionError(self.label+' converted to str')
    def __bool__(self): raise AssertionError(self.label+' tested for truth')
    def __iter__(self): self.reads.append('__iter__'); raise AssertionError(self.label+' iterated')
    def items(self): self.reads.append('items'); raise AssertionError(self.label+' items read')
    def keys(self): self.reads.append('keys'); raise AssertionError(self.label+' keys read')
    def __getitem__(self,key): self.reads.append(('getitem',key)); raise AssertionError(self.label+' indexed')

def run_explicit(label,provider,backend,config):
    env=StrictEnvironmentProbe(block=True)
    api=Trap('api'); api_cls=Trap('api_cls'); actor=Trap('actor'); context=Trap('context'); credential=Trap('credential')
    resolver=[]
    if config and type(config) is dict:
        # caller-supplied synthetic secret object; no real material
        if 'execution_authorization_secret' in config: config['execution_authorization_secret']=credential
        if 'exchange_kwargs' in config and 'CTP' in config['exchange_kwargs']:
            config['exchange_kwargs']['CTP']['execution_authorization_secret']=credential
    def forbidden(*args,**kwargs): resolver.append('called'); raise AssertionError('resolver or local client reached')
    with unittest.mock.patch.object(store_module.os,'environ',env), \
         unittest.mock.patch.object(BtApiStore,'_resolve_provider',forbidden), \
         unittest.mock.patch.object(BtApiStore,'_apply_env_gateway_overrides',forbidden), \
         unittest.mock.patch.object(BtApiStore,'_create_forwarding_client',forbidden), \
         unittest.mock.patch.object(store_module,'_resolve_bt_api_client',forbidden):
        try:
            BtApiStore(provider=provider,backend=backend,api=api,api_cls=api_cls,config=config,
                       account_actor_port=actor,account_actor_context=context,
                       account_actor_test_ledger=context,autostart=True)
        except BtApiStoreError as exc:
            result=str(exc)
        else: result='UNEXPECTED_SUCCESS'
    checks={'env_reads':env.reads,'api_reads':api.reads,'api_cls_reads':api_cls.reads,
            'actor_reads':actor.reads,'context_reads':context.reads,'credential_reads':credential.reads,
            'resolver_calls':resolver}
    print(label,'result=',result,'checks=',checks)
    assert result=='external account actor unavailable', (label,result)
    assert all(not v for v in checks.values()), (label,checks)

run_explicit('provider_ctp_direct','ctp','direct',{'execution_authorization_secret':None})
run_explicit('provider_ctp_gateway','ctp_gateway','gateway',{'execution_authorization_secret':None})
run_explicit('provider_ctp_forwarding','ctp','forwarding',{'execution_authorization_secret':None})
run_explicit('nested_ctp_forwarding','okx','forwarding',{'exchange_kwargs':{'CTP':{}}})

# Ambiguous generic btapi remains rejected; only the two route environment selectors are read.
env=StrictEnvironmentProbe({'BT_STORE_PROVIDER':'okx','BT_GATEWAY_EXCHANGE_TYPE':None})
api=Trap('ambiguous-api'); credential=Trap('ambiguous-credential'); adapter=Trap('ambiguous-adapter')
def forbidden(*a,**kw): raise AssertionError('ambiguous btapi local resolver reached')
with unittest.mock.patch.object(store_module.os,'environ',env), \
     unittest.mock.patch.object(BtApiStore,'_resolve_provider',forbidden), \
     unittest.mock.patch.object(BtApiStore,'_apply_env_gateway_overrides',forbidden), \
     unittest.mock.patch.object(store_module,'_resolve_bt_api_client',forbidden):
    try: BtApiStore(provider='btapi',api=api,config={'execution_authorization_secret':credential},managed_execution_adapter=adapter,autostart=True)
    except BtApiStoreError as exc: result=str(exc)
    else: result='UNEXPECTED_SUCCESS'
print('ambiguous_btapi result=',result,'env_reads=',env.reads,'api_reads=',api.reads,'credential_reads=',credential.reads,'adapter_reads=',adapter.reads)
assert result=='store route ambiguous' and env.reads==['BT_STORE_PROVIDER','BT_GATEWAY_EXCHANGE_TYPE']
assert api.reads==credential.reads==adapter.reads==[]

# An arbitrary custom route object must not be traversed; ambiguity remains fail-closed.
route=Trap('custom-route'); env=StrictEnvironmentProbe({}) ; api=Trap('custom-api'); actor=Trap('custom-actor')
with unittest.mock.patch.object(store_module.os,'environ',env), \
     unittest.mock.patch.object(BtApiStore,'_resolve_provider',forbidden), \
     unittest.mock.patch.object(BtApiStore,'_apply_env_gateway_overrides',forbidden), \
     unittest.mock.patch.object(BtApiStore,'_create_forwarding_client',forbidden), \
     unittest.mock.patch.object(store_module,'_resolve_bt_api_client',forbidden):
    try: BtApiStore(provider='okx',backend='forwarding',config=route,api=api,account_actor_port=actor,autostart=True)
    except BtApiStoreError as exc: result=str(exc)
    else: result='UNEXPECTED_SUCCESS'
print('custom_route result=',result,'custom_reads=',route.reads,'env_reads=',env.reads,'api_reads=',api.reads,'actor_reads=',actor.reads)
assert result=='store route ambiguous' and route.reads==api.reads==actor.reads==[]

# Non-CTP raw API remains injectable; the object is preserved without attribute reads.
class SafeAPI: pass
safe=SafeAPI(); env=StrictEnvironmentProbe({})
with unittest.mock.patch.object(store_module.os,'environ',env):
    store=BtApiStore(provider='okx',api=safe,config={'exchange_type':'OKX'})
print('okx_positive route=',store._candidate_route_kind,'same_api=',store._api is safe,'env_reads=',env.reads)
assert store._api is safe and str(store._candidate_route_kind).endswith('NON_CTP')

loaded=sorted(n for n in sys.modules if n=='bt_api_py' or n.startswith('bt_api_py.') or n in {'_ctp','ctp_wrap'})
print('sdk_native_modules_loaded=',loaded)
assert not loaded
print('INDEPENDENT_ACCESS_ORDER_PROBE_OK')
