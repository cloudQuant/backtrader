import os,sys,time
from pathlib import Path
T=Path('/tmp/iter63-r08-packaging-j8KrE0I2').resolve(); TARGET=T/'target'; BOOT=T/'bootstrap'
kind=os.environ.get('R08_TEST_KIND')
if kind not in ('bt','sdk'): raise RuntimeError('R08_TEST_KIND must be bt or sdk')
ROOT=T/(kind+'-tests')
sys.path[:0]=[str(TARGET),str(BOOT),str(ROOT),str(ROOT/"tests/unit")]
if __name__=='__main__': os.environ['R08_ORIGIN_RUN']=kind+'-'+str(os.getpid())+'-'+str(time.time_ns())
from origin_guard import audit, install
install('__main__' if __name__=='__main__' else 'multiprocessing-spawn-main')
def main():
 os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'; os.environ['PYTHONPATH']=os.pathsep.join((str(BOOT),str(TARGET),str(ROOT),str(ROOT/"tests/unit")))
 print('ORIGIN_RUN_LOGS',T/'origin-logs'/os.environ['R08_ORIGIN_RUN'],flush=True)
 import backtrader,bt_api_py,bt_api_base,bt_api_gateway,bt_api_ctp,bt_api_okx,bt_api_binance,pytest
 for module in (backtrader,bt_api_py,bt_api_base,bt_api_gateway,bt_api_ctp,bt_api_okx,bt_api_binance):
  p=Path(module.__file__).resolve(); assert p.is_relative_to(TARGET); print('INSTALLED_TEST_PACKAGE',module.__name__,p,flush=True)
 paths=[str(ROOT/p) for p in (ROOT/'selected-tests.txt').read_text().splitlines() if p]
 code=pytest.main(['-q','--import-mode=importlib',*sys.argv[1:],*paths])
 assert audit(); print('PARENT_ORIGIN_AUDIT_OK',flush=True); return code
if __name__=='__main__': raise SystemExit(main())
