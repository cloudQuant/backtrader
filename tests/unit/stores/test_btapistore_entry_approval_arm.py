"""Entry-approval arming and budget capability passthrough store contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest

from bt_api_py import CtpExecutionApprovalCapability

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_btapistore_iteration22 import (  # noqa: E402
    ManagedBtApiClient,
    _authorized_store,
)


def _capability_stub():
    capability = object.__new__(CtpExecutionApprovalCapability)
    return capability


class EntryApprovalClient(ManagedBtApiClient):
    def __init__(self):
        super().__init__()
        self.entry_approval_arms = []

    def arm_execution_from_approval(self, approval_capability):
        self.entry_approval_arms.append(approval_capability)
        proof = self.armed_proofs[0] if self.armed_proofs else {
            "account_fingerprint": "acct_0123456789abcdef",
            "trading_day": "20260909",
            "instrument": "CZCE.SA609",
            "connection_generation": 3,
            "environment_profile": "simnow_demo",
            "receipt_sha256": "1" * 64,
            "native_sha256": "2" * 64,
            "ctp_package_sha256": "3" * 64,
            "source_hashes_sha256": "4" * 64,
            "dependency_hashes_sha256": "5" * 64,
            "preflight_sha256": "6" * 64,
        }
        self.armed_proofs.append(dict(proof))
        self.armed = True
        self.arm_proof_sha256 = hashlib.sha256(
            json.dumps(
                dict(proof),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "armed": True,
            "market_data_only": False,
            "proof_sha256": self.arm_proof_sha256,
        }


def test_store_arms_sdk_from_redeemed_entry_approval_capability():
    client = EntryApprovalClient()
    client_armed = client.arm_execution_from_preflight  # inherited; unused
    del client_armed
    _client, store, proof, _grant, _configured = _authorized_store(client)
    capability = _capability_stub()

    result = store.arm_sdk_execution(proof, authorization=capability)

    assert result["armed"] is True
    assert result["market_data_only"] is False
    assert client.entry_approval_arms == [capability]
    assert store._sdk_execution_config["market_data_only"] is False
    assert store._command_accept_openings is False
    assert store._sdk_execution_arming is False


def test_store_rejects_entry_approval_arm_without_sdk_support():
    _client, store, proof, _grant, _configured = _authorized_store()
    capability = _capability_stub()
    if hasattr(_client, "arm_execution_from_approval"):
        del _client.arm_execution_from_approval

    from backtrader.stores.btapistore import BtApiStoreError

    with pytest.raises(BtApiStoreError, match="entry approval arming"):
        store.arm_sdk_execution(proof, authorization=capability)
    assert store._sdk_execution_config["market_data_only"] is True


class _OrderInfo(dict):
    pass


class _FakeOrder:
    def __init__(self, info):
        self.info = info
        self.ref = 991

    def addinfo(self, **kwargs):
        self.info.update(kwargs)


def test_store_order_command_carries_budget_capability(monkeypatch):
    _client, store, proof, _grant, _configured = _authorized_store()
    store.arm_sdk_execution(proof)
    capability = _capability_stub()
    captured = []

    def enqueue_once(command, *, priority_name):
        captured.append((dict(command), priority_name))
        return {
            "queued": True,
            "status": "submitted",
            "receipt_id": "budget-receipt-1",
        }

    monkeypatch.setattr(store, "_enqueue_sdk_command", enqueue_once)
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: None)
    monkeypatch.setattr(store, "_require_async_sdk_commands", lambda: None)
    monkeypatch.setattr(store, "_start_command_worker", lambda: None)
    monkeypatch.setattr(
        store,
        "_sdk_exchange",
        lambda symbol: "CTP___FUTURE",
    )

    class _Request:
        client_order_id = "000000000001"

    monkeypatch.setattr(
        store,
        "_order_to_payload",
        lambda order: {
            "symbol": "SA609.CZCE",
            "side": "buy",
            "size": 1,
            "price": 1500.0,
            "order_type": "limit",
            "offset": "open",
            "bt_order_ref": 991,
        },
    )
    monkeypatch.setattr(
        store,
        "_sdk_order_request",
        lambda venue, payload: _Request(),
    )

    order = _FakeOrder({"budget_capability": capability})
    store._enqueue_order_command(order)

    assert len(captured) == 1
    command = captured[0][0]
    assert command["operation"] == "submit"
    assert command["budget_capability"] is capability
    # The opaque reservation also stays on the local order info so broker
    # reconciliation can keep referencing it.
    assert order.info["client_order_id"] == "000000000001"


def test_store_invoke_sdk_command_passes_budget_capability_to_async_make_order():
    _client, store, proof, _grant, _configured = _authorized_store()
    capability = _capability_stub()
    seen = []

    class _Api:
        async def async_make_order(self, venue, request, *, normalized=False, **kwargs):
            seen.append((venue, request, normalized, kwargs))
            return {"kind": "order", "status": "submitted"}

    store._api = _Api()
    command = {
        "operation": "submit",
        "venue": "CTP___FUTURE",
        "request": object(),
        "budget_capability": capability,
    }
    result = asyncio.run(store._invoke_sdk_command("submit", command))

    assert result == {"kind": "order", "status": "submitted"}
    assert len(seen) == 1
    assert seen[0][2] is True
    assert seen[0][3] == {"budget_capability": capability}


def test_store_invoke_sdk_command_omits_budget_capability_when_absent():
    _client, store, proof, _grant, _configured = _authorized_store()
    seen = []

    class _Api:
        async def async_make_order(self, venue, request, *, normalized=False, **kwargs):
            seen.append(kwargs)
            return {"kind": "order", "status": "submitted"}

    store._api = _Api()
    command = {
        "operation": "submit",
        "venue": "CTP___FUTURE",
        "request": object(),
    }
    asyncio.run(store._invoke_sdk_command("submit", command))

    assert seen == [{}]
