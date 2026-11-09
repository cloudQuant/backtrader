"""Run one declared source suite with lazy origin and offline guards."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path
for key in tuple(os.environ):
    if key.startswith(('CTP_', 'OKX_', 'BINANCE_', 'HTX_', 'IB_')):
        os.environ.pop(key, None)
OUT=Path('/tmp/iter63-r29-primary')
SDK=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
BT=SDK.parent/'backtrader'
KIND=os.environ['R29_KIND']
if KIND not in {'gateway','ctp','sdk','bt'}:
    raise ValueError('invalid R29_KIND')
ROOT=BT if KIND=='bt' else SDK if KIND=='sdk' else SDK/'bt_api'/('bt_api_'+KIND)
BOOT=OUT/'bootstrap'
roots=[SDK/'bt_api'/name/'src' for name in ('bt_api_base','bt_api_gateway','bt_api_ctp','bt_api_okx','bt_api_binance','bt_api_transport_zmq')]
roots.extend([SDK,BT])
extra=[ROOT/'tests',ROOT/'tests/unit',ROOT/'tests/integration',SDK/'bt_api/bt_api_ctp/tests']
paths=[BOOT,ROOT,*roots,*extra]
sys.path[:0]=list(map(str,paths))
os.environ['PYTHONPATH']=os.pathsep.join(map(str,paths))
os.environ['R29_CTP_STRUCTS']='1' if KIND in ('ctp','sdk','bt') else '0'
if __name__ == '__main__':
    os.environ['R29_ORIGIN_RUN']=KIND+'-'+str(os.getpid())+'-'+str(time.time_ns())
elif not os.environ.get('R29_ORIGIN_RUN'):
    raise RuntimeError('spawned source process missing parent run id')
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
os.environ['BT_SKIP_PYTEST_TMP_CLEANUP']='1'
from origin_guard import audit, install as install_origin
from offline_guard import install as install_offline
install_origin('source-runner')
install_offline()
def main():
    os.chdir(ROOT)
    if not (OUT/'SOURCE_FROZEN').is_file(): raise RuntimeError('SOURCE_FREEZE required')
    plan=Path(os.environ.get('R29_SELECTORS',str(OUT/'selectors.json')))
    selectors=json.loads(plan.read_text())[KIND]
    print('RUN_METADATA',json.dumps({'run_id':os.environ['R29_ORIGIN_RUN'],'pid':os.getpid(),'ppid':os.getppid(),'selector_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),'argv':sys.orig_argv,'origin_log_group':os.environ['R29_ORIGIN_RUN']},sort_keys=True),flush=True)
    print('SOURCE_ROOT',KIND,ROOT,'SELECTORS',plan,flush=True)
    print('LAZY_ORIGIN_AND_OFFLINE_GUARDS active; CTP native factories blocked',flush=True)
    if KIND == 'base':
        import importlib.machinery
        import types
        module=types.ModuleType('tests')
        module.__path__=[str(ROOT/'tests')]
        module.__spec__=importlib.machinery.ModuleSpec('tests',loader=None,is_package=True)
        module.__spec__.submodule_search_locations=module.__path__
        sys.modules['tests']=module
        print('BASE_TEST_NAMESPACE_ROOT',module.__path__[0],flush=True)
    import pytest
    plugins=['-p','xdist.plugin'] if KIND=='sdk' else ['-p','pytest_asyncio.plugin'] if KIND=='base' else []
    mode='importlib' if KIND in {'sdk','bt'} else 'prepend'
    code=pytest.main(['-q','-ra','--junitxml='+str(OUT/(KIND+'-source.xml')),'-p','no:cacheprovider',*plugins,'--rootdir',str(ROOT),'--import-mode='+mode,*selectors])
    if KIND == 'base':
        test_root=(ROOT/'tests').resolve()
        helpers={name:str(Path(module.__file__).resolve()) for name,module in tuple(sys.modules.items())
                 if name.startswith('tests.') and module is not None and getattr(module,'__file__',None)}
        if any(not Path(path).is_relative_to(test_root) for path in helpers.values()):
            raise RuntimeError('BASE_TEST_HELPER_OUTSIDE_SOURCE')
        print('BASE_TEST_HELPER_ORIGINS',json.dumps(helpers,sort_keys=True),flush=True)
    if not audit('explicit-audit-ok'):
        raise RuntimeError('SOURCE_ORIGIN_AUDIT_FAILED')
    print('SOURCE_ORIGIN_AUDIT_OK',flush=True)
    return code
if __name__=='__main__':
    started=time.time_ns(); code=1
    try:
        code=main()
    finally:
        plan=Path(os.environ.get('R29_SELECTORS',str(OUT/'selectors.json')))
        record={'run_id':os.environ['R29_ORIGIN_RUN'],'pid':os.getpid(),'ppid':os.getppid(),
                'kind':KIND,'argv':sys.orig_argv,'selector_sha256':hashlib.sha256(plan.read_bytes()).hexdigest() if plan.is_file() else None,
                'started_ns':started,'finished_ns':time.time_ns(),'exit_code':code}
        with (OUT/'source-executions.jsonl').open('a',encoding='utf-8') as stream: stream.write(json.dumps(record,sort_keys=True)+'\n')
        print('RUN_EXIT',code,'RUN_ID',os.environ['R29_ORIGIN_RUN'],flush=True)
    raise SystemExit(code)
