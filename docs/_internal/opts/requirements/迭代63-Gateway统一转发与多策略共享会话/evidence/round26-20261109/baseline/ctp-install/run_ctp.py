"""Run frozen CTP tests only against isolated wheels and offline guards."""
import json,os,sys
from pathlib import Path
T=Path('/tmp/iter63-r26-ctp-install-20261109-sqM3vqAE');target=T/'install/src';root=T/'install';boot=T/'bootstrap'
sys.path[:0]=[str(target),str(boot),str(root),str(root/'tests')]
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1';os.environ['R26_CTP_STRUCTS']='1';os.environ['PYTHONPATH']=os.pathsep.join(map(str,(boot,target,root,root/'tests')))
from origin_guard import audit,install as origin
from offline_guard import install as offline
origin('r26-ctp-installed');offline()
import bt_api_ctp,bt_api_py,msgpack,importlib.metadata
for mod in (bt_api_ctp,bt_api_py,msgpack):
    if not Path(mod.__file__).resolve().is_relative_to(target.resolve()):raise RuntimeError(('package outside target',mod.__name__))
if importlib.metadata.version('msgpack')!='1.2.4':raise RuntimeError('wrong msgpack version')
print('RUN_ID',os.environ['R26_ORIGIN_RUN'],'PID',os.getpid(),'PPID',os.getppid(),'FIXED_SDK',bt_api_py.__file__,'MSGPACK',msgpack.__file__,flush=True)
import pytest
os.chdir(root);selectors=[str(root/line) for line in (root/'selected-tests.txt').read_text().splitlines() if line]
code=pytest.main(['-q','-ra','-p','no:cacheprovider','--rootdir',str(root),'--import-mode=prepend',*selectors])
if not audit():raise RuntimeError('origin audit failure')
print('PARENT_ORIGIN_AUDIT_OK',flush=True)
raise SystemExit(code)
