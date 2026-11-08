"""Run one declared source suite with lazy origin and offline guards."""
import json
import os
import sys
import time
from pathlib import Path
OUT=Path('/tmp/iter63-r17-primary')
SDK=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
BT=SDK.parent/'backtrader'
KIND=os.environ['R17_KIND']
if KIND not in {'base','gateway','ctp','sdk','bt'}:
    raise ValueError('invalid R17_KIND')
ROOT=BT if KIND=='bt' else SDK if KIND=='sdk' else SDK/'bt_api'/('bt_api_'+KIND)
BOOT=OUT/'bootstrap'
roots=[SDK/'bt_api'/name/'src' for name in ('bt_api_base','bt_api_gateway','bt_api_ctp','bt_api_okx','bt_api_binance','bt_api_transport_zmq')]
roots.extend([SDK,BT])
extra=[ROOT/'tests',ROOT/'tests/unit',ROOT/'tests/integration',SDK/'bt_api/bt_api_ctp/tests']
paths=[BOOT,ROOT,*roots,*extra]
sys.path[:0]=list(map(str,paths))
os.environ['PYTHONPATH']=os.pathsep.join(map(str,paths))
os.environ['R17_CTP_STRUCTS']='1' if KIND in ('ctp','sdk','bt') else '0'
os.environ['R17_ORIGIN_RUN']=KIND+'-'+str(os.getpid())+'-'+str(time.time_ns())
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
os.environ['BT_SKIP_PYTEST_TMP_CLEANUP']='1'
from origin_guard import audit, install as install_origin
from offline_guard import install as install_offline
install_origin('source-runner')
install_offline()
def main():
    os.chdir(ROOT)
    plan=Path(os.environ.get('R17_SELECTORS',str(OUT/'selectors.json')))
    selectors=json.loads(plan.read_text())[KIND]
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
    code=pytest.main(['-q','-p','no:cacheprovider',*plugins,'--rootdir',str(ROOT),'--import-mode='+mode,*selectors])
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
    raise SystemExit(main())
