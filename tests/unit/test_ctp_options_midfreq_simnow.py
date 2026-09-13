"""Mock-only safety and state-machine checks for the Iteration 24 adapter."""

from datetime import datetime, timezone
from pathlib import Path
import importlib

import pytest


run_module = importlib.import_module("examples.014_2_ctp_options_midfreq.run")
adapter = importlib.import_module("examples.014_2_ctp_options_midfreq.simnow_adapter")

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "014_2_ctp_options_midfreq"


class NoOpApi:
    """Injected SDK-shaped object; no method can connect or submit."""


def _flat_reconciliation(request_id_base: int) -> dict:
    request_ids = {
        "account": request_id_base,
        "positions": request_id_base + 1,
        "orders": request_id_base + 2,
        "trades": request_id_base + 3,
    }
    return {
        "schema_version": "backtrader.ctp.reconciliation.v1",
        "account_fingerprint": "acct",
        "trading_day": "20260911",
        "connection_generation": 7,
        "account": [],
        "positions": [],
        "orders": [],
        "trades": [],
        "complete": True,
        "is_last_seen": True,
        "timed_out": False,
        "error_code": None,
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "flat": True,
        "request_ids": request_ids,
        "all_request_ids": dict(request_ids),
    }


def test_cli_engineering_smoke_is_fail_closed_without_injected_api():
    config = run_module.load_config(EXAMPLE / "config.yaml")
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        run_module.run_engineering_smoke(config, api=None)
    assert error.value.code == "SDK_NOT_INJECTED"


def test_build_uses_one_native_store_feed_broker_cerebro_chain():
    config = run_module.load_config(EXAMPLE / "config.yaml")
    report = run_module.run_engineering_smoke(config, api=NoOpApi())
    assert report["status"] == "ENGINEERING_SMOKE_BUILT"
    assert report["chain"] == {
        "store": "BtApiStore",
        "feeds": ["BtApiFeed", "BtApiFeed", "BtApiFeed"],
        "broker": "BtApiBroker",
        "cerebro": "Cerebro",
    }
    assert report["external_network_requests"] == 0
    assert report["external_trade_writes"] == 0
    assert report["market_data_only"] is True
    assert report["execution_permission"] == "NOT_PROVEN"


def test_missing_trust_root_cannot_be_replaced_by_an_empty_grant():
    class Store:
        def configure_ctp_execution_authorization(self, grant):
            raise RuntimeError("CTP execution authorization trust root is unavailable")

    lifecycle = adapter.CtpStoreLifecycle(Store())
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        lifecycle.configure_authorization({})
    assert error.value.code == "TRUST_ROOT_UNAVAILABLE"


def test_realtime_cohort_and_fq2_are_strictly_causal():
    cutoff = datetime(2026, 9, 11, 1, 0, tzinfo=timezone.utc)
    events = [
        {"symbol": "F", "event_time": "2026-09-11T00:59:59Z", "recv_monotonic": 2, "generation": 3, "subscription_epoch": 4},
        {"symbol": "F", "event_time": "2026-09-11T01:00:00Z", "recv_monotonic": 3, "generation": 3, "subscription_epoch": 4},
        {"symbol": "F", "event_time": "2026-09-11T00:59:58Z", "recv_monotonic": 1, "generation": 2, "subscription_epoch": 4},
    ]
    accepted = adapter.causal_fq2_events(events, cutoff=cutoff, generation=3, subscription_epoch=4)
    assert len(accepted) == 1
    assert accepted[0].event_time < cutoff
    with pytest.raises(adapter.EngineeringSmokeBlocked):
        adapter.causal_fq2_events([{**events[0], "subscription_epoch": None}], cutoff=cutoff, generation=3, subscription_epoch=4)


def test_three_legs_only_progress_from_external_confirmations_and_recover_partial(tmp_path):
    journal = adapter.DurableExecutionJournal(tmp_path / "execution.jsonl")
    coordinator = adapter.ThreeLegExecutionCoordinator(("F", "C", "P"), journal)
    identity = {"account_fingerprint": "acct_test", "trading_day": "20260911", "generation": 7}
    coordinator.record_intent("basket-1", "F", 1, identity)
    terminal = {**identity, "order_id": "o1", "client_order_id": "c1"}
    coordinator.record_ack("basket-1", "F", "o1", "c1", identity)
    coordinator.record_fill("basket-1", "F", 0.5, terminal)
    assert coordinator.status == "PARTIAL"
    assert coordinator.recovery_required is True
    coordinator.mark_compensation("basket-1", "partial-leg", terminal)
    assert coordinator.status == "RECOVERY"
    lines = (tmp_path / "execution.jsonl").read_text(encoding="utf-8").splitlines()
    assert [line.split('"kind":')[1].split(",")[0].strip(' :"') for line in lines] == ["intent", "ack", "fill", "compensation_or_recovery"]


def test_fee_margin_and_real_schema_two_round_reconciliation_fail_closed():
    inputs = adapter.FeeMarginInputs(
        "account-query", "margin-query", {"F": 1, "C": 1, "P": 1}, {"F": 10, "C": 20, "P": 20},
        {"account_fingerprint": "acct", "trading_day": "20260911", "generation": "7"},
    )
    inputs.validate(("F", "C", "P"))
    rounds = (_flat_reconciliation(100), _flat_reconciliation(200))
    assert len(adapter.require_two_account_reconciliations(rounds)) == 2
    with pytest.raises(adapter.EngineeringSmokeBlocked):
        adapter.require_two_account_reconciliations(rounds[:1])
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        adapter.require_two_account_reconciliations((rounds[0], dict(rounds[0])))
    assert error.value.code == "RECONCILIATION_REQUEST_ID_REPLAY"


def test_non_flat_real_reconciliation_is_rejected():
    round_data = _flat_reconciliation(100)
    round_data.update({"positions": [{"instrument": "C"}], "flat": False})
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        adapter.require_two_account_reconciliations((round_data, round_data))
    assert error.value.code == "RECONCILIATION_NOT_FLAT"


def test_reconciliation_requires_stable_complete_store_evidence():
    first = _flat_reconciliation(100)
    changed = _flat_reconciliation(200)
    changed["account"] = [{"available": 9_999}]
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        adapter.require_two_account_reconciliations((first, changed))
    assert error.value.code == "RECONCILIATION_SEMANTIC_MISMATCH"

    empty_identity = _flat_reconciliation(300)
    empty_identity.update(
        {"account_fingerprint": "", "trading_day": "", "connection_generation": 0}
    )
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        adapter.require_two_account_reconciliations((empty_identity, _flat_reconciliation(400)))
    assert error.value.code == "RECONCILIATION_IDENTITY"

    missing_terminal = _flat_reconciliation(500)
    missing_terminal["is_last_seen"] = False
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        adapter.require_two_account_reconciliations((missing_terminal, _flat_reconciliation(600)))
    assert error.value.code == "RECONCILIATION_INCOMPLETE"


def test_reconciliation_request_ids_require_strict_integer_mirrors():
    malformed = _flat_reconciliation(100)
    malformed["all_request_ids"]["account"] = True
    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        adapter.require_two_account_reconciliations((malformed, _flat_reconciliation(200)))
    assert error.value.code == "RECONCILIATION_REQUEST_IDS_INVALID"


def test_startup_requires_real_bundle_preflight_evidence():
    class Store:
        def get_ctp_bundle_preflight_snapshot(self, *args, **kwargs):
            return {
                "schema_version": "backtrader.ctp.bundle-preflight.v2",
                "evidence_complete": False, "read_only_safe": True, "flat": True,
            }

    with pytest.raises(adapter.EngineeringSmokeBlocked) as error:
        adapter.CtpStoreLifecycle(Store()).startup([])
    assert error.value.code == "BUNDLE_PREFLIGHT_NOT_FLAT"
