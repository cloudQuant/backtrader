from __future__ import annotations
import os
import sys
from types import ModuleType
from pathlib import Path

for key in list(os.environ):
    if key.upper().startswith(("BT_", "CTP_", "PYTHONPATH", "PYTEST_")):
        os.environ.pop(key, None)
ROOT = Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1\pre-fix-r2a")
sys.path.insert(0, str(ROOT))

clients = []
class FakeGatewayClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.submits = []
        self.cancels = []
        clients.append(self)
    def connect(self):
        return None
    def disconnect(self):
        return None
    def get_balance(self):
        return {"balance": 100}
    def submit_order(self, payload):
        self.submits.append(payload)
        return {"status": "sent"}
    def cancel_order(self, order_ref, dataname=None):
        self.cancels.append((order_ref, dataname))
        return {"status": "sent"}

root = ModuleType("bt_api_py"); root.__path__ = []
gateway = ModuleType("bt_api_py.gateway"); gateway.__path__ = []
client_module = ModuleType("bt_api_py.gateway.client")
client_module.GatewayClient = FakeGatewayClient
sys.modules["bt_api_py"] = root
sys.modules["bt_api_py.gateway"] = gateway
sys.modules["bt_api_py.gateway.client"] = client_module

from backtrader.stores.btapistore import BtApiStore

results = []
for mutation in ("provider", "config"):
    store = BtApiStore(provider="ib_web_gateway", backend="gateway", config={"exchange_type": "IB_WEB"})
    store._ensure_api_ready()
    assert len(clients) == len(results) + 1
    wrapper = store._api
    client = clients[-1]
    wrapper.submit_order({"phase": "before", "mutation": mutation})
    wrapper.cancel_order("before-ref", dataname="before")
    if mutation == "provider":
        store.provider = "ctp"
    else:
        store._config["exchange_type"] = "CTP"
    wrapper.submit_order({"phase": "after", "mutation": mutation})
    wrapper.cancel_order("after-ref", dataname="after")
    assert client.submits == [
        {"phase": "before", "mutation": mutation},
        {"phase": "after", "mutation": mutation},
    ], client.submits
    assert client.cancels == [("before-ref", "before"), ("after-ref", "after")], client.cancels
    results.append({
        "mutation": mutation,
        "submit_reached_fake_after_mutation": client.submits[-1],
        "cancel_reached_fake_after_mutation": client.cancels[-1],
        "total_submit_calls": len(client.submits),
        "total_cancel_calls": len(client.cancels),
    })

assert sys.modules["bt_api_py.gateway.client"] is client_module
assert "_ctp" not in sys.modules and "ctp_wrap" not in sys.modules
for result in results:
    print("PRE_FIX_REPRO", result)
print("PRE_FIX_WRAPPER_ROUTE_BYPASS_REPRODUCED; fake calls only; no real provider/network/native")