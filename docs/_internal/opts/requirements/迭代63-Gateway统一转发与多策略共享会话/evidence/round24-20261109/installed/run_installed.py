"""Run one frozen copied suite against the isolated wheel target."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

T = Path('/tmp/iter63-r24-install-20261109-fEuNyr35').resolve()
TARGET, BOOT = T/'install/src', T/'bootstrap'
kind = os.environ.get('R24_TEST_KIND')
if kind not in {'base', 'gateway', 'ctp', 'sdk', 'bt'}:
    raise RuntimeError('R24_TEST_KIND invalid')
os.environ['R24_CTP_STRUCTS'] = '1' if kind in {'ctp', 'sdk', 'bt'} else '0'
ROOT = T/'install' if kind == 'ctp' and os.environ.get('R24_CTP_RELOCATED') == '1' else T/(kind+'-tests')
extra = [ROOT/'tests', ROOT/'tests/unit', ROOT/'tests/integration', ROOT/'bt_api/bt_api_ctp/tests']
sys.path[:0] = [str(TARGET), str(BOOT), str(ROOT), *[str(x) for x in extra]]
if __name__ == '__main__':
    os.environ.setdefault('R24_ORIGIN_RUN',kind+'-'+str(os.getpid())+'-'+str(time.time_ns()))
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
    os.environ['BT_SKIP_PYTEST_TMP_CLEANUP'] = '1'
    os.environ['PYTHONPATH'] = os.pathsep.join((str(BOOT), str(TARGET), str(ROOT), *map(str, extra)))
    print('RUN_ID',os.environ['R24_ORIGIN_RUN'],'PID',os.getpid(),'PPID',os.getppid(),flush=True)
    print('ORIGIN_RUN_LOGS', T/'origin-logs'/os.environ['R24_ORIGIN_RUN'], flush=True)
    print('GUARDS Python socket/zmq loopback only; CTP factory entrypoints blocked', flush=True)
    print('CTP_EXTENSION', 'native structs allowed on demand; factories blocked' if kind in {'ctp', 'sdk', 'bt'} else 'extension blocked', flush=True)
    if kind == 'base':
        import importlib.machinery
        import types
        module = types.ModuleType('tests')
        module.__path__ = [str(ROOT/'tests')]
        module.__spec__ = importlib.machinery.ModuleSpec('tests', loader=None, is_package=True)
        module.__spec__.submodule_search_locations = module.__path__
        sys.modules['tests'] = module
        print('BASE_TEST_NAMESPACE_ROOT', module.__path__[0], flush=True)
    import importlib.metadata
    import msgpack
    version=importlib.metadata.version('msgpack')
    if version!='1.2.4' or not Path(msgpack.__file__).resolve().is_relative_to(TARGET.resolve()): raise RuntimeError('MSGPACK_TARGET_REQUIRED')
    print('TEMP_MSGPACK',version,msgpack.__file__,flush=True)
    import pytest
    paths = [str(ROOT/line) for line in (ROOT/'selected-tests.txt').read_text().splitlines() if line]
    os.chdir(ROOT)
    import_mode = 'prepend' if kind in {'base', 'gateway', 'ctp'} else 'importlib'
    plugins = ['-p', 'xdist.plugin'] + (['-p', 'pytest_asyncio.plugin'] if kind == 'base' else [])
    code = pytest.main(['-q', '-ra', '-p', 'no:cacheprovider', *plugins, '--rootdir', str(ROOT),
                        '--import-mode='+import_mode, *sys.argv[1:], *paths])
    if kind == 'base':
        test_root = (ROOT/'tests').resolve()
        helpers = {name: str(Path(module.__file__).resolve()) for name, module in tuple(sys.modules.items())
                   if name.startswith('tests.') and module is not None and getattr(module, '__file__', None)}
        if any(not Path(path).is_relative_to(test_root) for path in helpers.values()):
            raise RuntimeError('BASE_TEST_HELPER_OUTSIDE_SNAPSHOT')
        print('BASE_TEST_HELPER_ORIGINS', json.dumps(helpers, sort_keys=True), flush=True)
    if not audit():
        raise RuntimeError('PARENT_ORIGIN_AUDIT_FAILED')
    print('PARENT_ORIGIN_AUDIT_OK', flush=True)
    return code
if __name__ == '__main__':
    raise SystemExit(main())
