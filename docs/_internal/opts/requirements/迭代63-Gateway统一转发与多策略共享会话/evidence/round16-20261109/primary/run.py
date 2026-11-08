from pathlib import Path
import os,sys,json,importlib
OUT=Path('/tmp/iter63-r16-primary')
SDK=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
BT=SDK.parent/'backtrader'
KIND=os.environ['R16_KIND']
ROOT=SDK if KIND=='sdk' else SDK/'bt_api'/('bt_api_'+KIND)
BOOT=OUT/'bootstrap'
roots={name:SDK/'bt_api'/name/'src' for name in ('bt_api_base','bt_api_gateway','bt_api_ctp','bt_api_okx','bt_api_binance','bt_api_transport_zmq')}
roots.update({'bt_api_py':SDK,'backtrader':BT})
paths=[BOOT,ROOT,*roots.values(),SDK/'tests',SDK/'tests/unit',SDK/'tests/integration',SDK/'bt_api/bt_api_ctp/tests']
sys.path[:0]=[str(x) for x in paths]
os.environ['PYTHONPATH']=os.pathsep.join(map(str,paths))
os.environ['R16_CTP_STRUCTS']='1' if KIND in ('ctp','sdk') else '0'
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
from offline_guard import install
install()
def main():
    os.chdir(ROOT)
    for name,source in roots.items():
        mod=importlib.import_module(name)
        path=Path(mod.__file__).resolve()
        if not path.is_relative_to(source.resolve()): raise RuntimeError(('wrong source',name,str(path)))
        print('SOURCE',name,path,flush=True)
    import pytest
    selectors=json.loads((OUT/'selectors.json').read_text())[KIND]
    return pytest.main(['-q','-p','no:cacheprovider',*(['-p','xdist.plugin'] if KIND=='sdk' else []),'--rootdir',str(ROOT),'--import-mode='+('importlib' if KIND=='sdk' else 'prepend'),*selectors])
if __name__=='__main__': raise SystemExit(main())
