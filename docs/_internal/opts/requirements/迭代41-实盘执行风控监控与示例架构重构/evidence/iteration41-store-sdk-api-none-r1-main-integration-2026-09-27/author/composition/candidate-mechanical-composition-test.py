from pathlib import Path

import pytest

from backtrader.stores.btapistore import BtApiStore
import examples.ctp_options_simnow_mechanical_operator as mechanical


def _config():
    return mechanical.MechanicalConfiguration(
        environment="second_7x24",
        product_id="SA",
        exchange_id="CZCE",
        future_instrument_id="SA701",
        call_instrument_id="SA701C1500",
        put_instrument_id="SA701P1500",
    )


def _replace_prior_admission_with_fake_stubs(monkeypatch, tmp_path):
    monkeypatch.setattr(mechanical, "MECHANICAL_EXECUTION_ENABLED", True)
    monkeypatch.setattr(
        mechanical,
        "_require_external_receipt_path",
        lambda path, reason: tmp_path / "synthetic-receipt.json",
    )
    monkeypatch.setattr(mechanical, "_require_pinned_trust_root", lambda *args: None)
    monkeypatch.setattr(
        mechanical,
        "_load_external_entry_approval",
        lambda *args, **kwargs: {"payload": {"issuer_key_id": "fake-issuer"}},
    )
    monkeypatch.setattr(mechanical, "_calendar_receipt_sha256", lambda *args: "a" * 64)
    monkeypatch.setattr(mechanical, "_read_json_mapping", lambda *args: {})
    monkeypatch.setattr(mechanical, "_contains_private_key_material", lambda value: False)
    monkeypatch.setattr(mechanical, "resolve_credentials", lambda env: {"synthetic": "only"})
    monkeypatch.setattr(
        mechanical, "resolve_fronts", lambda env, environment: {"synthetic": "only"}
    )


class _FakeApi:
    def __init__(self):
        self.connect_calls = 0
        self.write_calls = []

    def connect(self, *args, **kwargs):
        self.connect_calls += 1
        raise AssertionError("mechanical path must not connect the fake API")

    def submit_order(self, *args, **kwargs):
        self.write_calls.append(("submit_order", args, kwargs))
        raise AssertionError("mechanical path must not submit")

    def create_order(self, *args, **kwargs):
        self.write_calls.append(("create_order", args, kwargs))
        raise AssertionError("mechanical path must not create an order")

    def cancel_order(self, *args, **kwargs):
        self.write_calls.append(("cancel_order", args, kwargs))
        raise AssertionError("mechanical path must not cancel")


def test_actual_ctp_store_getter_and_mechanical_fallback_fail_closed_together(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("BT_STORE_PROVIDER", raising=False)
    monkeypatch.setenv("BT_CTP_EXECUTION_AUTHORIZATION_KEY_ID", "")
    monkeypatch.setenv("BT_CTP_EXECUTION_AUTHORIZATION_SECRET", "")
    _replace_prior_admission_with_fake_stubs(monkeypatch, tmp_path)
    api = _FakeApi()
    store = BtApiStore(provider="ctp", api=api, autostart=False)
    private_ready_calls = []

    def forbidden_private_fallback():
        private_ready_calls.append(True)
        raise AssertionError("private lazy-connect fallback must not run")

    monkeypatch.setattr(store, "_ensure_api_ready", forbidden_private_fallback)

    assert store.sdk_api is None
    with pytest.raises(mechanical.MechanicalBlocked, match="STORE_SDK_API_NOT_READY"):
        mechanical.run_mechanical_cycle(
            _config(), {}, state_directory=Path(tmp_path), store=store
        )

    assert private_ready_calls == []
    assert store._connected is False
    assert api.connect_calls == 0
    assert api.write_calls == []


