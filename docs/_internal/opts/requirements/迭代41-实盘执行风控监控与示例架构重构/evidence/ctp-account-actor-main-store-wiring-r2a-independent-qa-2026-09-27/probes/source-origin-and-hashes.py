import hashlib,json,pathlib,platform,sys
import pytest,backtrader
from backtrader.stores import btapistore,ctp_account_actor_port
qa=pathlib.Path(r'D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2a-independent-qa-20260927'); root=qa/'candidate'; manifest=json.loads((qa/'candidate-manifest.json').read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
print('python',sys.executable); print('python_version',sys.version.replace('\n',' ')); print('platform',platform.platform()); print('pytest',pytest.__version__)
for name,p in [('backtrader',pathlib.Path(backtrader.__file__).resolve()),('btapistore',pathlib.Path(btapistore.__file__).resolve()),('actor_port',pathlib.Path(ctp_account_actor_port.__file__).resolve())]:
 print('origin',name,p)
 if not p.is_relative_to(root.resolve()): raise SystemExit('origin escaped candidate')
recs={r['path']:r['sha256'] for r in manifest['files']}
for rel in ['backtrader/stores/btapistore.py','backtrader/stores/ctp_account_actor_port.py','tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py','tests/unit/stores/test_managed_execution_store_adapter.py','tests/unit/stores/test_managed_ctp_store_adapter.py','tests/unit/runtime/test_runtime_live_dispatch_guard.py','input-sources/btapistore.py']:
 got=sha(root/rel); print('post_hash',rel,got,'manifest_match',recs.get(rel)==got)
 if recs.get(rel)!=got: raise SystemExit('source changed')
loaded=sorted(n for n in sys.modules if n=='bt_api_py' or n.startswith('bt_api_py.') or n in {'_ctp','ctp_wrap'})
print('sdk_native_modules_loaded',loaded)
if loaded: raise SystemExit('SDK/native module loaded')
print('SOURCE_AND_HASH_CHECK_OK')
