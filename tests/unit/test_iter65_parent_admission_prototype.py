"""Observe the current parent-admission boundary using synthetic local ports.

The admission callback and Gateway port below are controlled test substitutes,
not authentication, an actual SDK transport, or evidence of a production race.
The temporary SQLite journal and ParentAuthority are real.  In particular, a
local PENDING/UNKNOWN result does not prove the state of any real remote owner.
These assertions record current behavior rather than the iteration 65 target.
"""

import json
from pathlib import Path
import sys
import time

import pytest

import backtrader
import bt_api_base
import bt_api_execution
import bt_api_py
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_execution.contracts import ExecutionScope
from bt_api_execution.errors import InvalidStateTransition
from bt_api_execution.parent_authority import ParentAuthority
from bt_api_execution.store import SqliteExecutionStore


@pytest.fixture(autouse=True)
def workspace_module_sources():
    root = Path(__file__).resolve().parents[3]
    # The workspace holds this repository and the sibling SDK checkout.
    assert (root / "backtrader").is_dir() and (root / "bt_api_py").is_dir()

    def check():
        for module in (backtrader, bt_api_base, bt_api_execution, bt_api_py):
            assert Path(module.__file__).resolve().is_relative_to(root)
        for name, module in tuple(sys.modules.items()):
            if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
                source = getattr(module, "__file__", None)
                if source:
                    assert Path(source).resolve().is_relative_to(root), (name, source)

    check()
    yield
    check()


def parent_spec():
    return {
        "parent_ref": "parent-1", "registration_operation_id": "register-parent-1",
        "risk_operation_id": "risk-parent-1", "account_scope": "synthetic-account",
        "strategy_scope": "synthetic-strategy", "execution_domain_ref": "synthetic-domain",
        "instrument": MarketInstrumentKey("ctp", "SHFE", "synthetic", "future", "rb", "rb").to_dict(),
        "quantity": "5", "quantity_unit": "lots", "side": "buy", "offset": "open",
        "limit_price": "5", "creation_trading_day": "20261109",
        "allowed_trading_days": ["20261109"], "expires_at_ns": time.time_ns() + 60_000_000_000,
        "grant_revision": "synthetic-grant-1", "plan_digest": "a" * 64, "plan_version": "v1",
        "target_position_ref": None, "risk_selected": False, "time_in_force": "GTD",
    }


class SyntheticAdmission:
    """Strict scope predicate with an intentional grant change at a test point."""

    def __init__(self, *, active=True, revoke_after=None):
        self.active = active
        self.revoke_after = revoke_after
        self.actions = []

    def __call__(self, action, spec):
        self.actions.append(action)
        allowed = (self.active and spec["account_scope"] == "synthetic-account"
                   and spec["strategy_scope"] == "synthetic-strategy")
        if allowed and action == self.revoke_after:
            # This is a synthetic callback interleaving, not a real grant source.
            self.active = False
        return allowed


class FencedGatewayStub:
    """Models SDK send-gate usage; does not implement a Gateway service."""

    def __init__(self):
        self.authority = None
        self.attempts = []
        self.outbound = []

    def register_parent(self, spec, operation_id):
        self.attempts.append((spec["parent_ref"], operation_id))
        wire_spec = {key: value for key, value in spec.items()
                     if key not in {"risk_selected", "risk_operation_id"}}
        if not self.authority.prepare_parent_dispatch(wire_spec, operation_id, "REGISTER", None):
            return None
        self.outbound.append((spec["parent_ref"], operation_id))
        return {"state": "ACCEPTED"}

    def verify(self, response, _spec, _operation_id):
        return response["state"] if response is not None else None


def open_authority(path, admission, gateway):
    scope = ExecutionScope("FAKE", "test", "synthetic-account", "synthetic-strategy", "20261109")
    store = SqliteExecutionStore(path)
    lease = store.acquire_or_renew_lease(scope, "synthetic-writer", ttl_ns=300_000_000_000)
    authority = ParentAuthority(store, scope, lease, admission=admission, gateway=gateway)
    gateway.authority = authority
    return store, authority


@pytest.mark.parametrize("mismatch", ["account_scope", "strategy_scope"])
def test_synthetic_scope_admission_denies_mismatch_without_parent(tmp_path, mismatch):
    admission, gateway = SyntheticAdmission(), FencedGatewayStub()
    store, authority = open_authority(tmp_path / "journal.sqlite", admission, gateway)
    try:
        spec = parent_spec()
        spec[mismatch] = "synthetic-other"
        with pytest.raises(InvalidStateTransition, match="parent admission denied"):
            authority.accept(spec)
        with pytest.raises(InvalidStateTransition, match="unknown parent"):
            authority.get(spec["parent_ref"])
        assert admission.actions == ["accept"]
        assert gateway.attempts == gateway.outbound == []

        accepted = authority.accept(parent_spec())
        assert accepted["gateway_state"] == "PENDING"
        assert json.loads(accepted["request_json"])["account_scope"] == "synthetic-account"
    finally:
        store.close()


def test_revoke_after_synthetic_accept_check_persists_local_parent_but_blocks_register(tmp_path):
    path = tmp_path / "journal.sqlite"
    admission = SyntheticAdmission(revoke_after="accept")
    gateway = FencedGatewayStub()
    store, authority = open_authority(path, admission, gateway)
    spec = parent_spec()
    try:
        accepted = authority.accept(spec)
        assert not admission.active
        assert accepted["gateway_state"] == "PENDING"
        assert json.loads(accepted["request_json"]) == spec
        # Production continuity is unproven, so registration stays local and no
        # owner dispatch is attempted even after the synthetic grant is revoked.
        assert authority.register(spec["parent_ref"])["gateway_state"] == "PENDING"
        assert admission.actions == ["accept"]
        assert gateway.attempts == gateway.outbound == []
    finally:
        store.close()

    store, authority = open_authority(path, admission, gateway)
    try:
        restored = authority.get(spec["parent_ref"])
        assert restored["request_sha256"] == accepted["request_sha256"]
        assert json.loads(restored["request_json"]) == spec
        with pytest.raises(InvalidStateTransition, match="parent admission denied"):
            authority.accept(spec)
        assert authority.register(spec["parent_ref"])["gateway_state"] == "PENDING"
        assert admission.actions == ["accept", "accept"]
        assert gateway.attempts == gateway.outbound == []

        # A new explicit test grant, not a restoration inferred from the journal.
        admission.active, admission.revoke_after = True, None
        assert authority.accept(spec)["request_sha256"] == accepted["request_sha256"]
        assert authority.register(spec["parent_ref"])["gateway_state"] == "PENDING"
        assert admission.actions == ["accept", "accept", "accept"]
        assert gateway.attempts == gateway.outbound == []
    finally:
        store.close()


def test_revoke_after_synthetic_register_check_is_blocked_by_send_gate(tmp_path):
    path = tmp_path / "journal.sqlite"
    admission = SyntheticAdmission(revoke_after="register")
    gateway = FencedGatewayStub()
    store, authority = open_authority(path, admission, gateway)
    spec = parent_spec()
    try:
        authority.accept(spec)
        result = authority.register(spec["parent_ref"])
        # Without proven continuity the local claim is never created, so the
        # send gate and its admission checks are never reached.
        assert admission.actions == ["accept"]
        assert result["gateway_state"] == "PENDING"
        assert gateway.attempts == gateway.outbound == []
        assert authority.register(spec["parent_ref"])["gateway_state"] == "PENDING"
        assert gateway.attempts == []
    finally:
        store.close()

    store, authority = open_authority(path, admission, gateway)
    try:
        restored = authority.get(spec["parent_ref"])
        assert restored["gateway_state"] == "PENDING"
        assert json.loads(restored["request_json"]) == spec
        assert authority.register(spec["parent_ref"])["gateway_state"] == "PENDING"
        assert gateway.outbound == []
    finally:
        store.close()
