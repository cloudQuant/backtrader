"""Offline contracts for the Iteration 25 engineering-smoke adapter."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import backtrader as bt
import pytest


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "examples/015_ctp_options_highfreq/engineering_smoke.py"
SPEC = importlib.util.spec_from_file_location("iter25_engineering_smoke", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class OfflineApi:
    """No network methods: construction must remain inert with this object."""


def _adapter(tmp_path, *, authorized=False):
    store = MODULE.BtApiStore(provider="btapi", api=OfflineApi(), cash=10_000, autostart=False)
    adapter = MODULE.EngineeringSmokeAdapter(
        store=store,
        symbols=("F", "C", "P"),
        session=MODULE.SessionIdentity("acct-hash", "20260911", 7, 3, "clk-1"),
        journal=MODULE.AppendOnlyJournal(tmp_path / "journal.jsonl"),
    )
    if authorized:
        adapter.store.configure_ctp_execution_authorization = lambda grant: {"configured": True}
        adapter.configure_execution_authorization({"mock": True})
    return adapter


def _tick(*, generation=7, symbol="F", seq=1):
    return SimpleNamespace(
        connection_generation=generation,
        clock_domain_id="clk-1",
        symbol=symbol,
        ingest_seq=seq,
        cohort_now=bt.feeds.CtpCohortNow(
            now_monotonic_ns=10_000,
            now_epoch="2026-09-11T01:00:00+00:00",
            clock_domain_id="clk-1",
            receive_clock_error_ms=0.0,
            receive_clock_quality="verified",
            freshness_verified=True,
        ),
    )


def test_constructs_one_native_chain_without_starting_or_writing(tmp_path):
    adapter = _adapter(tmp_path)

    assert adapter.runtime_chain == {
        "store": "backtrader.stores.btapistore.BtApiStore",
        "feed": ["backtrader.feeds.btapifeed.BtApiFeed"] * 3,
        "broker": "backtrader.brokers.btapibroker.BtApiBroker",
        "cerebro": "backtrader.cerebro.Cerebro",
        "strategy": "iter25_engineering_smoke._SmokeStrategy",
    }
    assert adapter.state.hft_status == "NOT_ADMITTED"
    assert adapter.report()["external_network_requests"] == 0
    assert adapter.report()["external_write_requests"] == 0


def test_arm_requires_settlement_bundle_and_two_round_reconciliation(tmp_path):
    adapter = _adapter(tmp_path)
    with pytest.raises(MODULE.EngineeringSmokeError, match="TRUST_ROOT"):
        adapter.arm_one_cycle(cycle_id="cycle-1", intent_id="intent-1")


def test_missing_trust_root_keeps_market_data_only_even_with_arming_proof(tmp_path):
    adapter = _adapter(tmp_path)
    with pytest.raises(MODULE.EngineeringSmokeError, match="TRUST_ROOT"):
        adapter.arm_one_cycle(cycle_id="cycle-1", intent_id="intent-1")
    assert adapter.report()["market_data_only"] is True
    assert adapter.report()["execution_authorized"] is False


def test_authorization_success_without_configured_true_does_not_unlock(tmp_path):
    adapter = _adapter(tmp_path)
    adapter.store.configure_ctp_execution_authorization = lambda grant: {"configured": False}
    with pytest.raises(MODULE.EngineeringSmokeError, match="NOT_CONFIGURED"):
        adapter.configure_execution_authorization({"mock": True})
    assert adapter.report()["market_data_only"] is True


def test_store_public_preflight_and_reconciliation_interfaces_are_the_only_query_boundary(
    tmp_path, monkeypatch
):
    adapter = _adapter(tmp_path)
    calls = []

    def preflight(legs, **kwargs):
        calls.append(("preflight", list(legs), kwargs))
        return {
            "snapshot_sha256": "bundle-hash",
            "evidence_complete": True,
            "read_only_safe": True,
            "flat": True,
            "account_fingerprint": "acct-hash",
            "trading_day": "20260911",
            "connection_generation": 7,
        }

    def reconciliation(**kwargs):
        calls.append(("reconciliation", kwargs))
        return {
            "schema_version": "backtrader.ctp.reconciliation.v1",
            "account": {},
            "positions": [],
            "orders": [],
            "trades": [],
            "evidence_complete": True,
            "read_only_safe": True,
            "write_request_free": True,
            "flat": True,
            "active_order_count": 0,
            "unknown_intent_count": 0,
            "unmatched_trade_count": 0,
            "account_fingerprint": "acct-hash",
            "connection_generation": 7,
            "trading_day": "20260911",
        }

    monkeypatch.setattr(adapter.store, "get_ctp_bundle_preflight_snapshot", preflight)
    monkeypatch.setattr(adapter.store, "get_ctp_reconciliation_snapshot", reconciliation)
    adapter.get_bundle_preflight(({"exchange_id": "CZCE", "instrument_id": leg} for leg in ("F", "C", "P")))
    assert adapter.reconcile_from_store() is False
    assert [call[0] for call in calls] == ["preflight", "reconciliation"]


def test_one_lot_association_cancel_before_trade_and_two_round_reconciliation(tmp_path):
    adapter = _adapter(tmp_path, authorized=True)
    adapter._bundle_preflight_verified = True
    adapter._settlement_verified = True
    adapter.reconcile(_safe_reconciliation(1_000))
    adapter.reconcile(_safe_reconciliation(2_000))
    adapter.arm_one_cycle(cycle_id="cycle-1", intent_id="intent-1")
    adapter.authorize_one_lot_write()
    association = MODULE.NativeAssociation(
        cycle_id="cycle-1",
        intent_id="intent-1",
        bt_order_ref="bt-1",
        order_ref="native-1",
        generation=7,
        symbol="F",
        requested_volume=1,
    )
    adapter.record_send(association)
    adapter.request_cancel(order_ref="native-1")
    adapter.on_trade_event(SimpleNamespace(trade_id="trade-late"))

    assert "cancel_before_trade" in adapter.state.classifications
    adapter.reconcile(_safe_reconciliation(3_000))
    adapter.reconcile(_safe_reconciliation(4_000))
    assert adapter.state.status == "FLAT_VERIFIED"
    assert adapter.report()["hft_status"] == "NOT_ADMITTED"
    assert adapter.report()["pnl_fields_emitted"] is False


def test_generation_change_blocks_and_unknown_is_not_recovered_by_one_snapshot(tmp_path):
    adapter = _adapter(tmp_path)
    adapter.on_tick(_tick())
    adapter.on_reconnect(
        session=MODULE.SessionIdentity("acct-hash", "20260911", 8, 1, "clk-1")
    )
    assert adapter.state.status == "RECOVERING"
    assert adapter.state.ordinary_entry_blocked is True
    assert adapter.reconcile(
        {
            "schema_version": "backtrader.ctp.reconciliation.v1",
            "account": {},
            "positions": [],
            "orders": [],
            "trades": [],
            "evidence_complete": True,
            "read_only_safe": True,
            "write_request_free": True,
            "flat": True,
            "active_order_count": 0,
            "unknown_intent_count": 0,
            "unmatched_trade_count": 0,
            "account_fingerprint": "acct-hash",
            "connection_generation": 8,
            "trading_day": "20260911",
        }
    ) is False
    assert adapter.state.status == "RECOVERING"


def test_stale_tick_and_unknown_order_never_change_hft_status(tmp_path):
    adapter = _adapter(tmp_path)
    adapter.on_tick(_tick(generation=6))
    adapter.on_order_event(SimpleNamespace(status="unknown", order_ref="o-1"))

    assert adapter.state.status == "UNKNOWN"
    assert adapter.state.reason == "EXECUTION_UNKNOWN"
    assert adapter.report()["hft_status"] == "NOT_ADMITTED"
    assert adapter.report()["actual_fills"] == 0


def _safe_reconciliation(captured_at):
    return {
        "schema_version": "backtrader.ctp.reconciliation.v1",
        "account_fingerprint": "acct-hash",
        "trading_day": "20260911",
        "connection_generation": 7,
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "account": {"available": 10_000},
        "positions": [],
        "orders": [],
        "trades": [],
        "captured_at": captured_at,
    }


@pytest.mark.parametrize(
    "field,value",
    [("flat", False), ("unknown_intent_count", 1), ("evidence_complete", False)],
)
def test_unsafe_real_reconciliation_schema_rejects_and_resets_rounds(tmp_path, field, value):
    adapter = _adapter(tmp_path)
    snapshot = _safe_reconciliation(1)
    snapshot[field] = value
    assert adapter.reconcile(snapshot) is False
    assert adapter.state.reconciliation_rounds == 0
    assert adapter.state.ordinary_entry_blocked is True
