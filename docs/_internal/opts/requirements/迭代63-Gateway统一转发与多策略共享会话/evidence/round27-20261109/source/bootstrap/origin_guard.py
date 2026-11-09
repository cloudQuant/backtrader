"""Audit source origins lazily in parent and spawned child processes."""
import atexit
import importlib.abc
import importlib.machinery
import json
import multiprocessing.util
import os
from pathlib import Path
import sys
SDK = Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
BT = SDK.parent/'backtrader'
ROOTS = {name: (SDK/'bt_api'/name/'src').resolve() for name in (
    'bt_api_base','bt_api_gateway','bt_api_ctp','bt_api_okx','bt_api_binance','bt_api_transport_zmq')}
ROOTS.update({'bt_api_py': SDK.resolve(), 'backtrader': BT.resolve()})
TARGET = ROOTS['bt_api_ctp']
LOG = Path('/tmp/iter63-r27-primary/origin-logs') / os.environ.get('R27_ORIGIN_RUN', 'unbound')
LOG.mkdir(parents=True, exist_ok=True)
def write(event, data):
    with (LOG/f'{os.getpid()}.jsonl').open('a', encoding='utf-8') as output:
        output.write(json.dumps({'event':event,'pid':os.getpid(),'ppid':os.getppid(),'run_id':os.environ.get('R27_ORIGIN_RUN','unbound'),'data':data},sort_keys=True)+'\n')
def owner(name):
    return next((root for prefix,root in ROOTS.items() if name == prefix or name.startswith(prefix+'.')), None)
def audit(event='audit-ok'):
    observed={}
    for name,module in tuple(sys.modules.items()):
        root=owner(name)
        origin=getattr(module,'__file__',None) if module else None
        if root is not None and origin:
            path=Path(origin).resolve()
            if not path.is_relative_to(root):
                write('VIOLATION',{'module':name,'origin':str(path)})
                return False
            observed[name]=str(path)
    write(event,observed)
    return True
class SourceFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root=owner(fullname)
        if root is None:
            return None
        spec=importlib.machinery.PathFinder.find_spec(fullname,path)
        if spec is None:
            raise ModuleNotFoundError('source module unavailable: '+fullname, name=fullname)
        if spec.origin is not None and not Path(spec.origin).resolve().is_relative_to(root):
            raise ImportError('module outside declared source: '+fullname)
        if spec.origin is None and spec.submodule_search_locations is not None and any(
            not Path(location).resolve().is_relative_to(root) for location in spec.submodule_search_locations
        ):
            raise ImportError('namespace outside declared source: '+fullname)
        write('resolved', {'module':fullname,'origin':spec.origin})
        return spec
def install(mode):
    if any(isinstance(finder,SourceFinder) for finder in sys.meta_path):
        return
    if not audit('preexisting-audit-ok'):
        raise ImportError('preexisting module outside declared source')
    sys.meta_path.insert(0,SourceFinder())
    write('guard-installed',{'mode':mode})
    atexit.register(audit)
    multiprocessing.util.Finalize(None,audit,exitpriority=0)
