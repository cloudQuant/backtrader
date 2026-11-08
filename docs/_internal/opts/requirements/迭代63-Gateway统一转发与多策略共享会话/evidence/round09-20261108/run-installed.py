import os,sys,time
from pathlib import Path
T=Path('/tmp/iter63-r09-packaging-ySGAYCmv/final').resolve(); TARGET=T/'install/src'; BOOT=T/'bootstrap'
kind=os.environ.get('R09_TEST_KIND')
if kind not in ('gateway','ctp','sdk','sdk_fallback'): raise RuntimeError('R09_TEST_KIND invalid')
ROOT={'gateway':T/'gateway-tests','ctp':T/'install','sdk':T/'sdk-tests','sdk_fallback':T/'sdk-tests'}[kind]
extra=[ROOT/'tests',ROOT/'tests/unit',ROOT/'bt_api/bt_api_ctp/tests']
sys.path[:0]=[str(TARGET),str(BOOT),str(ROOT),*[str(x) for x in extra]]
if __name__=='__main__': os.environ['R09_ORIGIN_RUN']=kind+'-'+str(os.getpid())+'-'+str(time.time_ns())
from origin_guard import audit,install
install('__main__' if __name__=='__main__' else 'multiprocessing-spawn-main')
if kind=='sdk_fallback':
 os.environ['R09_FAKE_NATIVE']='1'
 from fake_native import install as fake
 fake()
def main():
 os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'; os.environ['PYTHONPATH']=os.pathsep.join((str(BOOT),str(TARGET),str(ROOT),*[str(x) for x in extra]))
 print('ORIGIN_RUN_LOGS',T/'origin-logs'/os.environ['R09_ORIGIN_RUN'],flush=True)
 import backtrader,bt_api_py,bt_api_base,bt_api_gateway,bt_api_ctp,bt_api_okx,bt_api_binance,pytest
 for module in (backtrader,bt_api_py,bt_api_base,bt_api_gateway,bt_api_ctp,bt_api_okx,bt_api_binance):
  p=Path(module.__file__).resolve(); assert p.is_relative_to(TARGET); print('INSTALLED_TEST_PACKAGE',module.__name__,p,flush=True)
 plan={'gateway':ROOT/'selected-tests.txt','ctp':T/'ctp-selected.txt','sdk':ROOT/'selected-tests.txt','sdk_fallback':ROOT/'fallback-selected.txt'}[kind]
 paths=[str(ROOT/p) for p in plan.read_text().splitlines() if p]
 code=pytest.main(['-q','--import-mode=importlib',*sys.argv[1:],*paths])
 assert audit(); print('PARENT_ORIGIN_AUDIT_OK',flush=True); return code
if __name__=='__main__': raise SystemExit(main())
