from pathlib import Path
import json,shutil
T=Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4'); O=Path('/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl')
# Only scripts and guard code are copied; no source or test snapshot.
files=['setup_harness.py','launch_v2.py','run_sdk_v2.py','verify.py','guard_preflight.py','audit_run.py','capture_editable_deps.py']
for name in files:
 s=(O/name).read_text().replace(str(O),str(T)).replace('R26_','R29_').replace('r26-','r29-')
 if name=='setup_harness.py':
  s=s.replace("P=Path('/tmp/iter63-r29-sdk-acceptance')", "P=Path(os.environ.get('R29_FREEZE_DIR',str(T/'primary-freeze')))" ).replace("A=Path('/tmp/iter63-r29-ctp-acceptance-20261109-7xzFjES1')", "A=Path('/tmp/iter63-r26-ctp-acceptance-20261109-7xzFjES1')")
  s=s.replace('assert len(frozen)==55','assert frozen')
  s=s.replace('==42','==14').replace('R26 SDK 55 frozen input hashes checked; 42 SDK selectors; fixed CTP final','R29 SDK frozen inputs checked; 14 SDK selectors; fixed CTP final')
  s=s.replace("allowed={'bt_api_py/gateway_instrument_service.py','bt_api_py/gateway_instrument_spec_codec.py','bt_api_py/gateway_strategy_instrument.py','bt_api_py/gateway_settlement.py'}","allowed={'bt_api_py/gateway_api.py'}")
  s=s.replace("'back_trader_python-':'5b24542e50cfb5d78234a7345dad52e961531a5da5768c5870a576eb0d65c227',",'')
  s=s.replace("src,=(A/'wheels').glob('bt_api_ctp-*.whl');digest=", "src,=Path('/tmp/iter63-r28-candidate3-20261109-ijqQ26LC/wheels').glob('back_trader_python-*.whl');digest='3435b1df02d50bdb5a6135605a86cc6de4b8a85c715d13885a8c04e7a7ba6981'\n if sha(src)!=digest:raise RuntimeError('R28 BT wheel hash mismatch')\n shutil.copyfile(src,T/'wheels'/src.name);rows.append({'source':str(src),'filename':src.name,'sha256':digest})\n src,=(A/'wheels').glob('bt_api_ctp-*.whl');digest=")
 if name=='launch_v2.py':s=s.replace("'sdk-installed':'run_sdk.py'","'sdk-installed':'run_sdk_v2.py'")
 if name=='run_sdk_v2.py':s=s.replace('==42','==14')
 if name=='verify.py':s=s.replace("print('PRIMARY_FROZEN_INPUTS_OK',55)","print('PRIMARY_FROZEN_INPUTS_OK',len(json.loads((T/'sdk-frozen-inputs.json').read_text())))")
 (T/name).write_text(s)
shutil.copytree(O/'bootstrap',T/'bootstrap',ignore=shutil.ignore_patterns('__pycache__'))
for p in (T/'bootstrap').glob('*.py'):p.write_text(p.read_text().replace(str(O),str(T)).replace('R26_','R29_').replace('r26-','r29-'))
selectors=['tests/unit/test_iter63_gateway_api.py','tests/integration/test_iter63_gateway_api_process.py','tests/test_mig01_gateway_entrypoints_retired.py','tests/unit/test_iter63_gateway_strategy_client.py','tests/integration/test_iter63_gateway_strategy_client.py','tests/integration/test_iter63_strategy_read_session.py','tests/unit/test_iter63_gateway_cancel_client.py','tests/unit/test_iter63_gateway_strategy_instrument.py','tests/unit/test_iter63_gateway_direct_client.py','tests/unit/test_gateway_strategy_market.py','tests/unit/test_gateway_strategy_account.py','tests/unit/test_iter63_gateway_execution_stream_client.py','tests/unit/test_iter63_async_market_client.py','tests/unit/test_iter63_service_runtime_thread.py']
(T/'selectors-DRAFT.json').write_text(json.dumps({'sdk':selectors},indent=2)+'\n')
