import importlib
import os
import sys
from pathlib import Path
root=Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1\candidate").resolve()
for key in list(os.environ):
    if key.upper().startswith(("BT_", "CTP_", "PYTHONPATH", "PYTEST_")):
        os.environ.pop(key, None)
sys.path.insert(0,str(root))
import backtrader
from backtrader.stores import btapistore
from backtrader.stores import ctp_account_actor_port
for name,module in (("backtrader",backtrader),("btapistore",btapistore),("ctp_account_actor_port",ctp_account_actor_port)):
    path=Path(module.__file__).resolve()
    assert path.is_relative_to(root), (name,path,root)
    print("ORIGIN",name,path)
for name in ("bt_api_py","_ctp","ctp_wrap"):
    print("LOADED",name,name in sys.modules)
assert "bt_api_py" not in sys.modules and "_ctp" not in sys.modules and "ctp_wrap" not in sys.modules
print("ORIGIN_AND_NATIVE_IMPORT_SMOKE_OK")