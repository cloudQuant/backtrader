"""Run one frozen copied suite against the isolated wheel target."""
import os
import sys
import tempfile
import time
from pathlib import Path

T = Path('/tmp/iter63-r13-packaging-gjjgT6GX').resolve()
TARGET, BOOT = T/'install/src', T/'bootstrap'
kind = os.environ.get('R13_TEST_KIND')
if kind not in {'ctp', 'gateway', 'sdk'}:
    raise RuntimeError('R13_TEST_KIND invalid')
os.environ['R13_CTP_STRUCTS'] = '1' if kind in {'sdk', 'ctp'} else '0'
ROOT = T/'install' if kind == 'ctp' else T/(kind+'-tests')
extra = [ROOT/'tests', ROOT/'tests/unit', ROOT/'tests/integration', ROOT/'bt_api/bt_api_ctp/tests']
sys.path[:0] = [str(TARGET), str(BOOT), str(ROOT), *[str(x) for x in extra]]
if __name__ == '__main__':
    os.environ['R13_ORIGIN_RUN'] = kind+'-'+str(os.getpid())+'-'+str(time.time_ns())
from origin_guard import audit, install
from offline_guard import install as install_offline
install('__main__' if __name__ == '__main__' else 'multiprocessing-spawn-main')
install_offline()

def main():
    temporary_root = T/'tmp'
    temporary_root.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(temporary_root)
    tempfile.tempdir = str(temporary_root)
    os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    os.environ['PYTHONPATH'] = os.pathsep.join((str(BOOT), str(TARGET), str(ROOT), *map(str, extra)))
    print('ORIGIN_RUN_LOGS', T/'origin-logs'/os.environ['R13_ORIGIN_RUN'], flush=True)
    print('GUARDS Python socket/zmq loopback only; CTP factory entrypoints blocked', flush=True)
    print('CTP_EXTENSION', 'loaded for structs/measurement' if kind in {'sdk', 'ctp'} else 'blocked', flush=True)
    import backtrader, bt_api_py, bt_api_base, bt_api_gateway, bt_api_ctp, bt_api_okx, bt_api_binance, pytest
    for module in (backtrader, bt_api_py, bt_api_base, bt_api_gateway, bt_api_ctp, bt_api_okx, bt_api_binance):
        path = Path(module.__file__).resolve()
        if not path.is_relative_to(TARGET):
            raise RuntimeError(('PROJECT_IMPORT_OUTSIDE_TARGET', module.__name__))
        print('INSTALLED_TEST_PACKAGE', module.__name__, path, flush=True)
    paths = [str(ROOT/line) for line in (ROOT/'selected-tests.txt').read_text().splitlines() if line]
    os.chdir(ROOT)
    import_mode = 'prepend' if kind in {'gateway', 'ctp'} else 'importlib'
    code = pytest.main(['-q', '-p', 'no:cacheprovider', '--rootdir', str(ROOT),
                        '--import-mode='+import_mode, *sys.argv[1:], *paths])
    if not audit():
        raise RuntimeError('PARENT_ORIGIN_AUDIT_FAILED')
    print('PARENT_ORIGIN_AUDIT_OK', flush=True)
    return code
if __name__ == '__main__':
    raise SystemExit(main())
