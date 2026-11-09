from pathlib import Path
import shutil
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');R=Path('/tmp/iter63-r21-install-20261109-QD2dgx3G');G=Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4');C=Path('/tmp/iter63-r26-ctp-acceptance-20261109-7xzFjES1')
for name in ('prepare.py','run.py','run_installed.py','verify.py','verify_commits.py','capture_selectors.py','relocate_ctp_tests.py'):
 s=(R/name).read_text().replace(str(R),str(T)).replace('R21_','R30_').replace('R21 ','R30 ').replace('/tmp/iter63-r21-primary/','/tmp/iter63-r30-primary/')
 if name=='prepare.py':
  a=s.index('def fixed():');b=s.index('\ndef plan(name):',a)
  fixed='''def fixed():
    old=Path('/tmp/iter63-r25-install-20261109-jsTH40Ui/wheels')
    expected={'bt_api_okx-':'2243f8427d282e53f08b50e88832b149dfde0729afcbd8b3e768eb7a81ce1c07', 'bt_api_binance-':'703f312d1889052293b49c390855f2df50d38084ced8a80029f4794ca6e1c5be', 'msgpack-':'a4b47ec7422bef149223786a87df80067ac65bfc7c0565e5cf1dfbdc40acee50'}
    if (T/'wheels').exists(): raise RuntimeError('wheels already exist')
    (T/'wheels').mkdir();rows=[]
    for prefix,digest in expected.items():
        source,=old.glob(prefix+'*.whl')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise RuntimeError(('fixed SHA mismatch',prefix))
        shutil.copyfile(source,T/'wheels'/source.name);rows.append({'source':str(source),'filename':source.name,'sha256':digest})
    (T/'fixed-wheels.json').write_text(json.dumps(rows,indent=2)+'\\n')
    print('FIXED_WHEELS',len(rows),flush=True)

'''
  s=s[:a]+fixed+s[b:]
  s=s.replace("allowed[BT].add('conftest.py')","allowed[BT].update({'conftest.py','pytest.ini'})")
  s=s.replace("queue.append(('bt', BT, copy('bt', BT, 'conftest.py')))","queue.append(('bt', BT, copy('bt', BT, 'conftest.py')))\n        if (BT/'pytest.ini').is_file(): copy('bt', BT, 'pytest.ini')")
  s=s.replace("allowed[CTP] |= set(ALLOWLISTS.get('tests', {}).get('ctp', []))", "allowed[CTP] |= set(ALLOWLISTS.get('tests', {}).get('ctp', []))\n    allowed[BT] |= set(ALLOWLISTS.get('tests', {}).get('bt', []))")
  s=s.replace("{'tests/unit/live_state/test_gateway_pending_cancel.py'}", "set(ALLOWLISTS.get('tests', {}).get('bt', []))")
 if name=='capture_selectors.py':s=s.replace("{'gateway', 'ctp', 'sdk'}","{'base', 'gateway', 'ctp', 'sdk', 'bt'}")
 if name=='run.py':
  s=s.replace("for kind in ('gateway', 'sdk'):","for kind in ('base', 'gateway', 'sdk', 'bt'):")
  s=s.replace("if len(wheels) != 4:","if len(wheels) != 3:").replace('expected four fixed wheels before build','expected three fixed wheels before build')
  s=s.replace("for kind in ('gateway', 'sdk')]])","for kind in ('base', 'gateway', 'sdk', 'bt')]])")
  s=s.replace("if len(wheels) != 6:","if len(wheels) != 7:").replace('expected four fixed plus two wheels before CTP build','expected three fixed plus four rebuilt wheels before CTP build')
  s=s.replace("if len(wheels) != 7:\n            raise RuntimeError(('expected four fixed and three rebuilt wheels'", "if len(wheels) != 8:\n            raise RuntimeError(('expected three fixed and five rebuilt wheels'")
  s=s.replace("env.update({'TMPDIR': str(T/'tmp'), 'PIP_NO_CACHE_DIR': '1',", "env.update({'TMPDIR': str(T/'tmp'), 'PIP_CONFIG_FILE': '/dev/null', 'PIP_NO_CACHE_DIR': '1',")
 if name=='verify.py':
  s=s.replace("'REBUILT' if staged in {'gateway','ctp','sdk'} else 'REUSED_R19'", "'REBUILT'")
  s=s.replace("names = {'bt_api_okx-':('bt_api_okx','bt_api_okx'), 'bt_api_binance-':('bt_api_binance','bt_api_binance')}", "names = {'bt_api_okx-':('bt_api_okx','bt_api_okx'), 'bt_api_binance-':('bt_api_binance','bt_api_binance'), 'msgpack-':('msgpack','msgpack')}")
  s=s.replace("(row['filename'].startswith(('back_trader_python-', 'bt_api_base-', 'bt_api_ctp-')))","(False)")
  s=s.replace("print('GAP_SDK_ISOLATED_MINUS_I_CHILD_NO_SITECUSTOMIZE see sdk-minus-i-audit-gap.md',flush=True)","print('GAP: Python -I and -S children may bypass sitecustomize',flush=True)")
 (T/name).write_text(s)
for source,name in ((C/'build_ctp_reuse.py','build_ctp_reuse.py'),(G/'guard_preflight.py','guard_preflight.py'),(G/'audit_run.py','audit_run.py'),(G/'capture_editable_deps.py','capture_editable_deps.py')):
 s=source.read_text().replace(str(C),str(T)).replace(str(G),str(T)).replace('R26_','R30_').replace('R29_','R30_');(T/name).write_text(s)
shutil.copytree(G/'bootstrap',T/'bootstrap',ignore=shutil.ignore_patterns('__pycache__'))
for p in (T/'bootstrap').glob('*.py'):p.write_text(p.read_text().replace(str(G),str(T)).replace('R29_','R30_'))
