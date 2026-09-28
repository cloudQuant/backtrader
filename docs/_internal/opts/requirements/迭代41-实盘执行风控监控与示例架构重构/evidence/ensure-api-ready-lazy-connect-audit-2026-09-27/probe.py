import hashlib
import importlib.abc
import json
import os
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("BTAPISTORE_AUDIT_REPO_ROOT", Path.cwd())).resolve()
SOURCE_ROOT = REPO_ROOT
STORE_PATH = SOURCE_ROOT / "backtrader" / "stores" / "btapistore.py"
EXPECTED_STORE_SHA256 = "A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D"
actual_store_sha256 = hashlib.sha256(STORE_PATH.read_bytes()).hexdigest().upper()
if actual_store_sha256 != EXPECTED_STORE_SHA256:
    raise SystemExit(f"unexpected Store source hash: {actual_store_sha256}")
sys.dont_write_bytecode = True
sys.path.insert(0, str(SOURCE_ROOT))
os.environ.pop("BT_STORE_PROVIDER", None)
os.environ["BT_CTP_EXECUTION_AUTHORIZATION_KEY_ID"] = ""
os.environ["BT_CTP_EXECUTION_AUTHORIZATION_SECRET"] = ""

BLOCKED_PREFIXES = ("bt_api_py", "bt_api_ctp", "thostmduserapi", "thosttraderapi", "vnpy")
blocked_imports = []
network_attempts = []


class ImportTripwire(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + ".") for p in BLOCKED_PREFIXES):
            blocked_imports.append(fullname)
            raise ImportError("SDK/native imports disabled in fake audit")
        return None


def block_network(*args, **kwargs):
    network_attempts.append("socket")
    raise AssertionError("network disabled in fake audit")


sys.meta_path.insert(0, ImportTripwire())
socket.socket.connect = block_network
socket.create_connection = block_network
preloaded = sorted(
    name for name in sys.modules
    if any(name == p or name.startswith(p + ".") for p in BLOCKED_PREFIXES)
)
if preloaded:
    raise SystemExit(f"unexpected preloaded optional modules: {preloaded!r}")

from backtrader.stores.btapistore import BtApiStore
assert Path(sys.modules["backtrader.stores.btapistore"].__file__).resolve() == (SOURCE_ROOT / "backtrader" / "stores" / "btapistore.py").resolve()


class FakeApi:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def connect(self):
        self.calls.append("connect")

    def start(self):
        self.calls.append("start")

    def disconnect(self):
        self.calls.append("disconnect")

    def get_balance(self):
        self.calls.append("get_balance")
        return {"cash": 101.0, "value": 102.0}

    def get_symbol_info(self, symbol):
        self.calls.append(("get_symbol_info", symbol))
        return {"symbol": symbol, "multiplier": 10, "tick_size": 1}

    def get_session_state(self):
        self.calls.append("get_session_state")
        return {}

    def submit_order(self, *args, **kwargs):
        self.calls.append("submit_order")
        raise AssertionError("fake audit must not write")

    def cancel_order(self, *args, **kwargs):
        self.calls.append("cancel_order")
        raise AssertionError("fake audit must not write")


class FakeSdkApi(FakeApi):
    def configure_execution(self, config):
        self.calls.append(("configure_execution", dict(config)))

    def get_ctp_session_state(self, *, exchange_name):
        self.calls.append(("get_ctp_session_state", exchange_name))
        return {
            "session_enabled": True,
            "market_data_only": True,
            "armed": False,
            "auth_state": "ready",
            "login_state": "ready",
            "request_counts": {},
        }

    def get_all_balances(self, *, normalized):
        self.calls.append(("get_all_balances", normalized))
        return {"CTP___FUTURE": {"cash": 101.0, "value": 102.0}}

    def get_portfolio_balance(self, *, venue_balances):
        self.calls.append(("get_portfolio_balance", dict(venue_balances)))
        return {"cash": 101.0, "value": 102.0}

    def get_instrument_spec(self, exchange_name, symbol):
        self.calls.append(("get_instrument_spec", exchange_name, symbol))
        return {
            "exchange_name": exchange_name,
            "symbol": symbol,
            "contract_value": 1,
            "contract_multiplier": 10,
            "price_tick": 1,
            "quantity_step": 1,
            "min_quantity": 1,
            "quantity_unit": "lot",
            "quote_currency": "CNY",
        }


def instrument_ensure(store):
    calls = []
    original = store._ensure_api_ready

    def counted(*args, **kwargs):
        calls.append("_ensure_api_ready")
        return original(*args, **kwargs)

    store._ensure_api_ready = counted
    return calls


def summarize(store, api, ensure_calls):
    return {
        "provider": store.provider,
        "backend": store.backend,
        "public_sdk_api_is_none": store.sdk_api is None,
        "_ensure_api_ready_calls": list(ensure_calls),
        "sdk_mode": store._sdk_mode,
        "ctp_session_provider": store._is_ctp_session_provider(),
        "ctp_write_provider": store._is_ctp_write_provider(),
        "connected": store._connected,
        "calls": list(api.calls),
        "write_calls": [call for call in api.calls if isinstance(call, str) and call in {"submit_order", "cancel_order"}],
    }


results = {
    "source_preimage": {
        "repository_relative_path": "backtrader/stores/btapistore.py",
        "sha256": actual_store_sha256,
        "loaded_module_path": str(Path(sys.modules["backtrader.stores.btapistore"].__file__).resolve()),
    }
}

api = FakeApi("direct-balance")
store = BtApiStore(provider="ctp", api=api, autostart=False)
ensure_calls = instrument_ensure(store)
results["direct_get_balance_force"] = {
    "result": store.get_balance(force=True),
    **summarize(store, api, ensure_calls),
}

api = FakeApi("direct-symbol")
store = BtApiStore(provider="ctp", api=api, autostart=False)
ensure_calls = instrument_ensure(store)
results["direct_get_symbol_info"] = {
    "result": store.get_symbol_info("CZCE.SA701"),
    **summarize(store, api, ensure_calls),
}

api = FakeApi("direct-start")
store = BtApiStore(provider="ctp", api=api, autostart=False)
ensure_calls = instrument_ensure(store)
store.start()
results["direct_start"] = summarize(store, api, ensure_calls)
store.stop(timeout=0.2)

api = FakeApi("gateway-start")
store = BtApiStore(provider="ctp_gateway", backend="gateway", api=api, autostart=False)
ensure_calls = instrument_ensure(store)
store.start()
results["ctp_gateway_start"] = summarize(store, api, ensure_calls)
store.stop(timeout=0.2)

api = FakeApi("forwarding-start")
store = BtApiStore(
    provider="btapi", backend="forwarding", config={"exchange": "CTP"}, api=api, autostart=False
)
ensure_calls = instrument_ensure(store)
store.start()
results["ctp_forwarding_start"] = summarize(store, api, ensure_calls)
store.stop(timeout=0.2)

# Example-equivalent in-process path: 013_3 builds provider='btapi', direct,
# one CTP exchange_kwargs route and market_data_only execution_config, then starts the Store.
api = FakeSdkApi("example-style-btapi")
store = BtApiStore(
    provider="btapi",
    backend="direct",
    config={
        "exchange_kwargs": {"CTP___FUTURE": {}},
        "execution_config": {"market_data_only": True},
        "funding_refresh_interval_seconds": 0,
    },
    api=api,
    autostart=False,
)
ensure_calls = instrument_ensure(store)
example_route_facts = {
    "provider": store.provider,
    "backend": store.backend,
    "sdk_mode": store._sdk_mode,
    "ctp_session_provider": store._is_ctp_session_provider(),
    "sdk_owned_api": store._sdk_owned_api,
}
store.start()
balance = store.get_balance(force=True)
symbol_info = store.get_symbol_info("CTP___FUTURE:SA701")
results["example_style_managed_ctp_fake"] = {
    "route_facts": example_route_facts,
    "balance": balance,
    "symbol_info": symbol_info,
    **summarize(store, api, ensure_calls),
}
store.stop(timeout=0.2)

results["optional_import_guard"] = list(blocked_imports)
results["network_guard"] = list(network_attempts)
if blocked_imports or network_attempts:
    raise SystemExit(f"guard hit: imports={blocked_imports!r}, network={network_attempts!r}")
print(json.dumps(results, indent=2, default=str))