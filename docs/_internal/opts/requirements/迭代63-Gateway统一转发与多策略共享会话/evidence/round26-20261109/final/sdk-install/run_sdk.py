import os,sys
from pathlib import Path
T=Path('/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl'); target=T/'install/src';root=T/'sdk-tests';boot=T/'bootstrap';ctp=root/'bt_api/bt_api_ctp/tests'
sys.path[:0]=list(map(str,(target,boot,root,root/'tests',root/'tests/unit',ctp)))
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1';os.environ['R26_CTP_STRUCTS']='1';os.environ['PYTHONPATH']=os.pathsep.join(map(str,(boot,target,root,root/'tests',root/'tests/unit',ctp)))
from origin_guard import audit,install as origin
from offline_guard import install as offline
origin('r26-sdk-installed');offline()
import bt_api_py,msgpack,importlib.metadata
assert Path(bt_api_py.__file__).resolve().is_relative_to(target.resolve()) and Path(msgpack.__file__).resolve().is_relative_to(target.resolve())
assert importlib.metadata.version('msgpack')=='1.2.4'
print('RUN_ID',os.environ['R26_ORIGIN_RUN'],'PID',os.getpid(),'PPID',os.getppid(),'SDK',bt_api_py.__file__,'MSGPACK',msgpack.__file__,flush=True)
import pytest
os.chdir(root);selectors=[str(root/line) for line in (root/'selected-tests.txt').read_text().splitlines() if line]
assert len(selectors)==42
code=pytest.main(['-q','-ra','-p','xdist.plugin','-p','no:cacheprovider','--rootdir',str(root),'--import-mode=importlib',*selectors])
assert audit();print('PARENT_ORIGIN_AUDIT_OK',flush=True);raise SystemExit(code)
