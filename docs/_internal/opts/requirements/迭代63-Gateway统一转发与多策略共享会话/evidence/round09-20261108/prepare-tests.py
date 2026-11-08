import ast,hashlib,json,subprocess
from pathlib import Path
T=Path('/tmp/iter63-r09-packaging-ySGAYCmv/final'); SDK=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py'); CTP=SDK/'bt_api/bt_api_ctp'; GW=SDK/'bt_api/bt_api_gateway'
ctp=['test_account_provider.py','test_ctp_g5_source_unification.py','test_ctp_position_evidence.py','test_iter63_gateway_session.py','test_account_provider_execution_observations.py','test_ctp_native_query_certificate.py','test_iter62_account_facts_real_client.py','test_iter62_instrument_positions.py','test_iter62_query_slot.py','test_ctp_callback_ingress_client.py']
sdk=['unit/test_iter63_gateway_dual_ports.py','integration/test_iter63_gateway_dual_ports.py','unit/test_iter63_gateway_direct_service.py','integration/test_iter63_gateway_direct_service.py','unit/test_service_config.py','unit/test_service_config_cfg05_acceptance.py','unit/test_service_host.py','unit/test_service_host_integration.py','test_iter63_ctp_gateway_trading.py','integration/test_iter63_ctp_gateway_trading.py','unit/test_iter63_gateway_operator_trading_owner.py','integration/test_iter63_gateway_operator_trading_owner.py']
fallback=['unit/test_ctp_order_target_query.py','unit/test_ctp_terminal_order_query.py','unit/test_ctp_zero_fill_tracked_order.py','unit/test_ctp_managed_cancel_port.py']
manifest=[]
def copy(src,dst):
 b=src.read_bytes(); dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(b); manifest.append({'source':str(src),'copy':str(dst),'sha256':hashlib.sha256(b).hexdigest()})
raw=subprocess.check_output(['git','-C',str(GW),'ls-files','-z','--cached','--others','--exclude-standard','--','tests']).decode().split('\0')
for rel in sorted({p for p in raw if p.endswith('.py')}): copy(GW/rel,T/'gateway-tests'/rel)
(T/'gateway-tests'/'selected-tests.txt').write_text('tests\n')
for rel in ctp+['conftest.py','test_iter62_settlement_readback_on_write.py']:
 if (CTP/'tests'/rel).is_file(): copy(CTP/'tests'/rel,T/'install/tests'/rel)
(T/'ctp-selected.txt').write_text('\n'.join('tests/'+x for x in ctp)+'\n')
root=T/'sdk-tests'; dest=root/'tests'; dest.mkdir(parents=True,exist_ok=True)
for rel in set(sdk+fallback+['__init__.py','conftest.py','conftest_test_data.py','unit/__init__.py','unit/conftest.py','integration/__init__.py','integration/conftest.py']):
 src=SDK/'tests'/rel
 if src.is_file(): copy(src,dest/rel)
# Two selected SDK tests dynamically calculate this public CTP helper path.
helper=CTP/'tests/test_iter62_settlement_readback_on_write.py'; copy(helper,root/'bt_api/bt_api_ctp/tests'/helper.name)
queue=list(root.rglob('*.py')); seen=set(); unresolved=set(); imports=set()
while queue:
 p=queue.pop()
 if p in seen: continue
 seen.add(p); tree=ast.parse(p.read_text(encoding='utf-8'),filename=str(p)); refs=set()
 for n in ast.walk(tree):
  if isinstance(n,ast.Import): refs.update(a.name for a in n.names if a.name.startswith(('tests.','test_')))
  elif isinstance(n,ast.ImportFrom) and n.level==0 and n.module:
   if n.module.startswith(('tests.','test_')): refs.add(n.module)
   elif n.module=='tests': refs.update('tests.'+a.name for a in n.names)
  elif isinstance(n,ast.Call) and n.args and isinstance(n.args[0],ast.Constant) and type(n.args[0].value) is str and isinstance(n.func,ast.Attribute) and n.func.attr=='import_module' and n.args[0].value.startswith(('tests.','test_')): refs.add(n.args[0].value)
 for name in refs:
  imports.add(name)
  if name.startswith('tests.'):
   rel=Path(*name.split('.')).with_suffix('.py'); src=SDK/rel; dst=root/rel
   if not src.is_file():
    if (SDK/Path(*name.split('.'))/'__init__.py').is_file(): continue
    unresolved.add(name); continue
  else:
   candidates=[p for p in (SDK/'tests/unit'/f'{name}.py',SDK/'tests'/f'{name}.py',SDK/'tests/integration'/f'{name}.py',CTP/'tests'/f'{name}.py') if p.is_file()]
   if len(candidates)!=1: unresolved.add(name); continue
   src=candidates[0]; dst=(root/src.relative_to(SDK)) if src.is_relative_to(SDK/'tests') else (root/'bt_api/bt_api_ctp/tests'/src.name)
  if not dst.exists(): copy(src,dst)
  queue.append(dst)
if unresolved: raise RuntimeError(('unresolved SDK helper imports',sorted(unresolved)))
(root/'imports.txt').write_text('\n'.join(sorted(imports))+'\n')
(root/'selected-tests.txt').write_text('\n'.join('tests/'+x for x in sdk)+'\n')
(root/'fallback-selected.txt').write_text('\n'.join('tests/'+x for x in fallback)+'\n')
(T/'test-manifest.json').write_text(json.dumps(sorted(manifest,key=lambda x:x['copy']),indent=2)+'\n')
print('gateway test files',len([x for x in manifest if '/gateway-tests/' in x['copy']]),'ctp',len([x for x in manifest if '/install/tests/' in x['copy']]),'sdk/helpers',len([x for x in manifest if '/sdk-tests/' in x['copy']]),'AST visited',len(seen),flush=True)
