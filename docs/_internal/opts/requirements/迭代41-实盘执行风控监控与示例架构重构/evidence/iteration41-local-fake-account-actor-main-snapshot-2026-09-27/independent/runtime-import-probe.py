import json
import subprocess
import sys

calls=[]
def refuse_popen(*args, **kwargs):
    calls.append((args, kwargs))
    raise AssertionError('Popen must not run during import')
subprocess.Popen=refuse_popen
import backtrader_runtime
from backtrader_runtime.inventory import iteration41_runtime_registry
registry=iteration41_runtime_registry()
ids=[item.runtime_id for item in registry.registrations]
loaded_default=any(name.startswith('backtrader_runtime._local_fake_account_actor_candidate') for name in sys.modules)
assert not loaded_default
assert not any('_local_fake_account_actor_candidate' in item for item in ids)
assert 'backtrader.stores.btapistore' not in sys.modules
# Direct source-module imports are inert too; no process is started at import time.
import backtrader_runtime._local_fake_account_actor_candidate.account_actor_port
import backtrader_runtime._local_fake_account_actor_candidate.fake_actor_client
assert not calls
assert not any(name.startswith(('bt_api_py','bt_api_ctp','bt_api_execution','_ctp','thosttrader','ctpbee')) for name in sys.modules)
print(json.dumps({'default_import_candidate_loaded':loaded_default,'candidate_runtime_registered':False,'BtApiStore_imported':False,'direct_candidate_import_started_process':bool(calls),'default_runtime_count':len(ids),'sdk_native_modules_loaded':[]},sort_keys=True))
