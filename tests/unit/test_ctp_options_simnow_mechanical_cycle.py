"""Pure-local tests for the shared Iteration 23/24/25 mechanical cycle."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

cycle_module = importlib.import_module("examples.ctp_options_simnow_mechanical_cycle")
operator_module = importlib.import_module("examples.ctp_options_simnow_mechanical_operator")


GATE_RECEIPT_NOW = datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc)


def _gate_binding(**changes):
    value = {
        "strategy_id": "iter23-25-options-mechanical",
        "environment": "second_7x24",
        "product_id": "SA",
        "exchange_id": "CZCE",
        "authorized_instruments": [
            {"role": "future", "exchange_id": "CZCE", "instrument_id": "SA701"},
            {"role": "call", "exchange_id": "CZCE", "instrument_id": "SA701C1500"},
            {"role": "put", "exchange_id": "CZCE", "instrument_id": "SA701P1500"},
        ],
        "account_fingerprint": "acct_0123456789abcdef",
        "trading_day": "20260911",
        "connection_generation": 7,
        "environment_profile": "simnow_demo",
        "configuration_sha256": "0" * 64,
        "calendar_sha256": "6" * 64,
        "source_hashes_sha256": "1" * 64,
        "dependency_hashes_sha256": "2" * 64,
        "native_sha256": "3" * 64,
        "runtime_executable_sha256": "4" * 64,
        "evidence_hashes_sha256": "5" * 64,
        "budget_ordinary_cap_cny": "8000",
        "maximum_cycle_count": 1,
    }
    value.update(changes)
    return value


def _write_signed_gate_receipt(tmp_path, *, binding=None, payload_changes=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    cryptography = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    binding = binding or _gate_binding()
    private = cryptography.Ed25519PrivateKey.generate()
    public_key = (
        base64.urlsafe_b64encode(private.public_key().public_bytes_raw())
        .decode("ascii")
        .rstrip("=")
    )
    key_id = "independent-gate-test"
    issued_at = (GATE_RECEIPT_NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    expires_at = (GATE_RECEIPT_NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": "iter23-25.mechanical-gate-receipt.v1",
        "approval_id": "mechanical-gate-test-1",
        "nonce": "mechanical-gate-nonce-1",
        "issuer_key_id": key_id,
        "issuer_role": "independent_gate_approver",
        "purpose": "simnow_mechanical_cycle",
        **binding,
        "gate_statuses": {"G1": "PASS", "G2": "PASS", "G3": "PASS"},
        "issued_at": issued_at,
        "not_before": issued_at,
        "expires_at": expires_at,
        "revocation_snapshot_version": 1,
    }
    if payload_changes:
        payload.update(payload_changes)
    payload_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    artifact = {
        "schema_version": "iter23-25.mechanical-gate-receipt-artifact.v1",
        "algorithm": "Ed25519",
        "payload": payload,
        "signature": base64.urlsafe_b64encode(private.sign(payload_bytes))
        .decode("ascii")
        .rstrip("="),
    }
    receipt_file = tmp_path / "mechanical-gate-receipt.json"
    receipt_file.write_text(json.dumps(artifact), encoding="utf-8")
    trust_root = {
        "schema_version": "ctp-execution-trust-root-v1",
        "keys": {
            key_id: {
                "public_key": public_key,
                "role": "independent_gate_approver",
                "purposes": ["simnow_mechanical_gate"],
                "not_before": issued_at,
                "expires_at": expires_at,
            }
        },
        "revocation_snapshot": {
            "version": 1,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "revoked_approval_ids": [],
            "revoked_nonces": [],
        },
    }
    trust_root_file = tmp_path / "mechanical-gate-trust-root.json"
    trust_root_file.write_text(json.dumps(trust_root), encoding="utf-8")
    return receipt_file, trust_root_file, binding


def _pin_gate_trust_root(monkeypatch, trust_root_file):
    monkeypatch.setattr(
        operator_module,
        "PINNED_MECHANICAL_GATE_TRUST_ROOT_SHA256",
        hashlib.sha256(trust_root_file.read_bytes()).hexdigest(),
    )


class FakeOrder:
    def __init__(self, ref, **info):
        self.ref = ref
        self.status = 1
        self._status_name = "Accepted"
        self.info = info

    def getstatusname(self):
        return self._status_name


class FakeBroker:
    def __init__(self):
        self.calls = []
        self._ref = 0

    def _new(self, action, **kwargs):
        self._ref += 1
        order = FakeOrder(self._ref, **kwargs)
        self.calls.append((action, kwargs, order))
        return order

    def buy(self, **kwargs):
        return self._new("buy", **kwargs)

    def sell(self, **kwargs):
        return self._new("sell", **kwargs)

    def cancel(self, order):
        self.calls.append(("cancel", order))
        return order


def snapshot(**changes):
    value = {
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "account_fingerprint": "acct_hash_only",
        "trading_day": "20260911",
        "connection_generation": 1,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "nonzero_positions": [],
        "active_orders": [],
    }
    value.update(changes)
    return value


def proof():
    base = snapshot()
    semantic = cycle_module._semantic_hash(base)
    return {
        "settlement_verified": True,
        "bundle_preflight": dict(base),
        "reconciliation_rounds": (dict(base), dict(base)),
        "reconciliation_semantic_hashes": (semantic, semantic),
        "execution_authorization": {
            "armed": True,
            "account_fingerprint": "acct_hash_only",
            "connection_generation": 1,
        },
    }


def make_cycle():
    broker = FakeBroker()
    cycle = cycle_module.MechanicalCycle(
        broker=broker,
        owner=object(),
        feeds={"F": object()},
        cycle_id="cycle-23-test",
    )
    cycle.arm(proof())
    cycle.plan_entry(
        [cycle_module.MechanicalLeg("F", "buy", 1000.0, object())],
        intent_id="intent-open",
    )
    return cycle, broker


def native_fill(order, *, cycle_id="cycle-23-test", intent_id="intent-open:open:0"):
    order.status = 4
    order._status_name = "Completed"
    order.info.update(
        execution_cycle_id=cycle_id,
        intent_id=intent_id,
        ctp_order_ref="native-ref",
        front_id=10,
        session_id=20,
        external_order_id="sys-1",
        trade_id="trade-1",
        connection_generation=1,
        execution_fill_source="trade",
    )
    return order


def test_unarmed_cycle_has_no_write_boundary_call():
    broker = FakeBroker()
    cycle = cycle_module.MechanicalCycle(
        broker=broker, owner=object(), feeds={"F": object()}, cycle_id="cycle-unarmed"
    )
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="CYCLE_NOT_ARMED"):
        cycle.plan_entry([cycle_module.MechanicalLeg("F", "buy", 1, object())], intent_id="i")
    assert broker.calls == []


def test_one_leg_open_close_and_two_round_flat_closes_without_profit_claim():
    cycle, broker = make_cycle()
    opened = cycle.submit_next_entry()
    cycle.on_order_update(native_fill(opened))
    cycle.plan_exit(
        [cycle_module.MechanicalLeg("F", "sell", 1001.0, object())], intent_id="intent-close"
    )
    closed = cycle.submit_next_exit()
    cycle.on_order_update(native_fill(closed, intent_id="intent-close:close:0"))
    cycle.finalize_flat(snapshot(), snapshot())
    assert cycle.state == "CLOSED_FLAT"
    assert [item[0] for item in broker.calls] == ["buy", "sell"]
    assert all("account_fingerprint" not in row for row in cycle.journal)
    assert all("native-ref" not in str(row) for row in cycle.journal)


def test_local_mock_fill_without_native_confirmation_is_not_a_fill():
    cycle, _ = make_cycle()
    order = cycle.submit_next_entry()
    order.status = 4
    order._status_name = "Completed"
    with pytest.raises(
        cycle_module.MechanicalCycleBlocked, match="NATIVE_FILL_IDENTITY_INCOMPLETE"
    ):
        cycle.on_order_update(order)
    assert cycle.state == "RECOVERY_REQUIRED"


def test_completed_integer_status_without_execution_fill_source_is_not_native_fill():
    cycle, _ = make_cycle()
    order = cycle.submit_next_entry()
    order.status = 4
    order._status_name = "Completed"
    order.info.update(
        execution_cycle_id="cycle-23-test",
        intent_id="intent-open:open:0",
        ctp_order_ref="native-ref",
        front_id=10,
        session_id=20,
        external_order_id="sys-1",
        trade_id="trade-1",
        connection_generation=1,
    )
    with pytest.raises(
        cycle_module.MechanicalCycleBlocked, match="NATIVE_FILL_IDENTITY_INCOMPLETE"
    ):
        cycle.on_order_update(order)


def test_missing_ctp_alias_is_fail_closed_even_with_trade_source():
    cycle, _ = make_cycle()
    order = cycle.submit_next_entry()
    native_fill(order)
    del order.info["external_order_id"]
    with pytest.raises(
        cycle_module.MechanicalCycleBlocked, match="NATIVE_FILL_IDENTITY_INCOMPLETE"
    ):
        cycle.on_order_update(order)


def test_exit_side_must_match_derived_opposite_entry_side():
    cycle, _ = make_cycle()
    opened = cycle.submit_next_entry()
    cycle.on_order_update(native_fill(opened))
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="EXIT_PLAN_NOT_EQUIVALENT"):
        cycle.plan_exit(
            [cycle_module.MechanicalLeg("F", "buy", 1001.0, object())],
            intent_id="intent-close",
        )


def test_close_fill_reaches_close_filled_before_flat_reconciliation():
    cycle, _ = make_cycle()
    opened = cycle.submit_next_entry()
    cycle.on_order_update(native_fill(opened))
    cycle.plan_exit(
        [cycle_module.MechanicalLeg("F", "sell", 1001.0, object())],
        intent_id="intent-close",
    )
    closed = cycle.submit_next_exit()
    cycle.on_order_update(native_fill(closed, intent_id="intent-close:close:0"))
    assert cycle.state == "CLOSE_FILLED"
    with pytest.raises(
        cycle_module.MechanicalCycleBlocked, match="FINAL_RECONCILIATION_NOT_SAFE_OR_FLAT"
    ):
        cycle.finalize_flat(snapshot(flat=False), snapshot(flat=False))


@pytest.mark.parametrize("status", ("Partial", "Unknown", "pending_cancel"))
def test_partial_or_unknown_stops_ordinary_opening(status):
    cycle, _ = make_cycle()
    order = cycle.submit_next_entry()
    order.status = 3
    order._status_name = status
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="PARTIAL_OR_UNKNOWN_FILL"):
        cycle.on_order_update(order)
    assert cycle.state == "RECOVERY_REQUIRED"


def test_cancel_then_late_native_fill_is_recovery_not_reopen():
    cycle, broker = make_cycle()
    order = cycle.submit_next_entry()
    cycle.cancel_pending()
    native_fill(order)
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="LATE_FILL_AFTER_CANCEL"):
        cycle.on_order_update(order)
    assert cycle.state == "RECOVERY_REQUIRED"
    assert broker.calls[-1][0] == "cancel"


def test_reconnect_stops_even_when_generation_is_unchanged():
    cycle, _ = make_cycle()
    cycle.submit_next_entry()
    with pytest.raises(cycle_module.MechanicalCycleBlocked, match="RECONNECT_REQUIRES_REARM"):
        cycle.reconnect(1)
    assert cycle.state == "RECOVERY_REQUIRED"


def test_arm_rejects_nonflat_or_unstable_proof():
    for bad in (
        {"bundle_preflight": snapshot(flat=False)},
        {"bundle_preflight": snapshot(unknown_intent_count=1, flat=False)},
        {"bundle_preflight": snapshot(evidence_complete=False)},
    ):
        value = proof()
        value.update(bad)
        with pytest.raises(cycle_module.MechanicalCycleBlocked):
            cycle_module.MechanicalCycle(
                broker=FakeBroker(), owner=object(), feeds={"F": object()}, cycle_id="bad"
            ).arm(value)


def test_cycle_has_no_direct_api_or_store_private_boundary():
    source = Path(cycle_module.__file__).read_text(encoding="utf-8")
    assert "._api" not in source
    assert "submit_order" not in source
    assert "cancel_order" not in source
    assert (
        "self.broker.buy" in source
        and "self.broker.sell" in source
        and "self.broker.cancel" in source
    )


def test_mechanical_gate_receipt_is_independently_signed_and_exactly_bound(tmp_path, monkeypatch):
    receipt_file, trust_root_file, binding = _write_signed_gate_receipt(tmp_path)
    _pin_gate_trust_root(monkeypatch, trust_root_file)

    verified = operator_module.verify_external_mechanical_gate_receipt(
        receipt_file,
        trust_root_file,
        binding,
        now=GATE_RECEIPT_NOW,
    )

    expected_receipt_sha256 = hashlib.sha256(
        json.dumps(
            verified["payload"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert verified["receipt_sha256"] == expected_receipt_sha256
    assert verified["gate_statuses"] == {"G1": "PASS", "G2": "PASS", "G3": "PASS"}


def test_mechanical_gate_receipt_rejects_an_unpinned_caller_supplied_root(tmp_path):
    """A caller-created root cannot become the gate's authority by CLI path."""

    receipt_file, trust_root_file, binding = _write_signed_gate_receipt(tmp_path)

    with pytest.raises(operator_module.MechanicalBlocked, match="TRUST_ROOT_NOT_PINNED"):
        operator_module.verify_external_mechanical_gate_receipt(
            receipt_file,
            trust_root_file,
            binding,
            now=GATE_RECEIPT_NOW,
        )


def test_mechanical_gate_receipt_rejects_caller_supplied_root_with_wrong_build_pin(
    tmp_path, monkeypatch
):
    receipt_file, trust_root_file, binding = _write_signed_gate_receipt(tmp_path / "trusted")
    _, alternate_root_file, _ = _write_signed_gate_receipt(tmp_path / "caller-created")
    _pin_gate_trust_root(monkeypatch, trust_root_file)

    with pytest.raises(operator_module.MechanicalBlocked, match="TRUST_ROOT_PIN_MISMATCH"):
        operator_module.verify_external_mechanical_gate_receipt(
            receipt_file,
            alternate_root_file,
            binding,
            now=GATE_RECEIPT_NOW,
        )


@pytest.mark.parametrize(
    ("payload_changes", "reason"),
    [
        ({"gate_statuses": {"G1": "PASS", "G2": "INCOMPLETE", "G3": "PASS"}}, "GATE_STATUS"),
        ({"account_fingerprint": "acct_other"}, "MECHANICAL_GATE_BINDING_MISMATCH"),
        ({"evidence_hashes_sha256": "not-a-hash"}, "MECHANICAL_GATE_HASH_INVALID"),
    ],
)
def test_mechanical_gate_receipt_rejects_nonpass_gate_or_mismatched_binding(
    tmp_path, monkeypatch, payload_changes, reason
):
    receipt_file, trust_root_file, binding = _write_signed_gate_receipt(
        tmp_path, payload_changes=payload_changes
    )
    _pin_gate_trust_root(monkeypatch, trust_root_file)

    with pytest.raises(operator_module.MechanicalBlocked, match=reason):
        operator_module.verify_external_mechanical_gate_receipt(
            receipt_file,
            trust_root_file,
            binding,
            now=GATE_RECEIPT_NOW,
        )


def test_mechanical_gate_trust_root_never_accepts_private_key_material(tmp_path, monkeypatch):
    receipt_file, trust_root_file, binding = _write_signed_gate_receipt(tmp_path)
    trust_root = json.loads(trust_root_file.read_text(encoding="utf-8"))
    trust_root["keys"]["independent-gate-test"]["private_key"] = "must-not-be-loaded"
    trust_root_file.write_text(json.dumps(trust_root), encoding="utf-8")
    _pin_gate_trust_root(monkeypatch, trust_root_file)

    with pytest.raises(operator_module.MechanicalBlocked, match="TRUST_ROOT_PRIVATE_KEY_FORBIDDEN"):
        operator_module.verify_external_mechanical_gate_receipt(
            receipt_file,
            trust_root_file,
            binding,
            now=GATE_RECEIPT_NOW,
        )


def test_mechanical_operator_cannot_load_or_create_approval_signatures():
    source = Path(operator_module.__file__).read_text(encoding="utf-8")

    assert "_private_signing_key" not in source
    assert "sign_payload(" not in source
    assert "_load_key(" not in source
    assert 'gate_statuses={"G1"' not in source


def test_mechanical_calendar_receipt_is_hash_frozen_and_exchange_bound(tmp_path):
    calendar_file = tmp_path / "calendar.json"
    calendar_file.write_text(
        json.dumps(
            {
                "schema_version": "iter22.czce-trading-calendar.v1",
                "exchange": "CZCE",
                "days": ["20260911"],
            }
        ),
        encoding="utf-8",
    )
    config = operator_module.MechanicalConfiguration(
        environment="second_7x24",
        product_id="SA",
        exchange_id="CZCE",
        future_instrument_id="SA701",
        call_instrument_id="SA701C1500",
        put_instrument_id="SA701P1500",
    )

    assert (
        operator_module._calendar_receipt_sha256(calendar_file, config)
        == hashlib.sha256(calendar_file.read_bytes()).hexdigest()
    )


def test_mechanical_run_requires_external_receipts_before_reading_credentials(
    tmp_path, monkeypatch
):
    def credentials_must_not_be_resolved(env):
        raise AssertionError("credentials must not be resolved without external approvals")

    monkeypatch.setattr(operator_module, "resolve_credentials", credentials_must_not_be_resolved)
    config = operator_module.MechanicalConfiguration(
        environment="second_7x24",
        product_id="SA",
        exchange_id="CZCE",
        future_instrument_id="SA701",
        call_instrument_id="SA701C1500",
        put_instrument_id="SA701P1500",
    )

    with pytest.raises(operator_module.MechanicalBlocked, match="MECHANICAL_EXECUTION_DISABLED"):
        operator_module.run_mechanical_cycle(config, {}, state_directory=tmp_path)


def test_disabled_mechanical_cli_does_not_read_environment_file(tmp_path, monkeypatch):
    def environment_must_not_be_read(path):
        raise AssertionError("disabled mechanical CLI must not read an environment file")

    monkeypatch.setattr(operator_module, "load_operator_env", environment_must_not_be_read)
    placeholder = tmp_path / "placeholder.json"

    assert (
        operator_module.main(
            [
                "--env",
                str(tmp_path / ".env"),
                "--gate-receipt",
                str(placeholder),
                "--gate-trust-root",
                str(placeholder),
                "--calendar-receipt",
                str(placeholder),
                "--settlement-approval",
                str(placeholder),
                "--entry-approval",
                str(placeholder),
            ]
        )
        == 2
    )
