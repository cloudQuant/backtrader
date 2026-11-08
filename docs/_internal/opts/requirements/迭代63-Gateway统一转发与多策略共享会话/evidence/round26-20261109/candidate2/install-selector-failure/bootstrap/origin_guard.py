"""Test-only guard: seven installed project packages must come from target."""
import atexit
import importlib.abc
import importlib.machinery
import json
import multiprocessing.util
import os
from pathlib import Path
import sys

TARGET = Path('/tmp/iter63-r26-ctp-final-20261109-dNXJaiAJ/install/src').resolve()
LOG = Path('/tmp/iter63-r26-ctp-final-20261109-dNXJaiAJ/origin-logs') / os.environ.get('R26_ORIGIN_RUN', 'unbound')
LOG.mkdir(parents=True, exist_ok=True)
PACKAGES = ('backtrader', 'bt_api_base', 'bt_api_gateway', 'bt_api_py', 'bt_api_ctp', 'bt_api_okx', 'bt_api_binance')


def tracked(name):
    return any(name == prefix or name.startswith(prefix + '.') for prefix in PACKAGES)


def write(event, data):
    with (LOG / f'{os.getpid()}.jsonl').open('a', encoding='utf-8') as output:
        output.write(json.dumps({'event': event, 'pid': os.getpid(), 'ppid': os.getppid(), 'run_id': os.environ.get('R26_ORIGIN_RUN', 'unbound'), 'data': data}, sort_keys=True) + '\n')


class TargetFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if not tracked(fullname): return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None: raise ModuleNotFoundError('target module unavailable: ' + fullname, name=fullname)
        if spec.origin is not None:
            if not Path(spec.origin).resolve().is_relative_to(TARGET):
                raise ImportError('module outside target: ' + fullname)
        elif spec.submodule_search_locations is not None:
            if any(not Path(item).resolve().is_relative_to(TARGET) for item in spec.submodule_search_locations):
                raise ImportError('namespace outside target: ' + fullname)
        write('resolved', {'module': fullname, 'origin': spec.origin})
        return spec


def audit(event='audit-ok'):
    observed = {}
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, '__file__', None) if module is not None else None
        if tracked(name) and origin:
            resolved = Path(origin).resolve()
            if not resolved.is_relative_to(TARGET):
                write('VIOLATION', {'module': name, 'origin': str(resolved)})
                return False
            observed[name] = str(resolved)
    write(event, observed)
    return True


def install(mode):
    if not any(isinstance(finder, TargetFinder) for finder in sys.meta_path):
        if not audit('preexisting-audit-ok'):
            raise ImportError('preexisting project module outside target')
        sys.meta_path.insert(0, TargetFinder())
        write('guard-installed', {'mode': mode, 'target': str(TARGET)})
        atexit.register(audit)
        # multiprocessing children may exit via os._exit, bypassing atexit.
        multiprocessing.util.Finalize(None, audit, exitpriority=0)
