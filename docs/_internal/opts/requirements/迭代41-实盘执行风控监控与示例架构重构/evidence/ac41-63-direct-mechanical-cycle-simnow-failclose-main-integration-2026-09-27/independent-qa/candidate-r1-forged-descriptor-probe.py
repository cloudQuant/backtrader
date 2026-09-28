from __future__ import annotations
import importlib.util, json, sys
from pathlib import Path
root=Path.cwd()
sys.path.insert(0,str(root))
unit_path=root/'tests/unit/test_ctp_options_simnow_live_runner.py'
spec=importlib.util.spec_from_file_location('_qa_live_runner_tests',unit_path)
unit=importlib.util.module_from_spec(spec); sys.modules[spec.name]=unit; spec.loader.exec_module(unit)
class DescriptorTrap:
    def __init__(self):
        object.__setattr__(self,'lookups',[]); object.__setattr__(self,'calls',[])
    def __getattribute__(self,name):
        if name in {'buy','sell','cancel'}:
            object.__getattribute__(self,'lookups').append(name)
        return object.__getattribute__(self,name)
    @property
    def buy(self): raise AssertionError('buy descriptor accessed')
    @property
    def sell(self): raise AssertionError('sell descriptor accessed')
    @property
    def cancel(self): raise AssertionError('cancel descriptor accessed')
    def __getattr__(self,name): raise AssertionError(f'unexpected descriptor lookup: {name}')
# Constructor preserves broker opacity.
constructor_trap=DescriptorTrap()
unit._runner(broker=constructor_trap)
constructor_lookups=list(constructor_trap.lookups)
# A caller can provide a fake mapping/signature, but the default runner rejects it before broker lookup.
runner,_=unit._runner(); runner.preflight(); dispatch_trap=DescriptorTrap(); runner.broker=dispatch_trap
forged={'armed':True,'hmac_grant_configured':True,'signature_hmac_sha256':'forged','account_fingerprint':'acct-test-sha256','connection_generation':7}
try:
    runner.execute_preflighted(prices=dict.fromkeys(unit.SYMBOLS,10.0),execution_state=unit._execution_state(),execution_authorization=forged)
except unit.SimNowLiveRunnerBlocked as exc:
    runner_reason=str(exc)
else:
    raise AssertionError('forged runner authorization was accepted')
runner_lookups=list(dispatch_trap.lookups); runner_calls=list(dispatch_trap.calls)
# Generic MechanicalCycle rejects forged arm, both side submits, and forged pending cancel before lookups.
cycle_spec=importlib.util.spec_from_file_location('_qa_mechanical_cycle',root/'backtrader_runtime/_iteration41_l2_fixture/mechanical_cycle.py')
cycle_mod=importlib.util.module_from_spec(cycle_spec); sys.modules[cycle_spec.name]=cycle_mod; cycle_spec.loader.exec_module(cycle_mod)
cycle_trap=DescriptorTrap()
cycle=cycle_mod.MechanicalCycle(broker=cycle_trap,owner=object(),feeds={'F':object()},cycle_id='qa-forged')
constructor_cycle_lookups=list(cycle_trap.lookups)
methods={}
for operation,invoke in (
    ('arm',lambda:cycle.arm({'settlement_verified':True,'execution_authorization':{'armed':True}})),
    ('submit_buy',lambda:cycle._submit(cycle_mod.MechanicalLeg('F','buy',1.0,object()),intent_id='forged-buy',offset='open')),
    ('submit_sell',lambda:cycle._submit(cycle_mod.MechanicalLeg('F','sell',1.0,object()),intent_id='forged-sell',offset='open')),
    ('cancel',lambda:cycle.cancel_pending()),
):
    if operation=='cancel': cycle.pending_order=object()
    try: invoke()
    except cycle_mod.MechanicalCycleBlocked as exc: methods[operation]=str(exc)
    else: raise AssertionError(f'{operation} was accepted')
cycle_lookups=list(cycle_trap.lookups); cycle_calls=list(cycle_trap.calls)
loaded_native=sorted(name for name in sys.modules if name=='bt_api_ctp' or name.startswith('bt_api_ctp.'))
loaded_sdk=sorted(name for name in sys.modules if name=='bt_api_execution' or name.startswith('bt_api_execution.'))
result={'runner_constructor_descriptor_lookups':constructor_lookups,'forged_runner_rejection':runner_reason,'runner_descriptor_lookups':runner_lookups,'runner_calls':runner_calls,'cycle_constructor_descriptor_lookups':constructor_cycle_lookups,'cycle_rejections':methods,'cycle_descriptor_lookups':cycle_lookups,'cycle_calls':cycle_calls,'native_ctp_modules_loaded':loaded_native,'execution_sdk_modules_loaded':loaded_sdk,'network_or_provider_calls':0,'status':'PASS' if not (constructor_lookups or runner_lookups or runner_calls or constructor_cycle_lookups or cycle_lookups or cycle_calls or loaded_native or loaded_sdk) and runner_reason=='TRUSTED_EXECUTION_AUTHORIZATION_VERIFIER_UNAVAILABLE' and set(methods.values())=={'TRUSTED_MECHANICAL_DISPATCH_UNAVAILABLE'} else 'FAIL'}
print(json.dumps(result,indent=2,sort_keys=True))
if result['status']!='PASS': raise SystemExit(1)


