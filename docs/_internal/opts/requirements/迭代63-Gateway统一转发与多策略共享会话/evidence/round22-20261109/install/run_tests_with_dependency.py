"""Run frozen tests against installed target, with origin and offline guards."""
import json,os,sys
from pathlib import Path
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv');target=T/'install';tests=T/'test/tests';boot=T/'bootstrap'
sys.path[:0]=[str(target),str(boot),str(tests)]
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
os.environ['PYTHONPATH']=os.pathsep.join(map(str,(boot,target,tests)))
os.environ['R22_CTP_STRUCTS']='0'
from origin_guard import audit,install as install_origin
from offline_guard import install as install_offline
install_origin('r22-installed-tests');install_offline()
import bt_api_base,bt_api_gateway
assert Path(bt_api_base.__file__).resolve().is_relative_to(target.resolve())
assert Path(bt_api_gateway.__file__).resolve().is_relative_to(target.resolve())
print('ORIGIN_RUN_ID',os.environ['R22_ORIGIN_RUN'],'PID',os.getpid(),'PPID',os.getppid(),flush=True)
import importlib.metadata
import msgpack
from packaging.version import Version
if not Path(msgpack.__file__).resolve().is_relative_to(target.resolve()): raise RuntimeError('msgpack outside isolated target')
version=importlib.metadata.version('msgpack')
if Version(version)<Version('1.1'): raise RuntimeError('msgpack version below declared minimum')
print('MSGPACK_DEPENDENCY',version,msgpack.__file__,flush=True)
import pytest
os.chdir(T/'test')
paths=[str(T/'test'/p) for p in json.loads((T/'selectors.json').read_text())]
code=pytest.main(['-q','-ra','-p','no:cacheprovider','--rootdir',str(T/'test'),*paths])
if not audit(): raise RuntimeError('project origin audit failed')
print('PARENT_ORIGIN_AUDIT_OK',flush=True)
raise SystemExit(code)
