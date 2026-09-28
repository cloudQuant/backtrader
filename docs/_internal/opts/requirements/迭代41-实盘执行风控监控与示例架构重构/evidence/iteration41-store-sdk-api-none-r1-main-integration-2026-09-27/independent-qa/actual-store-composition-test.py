from pathlib import Path
from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore
import examples.ctp_options_simnow_mechanical_operator as mechanical


class FakeApi:
    def __init__(self):
        self.exchange_kwargs = {"CTP___FUTURE": {}}
        self.write_calls = []
        self.connected = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def get_balance(self):
        return {"cash": 1.0, "value": 1.0}

    def submit_order(self, *_args, **_kwargs):
        self.write_calls.append("submit")

    def cancel_order(self, *_args, **_kwargs):
        self.write_calls.append("cancel")


def test_real_store_fake_api_never_reaches_private_lazy_connect(monkeypatch, tmp_path):
    monkeypatch.setattr(mechanical, "MECHANICAL_EXECUTION_ENABLED", True)
    monkeypatch.setattr(mechanical, "_require_external_receipt_path", lambda path, reason: tmp_path / "fake.json")
    monkeypatch.setattr(mechanical, "_require_pinned_trust_root", lambda *args: None)
    monkeypatch.setattr(mechanical, "_load_external_entry_approval", lambda *args, **kwargs: {"payload": {"issuer_key_id": "fake"}})
    monkeypatch.setattr(mechanical, "_calendar_receipt_sha256", lambda *args: "a" * 64)
    monkeypatch.setattr(mechanical, "_read_json_mapping", lambda *args: {})
    monkeypatch.setattr(mechanical, "_contains_private_key_material", lambda value: False)
    monkeypatch.setattr(mechanical, "resolve_credentials", lambda env: {"fake": True})
    monkeypatch.setattr(mechanical, "resolve_fronts", lambda env, environment: {"fake": True})

    api = FakeApi()
    store = BtApiStore(provider="ctp", api=api)
    fallback_calls = []
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: fallback_calls.append("called"))
    assert store.sdk_api is None

    config = mechanical.MechanicalConfiguration(
        environment="second_7x24",
        product_id="SA",
        exchange_id="CZCE",
        future_instrument_id="SA701",
        call_instrument_id="SA701C1500",
        put_instrument_id="SA701P1500",
    )
    with pytest.raises(mechanical.MechanicalBlocked, match="STORE_SDK_API_NOT_READY"):
        mechanical.run_mechanical_cycle(config, {}, state_directory=tmp_path, store=store)

    assert fallback_calls == []
    assert api.write_calls == []
    assert api.connected is False


def test_ctp_public_properties_do_not_return_raw_api_identity():
    import inspect

    api = FakeApi()
    store = BtApiStore(provider="ctp", api=api)
    properties = {
        name: descriptor
        for name, descriptor in inspect.getmembers(type(store))
        if isinstance(descriptor, property) and not name.startswith("_")
    }
    observed = {name: getattr(store, name) for name in properties}
    raw_identity = [name for name, value in observed.items() if value is api]
    assert raw_identity == []
    assert observed["sdk_api"] is None


def test_independent_import_guard_is_active_and_sdk_modules_are_absent():
    import sys

    assert any(type(finder).__name__ == "_NoNativeSdk" for finder in sys.meta_path)
    assert not any(
        name == blocked or name.startswith(blocked + ".")
        for name in sys.modules
        for blocked in ("bt_api_py", "bt_api_ctp", "_ctp")
    )
