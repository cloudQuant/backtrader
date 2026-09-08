import importlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import stat
import time

import pytest
import yaml
from bt_api_py import FeeSchedule, Freshness, FundingSnapshot, InstrumentSpec

RUNNERS = [
    importlib.import_module("examples.012_1_midfreq_cross_exchange.run"),
    importlib.import_module("examples.012_2_event_driven_cross_exchange.run"),
]


def _freshness():
    return Freshness(
        source="exchange",
        observed_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )


def _instrument_spec(symbol="BTC-USDT-SWAP"):
    return InstrumentSpec(
        exchange_name="OKX___SWAP" if "-" in symbol else "BINANCE___SWAP",
        symbol=symbol,
        asset_type="swap",
        base_currency="BTC",
        quote_currency="USDT",
        contract_type="linear",
        linear=True,
        contract_value=Decimal("0.01") if "-" in symbol else Decimal("1"),
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.1"),
        quantity_step=Decimal("1") if "-" in symbol else Decimal("0.001"),
        min_quantity=Decimal("1") if "-" in symbol else Decimal("0.001"),
        max_quantity=None,
        min_notional=Decimal("0"),
        quantity_unit="contracts" if "-" in symbol else "base",
        status="live",
        freshness=_freshness(),
        raw_rule_fingerprint="a" * 64,
    )


def _funding_snapshot(symbol="BTC-USDT-SWAP", *, available=True):
    return FundingSnapshot(
        exchange_name="OKX___SWAP" if "-" in symbol else "BINANCE___SWAP",
        symbol=symbol,
        rate=Decimal("0.001") if available else None,
        next_funding_time=datetime(2099, 1, 1, tzinfo=timezone.utc) if available else None,
        settlement_interval_seconds=28_800 if available else None,
        source="exchange" if available else "unavailable",
        freshness=_freshness(),
        available=available,
        unavailable_reason=None if available else "funding_unavailable",
    )


def _fee_schedule(symbol="BTC-USDT-SWAP", *, available=True):
    return FeeSchedule(
        exchange_name="OKX___SWAP" if "-" in symbol else "BINANCE___SWAP",
        symbol=symbol,
        account_id="canonical-demo-account",
        maker_rate=Decimal("0.0004") if available else None,
        taker_rate=Decimal("0.0004") if available else None,
        currency="USDT",
        source="exchange" if available else "unavailable",
        freshness=_freshness(),
        available=available,
        unavailable_reason=None if available else "fee_unavailable",
    )


@pytest.mark.parametrize("runner", RUNNERS)
def test_ac_cfg_001_mode_policy_is_unique_and_invalid_modes_fail(runner):
    policies = {mode: runner.mode_policy(mode) for mode in runner.MODES}

    assert policies["replay"]["network"] is False
    assert policies["shadow"]["sdk_writes"] is False
    assert policies["shadow"]["fills_forbidden"] is True
    assert policies["paper-live"]["hypothetical_fills"] is True
    assert policies["demo"]["sdk_writes"] is True
    with pytest.raises(runner.RunnerConfigurationError, match="unsupported mode"):
        runner.mode_policy("paper-demo")
    with pytest.raises(SystemExit):
        runner.build_parser().parse_args(["--mode", "typo"])


@pytest.mark.parametrize("runner", RUNNERS)
def test_network_admission_enforces_manifest_modes_status_and_config(runner):
    config = runner.load_config()
    rejected_manifest = {"manifest_status": "RESEARCH_REJECTED_DEMO_PROHIBITED"}
    rejected = {
        "research_status": "RESEARCH_REJECTED",
        "allowed_modes": ["replay", "shadow"],
        "conditional_modes": {
            "paper-live": "PROHIBITED_RESEARCH_REJECTED",
            "demo": "PROHIBITED_RESEARCH_REJECTED",
        },
    }

    preflight = runner._validate_network_admission(
        rejected_manifest, rejected, "demo", True, config
    )
    assert preflight["preflight_only"] is True
    assert preflight["execution_admitted"] is False
    with pytest.raises(runner.RunnerConfigurationError, match="preflight is only valid"):
        runner._validate_network_admission(rejected_manifest, rejected, "shadow", True, config)
    with pytest.raises(runner.DemoApprovalError, match="PASS research candidate"):
        runner._validate_network_admission(rejected_manifest, rejected, "demo", False, config)

    approved = {
        "research_status": "PASS",
        "allowed_modes": ["replay", "shadow", "paper-live", "demo"],
        "conditional_modes": {},
    }
    with pytest.raises(runner.DemoApprovalError, match="manifest_status"):
        runner._validate_network_admission(rejected_manifest, approved, "demo", False, config)
    with pytest.raises(runner.RunnerConfigurationError, match="manifest_status"):
        runner._validate_network_admission(rejected_manifest, approved, "paper-live", False, config)
    paper = runner._validate_network_admission(
        {"manifest_status": "PAPER_LIVE_APPROVED"},
        approved,
        "paper-live",
        False,
        config,
    )
    assert paper["execution_admitted"] is True
    config["mode"] = "shadow"
    with pytest.raises(runner.RunnerConfigurationError, match="configuration mode"):
        runner._validate_network_admission(
            {"manifest_status": "DEMO_APPROVED"}, approved, "demo", False, config
        )


@pytest.mark.parametrize("runner", RUNNERS)
def test_network_duration_is_bounded_by_candidate_config_and_signed_lease(runner):
    config = runner.load_config()
    configured = Decimal(str(config["run_timeout_seconds"]))
    assert runner._bounded_requested_duration(configured, config) == configured
    with pytest.raises(runner.RunnerConfigurationError, match="candidate-bound"):
        runner._bounded_requested_duration(configured + 1, config)

    now = datetime(2026, 9, 8, 4, 0, tzinfo=timezone.utc)
    expires_at = now + timedelta(seconds=float(configured + 60))
    receipt = {
        "expires_at": expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "constraints": {
            "maximum_duration_seconds": str(configured),
            "maximum_order_count": 8,
            "maximum_quantity_base": "0.01",
        },
    }
    risk = runner.risk_from_config(config)
    shutdown = Decimal(str(config["observation"]["shutdown_buffer_seconds"]))

    lease = runner._approval_lease(receipt, configured, risk, shutdown, now=now)

    assert lease["maximum_order_count"] == 8
    assert lease["expires_at"] == receipt["expires_at"]
    with pytest.raises(runner.DemoApprovalError, match="signed demo approval limit"):
        runner._approval_lease(receipt, configured + 1, risk, shutdown, now=now)
    receipt["constraints"]["maximum_quantity_base"] = "0.001"
    with pytest.raises(runner.DemoApprovalError, match="quantity exceeds"):
        runner._approval_lease(receipt, configured, risk, shutdown, now=now)


@pytest.mark.parametrize("runner", RUNNERS)
def test_demo_lease_status_must_match_receipt_and_stay_within_operation_budget(runner):
    lease = {
        "expires_at": "2026-09-08T05:00:00Z",
        "maximum_order_count": 8,
    }
    status = {
        "enabled": True,
        "expires_at_utc": lease["expires_at"],
        "maximum_order_count": 8,
        "operation_count": 8,
    }

    assert runner._approval_lease_status_proven(status, lease) is True
    assert runner._approval_lease_status_proven(dict(status, operation_count=9), lease) is False
    assert runner._approval_lease_status_proven(dict(status, enabled=False), lease) is False


@pytest.mark.parametrize("runner", RUNNERS)
def test_demo_broker_receives_the_signed_expiry_and_operation_budget(runner):
    lease = {
        "expires_at": "2026-09-08T05:00:00Z",
        "maximum_order_count": 8,
    }

    kwargs = runner._demo_broker_kwargs(lease, Decimal("15"))

    assert kwargs == {
        "position_mode": "dual_side",
        "position_sync_policy": "startup",
        "shutdown_timeout": 15.0,
        "approval_expires_at_utc": lease["expires_at"],
        "approval_max_order_count": 8,
    }


@pytest.mark.parametrize("runner", RUNNERS)
def test_preflight_pass_requires_complete_two_venue_readiness(runner):
    complete = {"status": "PASS", "venues": {venue: {} for venue in runner.VENUE_SYMBOLS}}

    assert runner._preflight_readiness_complete(complete) is True
    assert runner._preflight_readiness_complete(dict(complete, status="INCOMPLETE")) is False
    assert runner._preflight_readiness_complete({"status": "PASS", "venues": {"okx": {}}}) is False


@pytest.mark.parametrize("runner", RUNNERS)
def test_ac_cfg_003_unknown_config_fields_and_schema_fail_early(runner, tmp_path):
    config = runner.load_config()
    config["unexpected"] = True
    path = tmp_path / "unknown.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(runner.RunnerConfigurationError, match="unknown top-level"):
        runner.load_config(path)

    config.pop("unexpected")
    config["schema_version"] = 1
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(runner.RunnerConfigurationError, match="schema_version"):
        runner.load_config(path)


@pytest.mark.parametrize("runner", RUNNERS)
def test_ac_cfg_007_duration_covers_statistics_holding_and_shutdown(runner):
    config = runner.load_config()
    risk = runner.risk_from_config(config)
    required = runner.required_observation_duration(config, risk)

    with pytest.raises(runner.RunnerConfigurationError, match="below required"):
        runner.validate_duration(required - Decimal(".001"), config, risk)
    report = runner.validate_duration(required, config, risk)
    assert Decimal(report["requested_seconds"]) == required
    assert Decimal(report["maximum_holding_seconds"]) == risk.maximum_holding_seconds


def test_duration_gate_can_require_a_funding_settlement():
    runner = RUNNERS[0]
    config = runner.load_config()
    config["observation"]["require_funding_settlement"] = True
    risk = runner.risk_from_config(config)
    required = runner.required_observation_duration(config, risk)

    with pytest.raises(runner.RunnerConfigurationError, match="funding settlement"):
        runner.validate_duration(required, config, risk, next_funding_times=[])


@pytest.mark.parametrize("runner", RUNNERS)
def test_funding_duration_uses_active_window_and_requires_both_venues(runner, monkeypatch):
    config = runner.load_config()
    config["observation"]["require_funding_settlement"] = True
    risk = runner.risk_from_config(config)
    requested = runner.required_observation_duration(config, risk)
    shutdown = Decimal(str(config["observation"]["shutdown_buffer_seconds"]))
    active = requested - shutdown
    margin = Decimal(str(config["funding"]["refresh_interval_seconds"]))
    monkeypatch.setattr(runner.time, "time", lambda: 1000.0)

    report = runner.validate_duration(
        requested,
        config,
        risk,
        next_funding_times=[Decimal("1000") + active - margin - Decimal(".001")]
        * len(runner.VENUE_SYMBOLS),
        active_observation_seconds=active,
    )
    assert Decimal(report["funding_horizon_seconds"]) == active
    assert Decimal(report["funding_observation_margin_seconds"]) == margin

    with pytest.raises(runner.RunnerConfigurationError, match="funding settlement"):
        runner.validate_duration(
            requested,
            config,
            risk,
            next_funding_times=[
                Decimal("1000") + active - margin - Decimal(".001"),
                Decimal("1000") + active - margin,
            ],
            active_observation_seconds=active,
        )
    with pytest.raises(runner.RunnerConfigurationError, match="funding settlement"):
        runner.validate_duration(
            requested,
            config,
            risk,
            next_funding_times=[Decimal("1000") + active],
            active_observation_seconds=active,
        )


@pytest.mark.parametrize("runner", RUNNERS)
def test_funding_refresh_settings_require_a_positive_refresh_below_ttl(runner):
    config = runner.load_config()
    settings = runner.funding_settings_from_config(config)

    assert Decimal("0") < settings["refresh_interval_seconds"] < settings["max_age_seconds"]

    config["funding"]["refresh_interval_seconds"] = config["funding"]["max_age_seconds"]
    with pytest.raises(runner.RunnerConfigurationError, match="funding refresh"):
        runner.funding_settings_from_config(config)


@pytest.mark.parametrize("runner", RUNNERS)
def test_demo_funding_gate_reads_the_canonical_cashflow_field(runner):
    proven = {
        "execution_economics": [
            {
                "funding_evidence_status": "actual_ledger",
                "signed_funding_cashflow": "0",
            }
        ]
    }
    legacy_mismatch = {
        "execution_economics": [{"funding_evidence_status": "actual_ledger", "signed_funding": "0"}]
    }

    assert runner._funding_economics_proven(proven) is True
    assert runner._funding_economics_proven(legacy_mismatch) is False


@pytest.mark.parametrize("runner", RUNNERS)
def test_runtime_funding_provider_reads_only_store_cache_with_explicit_ttl(runner):
    calls = []

    class Store:
        def get_cached_funding_snapshot(self, symbol, *, max_age_seconds):
            calls.append((symbol, max_age_seconds))
            return _funding_snapshot()

    result = runner._cached_funding_provider(Store(), Decimal("17.5"))()

    assert set(result) == set(runner.VENUE_SYMBOLS)
    assert calls == [(runner.VENUE_SYMBOLS[venue], 17.5) for venue in runner.VENUE_SYMBOLS]


def test_funding_boundary_converts_aware_datetime_to_unix_epoch():
    runner = RUNNERS[0]

    class Store:
        def get_typed_funding_snapshot(self, symbol):
            return _funding_snapshot(symbol)

    result = runner._funding_from_store(Store())

    assert result["okx"][0] == Decimal("0.001")
    assert result["okx"][1] == Decimal("4070908800.0")
    assert result["okx"][2:] == (Decimal("28800"), "exchange")


@pytest.mark.parametrize("runner", RUNNERS)
def test_public_funding_rejects_an_expired_exchange_schedule(runner):
    class Store:
        def get_typed_funding_snapshot(self, symbol):
            return replace(
                _funding_snapshot(symbol),
                next_funding_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
                freshness=Freshness(
                    source="exchange",
                    observed_at=datetime(2019, 1, 1, tzinfo=timezone.utc),
                ),
            )

    with pytest.raises(runner.RunnerConfigurationError, match="funding_schedule_expired"):
        runner._funding_from_store(Store())


@pytest.mark.parametrize("runner", RUNNERS)
def test_public_shadow_uses_instrument_spec_and_conservative_fee_without_private_call(runner):
    class Store:
        def __init__(self):
            self.instrument_calls = 0
            self.fee_calls = 0

        def get_typed_instrument_spec(self, symbol):
            self.instrument_calls += 1
            return _instrument_spec(symbol)

        def get_typed_fee_schedule(self, *_args, **_kwargs):
            self.fee_calls += 1
            raise AssertionError("shadow must not read an account fee schedule")

    store = Store()
    rules, sources = runner._rules_from_store(store, "shadow")

    assert store.instrument_calls == 2
    assert store.fee_calls == 0
    assert {rule.taker_fee for rule in rules.values()} == {Decimal("0.0006")}
    assert sources == {"okx": "conservative_bound", "binance": "conservative_bound"}
    exchange_kwargs = runner._exchange_kwargs("shadow")
    assert exchange_kwargs[runner.EXCHANGES["okx"]] == {
        "environment": "production",
        "api_region": "global",
    }
    assert exchange_kwargs[runner.EXCHANGES["binance"]] == {"environment": "production"}


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("api_region", ["global", "eea", "us"])
def test_okx_api_region_is_passed_to_the_native_provider(runner, api_region):
    exchange_kwargs = runner._exchange_kwargs("demo", okx_api_region=api_region)

    assert exchange_kwargs[runner.EXCHANGES["okx"]] == {
        "environment": "demo",
        "api_region": api_region,
    }
    assert exchange_kwargs[runner.EXCHANGES["binance"]] == {"environment": "demo"}


@pytest.mark.parametrize("runner", RUNNERS)
def test_okx_api_region_rejects_unknown_values_and_unverified_tr_demo(runner, tmp_path):
    config = runner.load_config()
    config["okx_api_region"] = "apac"
    path = tmp_path / "invalid-region.yaml"
    path.write_text(yaml.safe_dump(config))

    with pytest.raises(runner.RunnerConfigurationError, match="okx_api_region"):
        runner.load_config(path)
    with pytest.raises(runner.RunnerConfigurationError, match="TR demo endpoints"):
        runner._exchange_kwargs("demo", okx_api_region="tr")


@pytest.mark.parametrize("runner", RUNNERS)
def test_demo_requires_typed_available_account_fee_schedule(runner):
    class Store:
        def get_typed_instrument_spec(self, symbol):
            return _instrument_spec(symbol)

        def get_typed_fee_schedule(self, symbol):
            return _fee_schedule(symbol)

    rules, sources = runner._rules_from_store(Store(), "demo")

    assert {rule.taker_fee for rule in rules.values()} == {Decimal("0.0004")}
    assert sources == {
        "okx": "account_fee_schedule:exchange",
        "binance": "account_fee_schedule:exchange",
    }


@pytest.mark.parametrize("runner", RUNNERS)
def test_demo_and_public_funding_fail_closed_when_typed_contract_is_unavailable(runner):
    class MissingFeeStore:
        def get_typed_instrument_spec(self, symbol):
            return _instrument_spec(symbol)

        def get_typed_fee_schedule(self, symbol):
            return _fee_schedule(symbol, available=False)

    class MissingFundingStore:
        def get_typed_funding_snapshot(self, symbol):
            return _funding_snapshot(symbol, available=False)

    with pytest.raises(runner.RunnerConfigurationError, match="FeeSchedule is unavailable"):
        runner._rules_from_store(MissingFeeStore(), "demo")
    with pytest.raises(runner.RunnerConfigurationError, match="FundingSnapshot is unavailable"):
        runner._funding_from_store(MissingFundingStore())


@pytest.mark.parametrize("runner", RUNNERS)
def test_demo_account_risk_proof_is_owned_by_current_monotonic_clock(runner):
    current_pid = os.getpid()
    now_monotonic_ns = time.monotonic_ns()
    identity = "a" * 64
    execution_summary = {
        "fencing_epoch": 7,
        "identity_binding_sha256": identity,
    }
    snapshot = {
        "generation": 1,
        "fencing_epoch": 7,
        "as_of_monotonic_ns": now_monotonic_ns,
        "owner_pid": current_pid,
        "clock_domain_id": f"process:{current_pid}:monotonic",
        "baseline_equity": "1000",
        "current_equity": "1000",
        "configured_venues": list(runner.VENUE_SYMBOLS),
        "durable": True,
        "trading_blocked": False,
        "evidence_complete": True,
        "evidence_errors": [],
        "error_code": None,
        "identity_binding_sha256": identity,
    }

    assert runner._account_risk_proven(snapshot, execution_summary) is True

    invalid = dict(snapshot, owner_pid=current_pid + 1)
    assert runner._account_risk_proven(invalid, execution_summary) is False
    invalid = dict(snapshot, clock_domain_id=f"process:{current_pid + 1}:monotonic")
    assert runner._account_risk_proven(invalid, execution_summary) is False
    invalid = dict(snapshot, as_of_monotonic_ns=time.monotonic_ns() + 10**9)
    assert runner._account_risk_proven(invalid, execution_summary) is False


@pytest.mark.parametrize("runner", RUNNERS)
def test_demo_readiness_refreshes_persisted_risk_before_strict_reconciliation(runner):
    events = []
    identity = "a" * 64
    pid = os.getpid()
    account_risk = {
        "generation": 1,
        "fencing_epoch": 1,
        "as_of_monotonic_ns": time.monotonic_ns(),
        "owner_pid": pid,
        "clock_domain_id": f"process:{pid}:monotonic",
        "baseline_equity": "1000",
        "current_equity": "1000",
        "configured_venues": list(runner.VENUE_SYMBOLS),
        "durable": True,
        "trading_blocked": False,
        "evidence_complete": True,
        "evidence_errors": [],
        "error_code": None,
        "identity_binding_sha256": identity,
    }

    def execution_summary(error=None):
        return {
            "active_orders": 0,
            "generation": 1,
            "fencing_epoch": 1,
            "as_of_monotonic_ns": time.monotonic_ns(),
            "session_enabled": True,
            "identity_binding_sha256": identity,
            "evidence_complete": True,
            "trading_blocked": error is not None,
            "unknown_ids": [],
            "fee_unresolved_orders": [],
            "funding_unresolved_orders": [],
            "evidence_errors": [error] if error else [],
            "error_code": None,
        }

    class Store:
        risk_refreshed = False

        def get_environment_info(self, symbol):
            events.append(("environment", symbol))
            return {"environment": "demo"}

        def get_account_config(self, symbol):
            events.append(("account", symbol))
            return {"position_mode": "dual_side", "can_trade": True}

        def get_order_readiness(self, symbol, quantity, position_mode):
            events.append(("readiness", symbol))
            return {"ready": True}

        def get_account_risk_snapshot(self):
            events.append(("risk", self.risk_refreshed))
            self.risk_refreshed = True
            return account_risk

        def get_reconcile_snapshot(self):
            events.append(("reconcile", self.risk_refreshed))
            error = None if self.risk_refreshed else "account_risk_snapshot_refresh_required"
            return {
                "configured_venues": list(runner.VENUE_SYMBOLS),
                "reconciled_venues": list(runner.VENUE_SYMBOLS),
                "positions": [],
                "open_orders": [],
                "execution_summary": execution_summary(error),
                "identity_binding_sha256": identity,
                "evidence_complete": True,
                "evidence_errors": [],
            }

        def initialize_account_risk_baseline(self):
            raise AssertionError("persisted baseline must not be initialized again")

    report = runner._readiness(
        Store(), runner.replay_rules(), runner.risk_from_config(runner.load_config())
    )

    assert report["status"] == "PASS"
    assert report["local_persistence"] == {
        "account_risk_baseline_initialized": False,
        "may_write_local_execution_ledger": False,
    }
    assert events.index(("risk", False)) < events.index(("reconcile", True))
    assert not any(event == ("reconcile", False) for event in events)


@pytest.mark.parametrize("runner", RUNNERS)
def test_demo_readiness_finishes_reads_before_baseline_write_then_reconciles_again(runner):
    events = []
    identity = "a" * 64
    pid = os.getpid()

    def summary(generation, baseline_required=False):
        result = {
            "active_orders": 0,
            "generation": generation,
            "fencing_epoch": generation,
            "as_of_monotonic_ns": time.monotonic_ns(),
            "session_enabled": True,
            "identity_binding_sha256": identity,
            "evidence_complete": True,
            "trading_blocked": False,
            "unknown_ids": [],
            "fee_unresolved_orders": [],
            "funding_unresolved_orders": [],
            "evidence_errors": [],
            "error_code": None,
        }
        if baseline_required:
            result["evidence_errors"] = ["account_risk_baseline_required"]
            result["trading_blocked"] = True
        return result

    def reconcile(generation, baseline_required=False):
        execution = summary(generation, baseline_required=baseline_required)
        return {
            "configured_venues": list(runner.VENUE_SYMBOLS),
            "reconciled_venues": list(runner.VENUE_SYMBOLS),
            "positions": [],
            "open_orders": [],
            "execution_summary": execution,
            "identity_binding_sha256": identity,
            "evidence_complete": True,
            "evidence_errors": [],
        }

    risk_snapshot = {
        "generation": 2,
        "fencing_epoch": 2,
        "as_of_monotonic_ns": time.monotonic_ns(),
        "owner_pid": pid,
        "clock_domain_id": f"process:{pid}:monotonic",
        "baseline_equity": "1000",
        "current_equity": "1000",
        "configured_venues": list(runner.VENUE_SYMBOLS),
        "durable": True,
        "trading_blocked": False,
        "evidence_complete": True,
        "evidence_errors": [],
        "error_code": None,
        "identity_binding_sha256": identity,
    }

    class Store:
        initialized = False

        def get_environment_info(self, symbol):
            events.append(("environment", symbol))
            return {"environment": "demo"}

        def get_account_config(self, symbol):
            events.append(("account", symbol))
            return {"position_mode": "dual_side", "can_trade": True}

        def get_order_readiness(self, symbol, quantity, position_mode):
            events.append(("readiness", symbol))
            return {"ready": True}

        def get_reconcile_snapshot(self):
            events.append(("reconcile", self.initialized))
            return reconcile(
                2 if self.initialized else 1,
                baseline_required=not self.initialized,
            )

        def get_account_risk_snapshot(self):
            events.append(("risk", self.initialized))
            return (
                risk_snapshot
                if self.initialized
                else {
                    "baseline_equity": None,
                    "loss_limit_breached": False,
                    "blocked_reasons": ["baseline_missing"],
                }
            )

        def initialize_account_risk_baseline(self):
            events.append(("initialize", True))
            self.initialized = True
            return risk_snapshot

    report = runner._readiness(
        Store(), runner.replay_rules(), runner.risk_from_config(runner.load_config())
    )

    assert report["status"] == "PASS"
    assert report["exchange_operations"] == "READ_ONLY"
    assert report["local_persistence"] == {
        "account_risk_baseline_initialized": True,
        "may_write_local_execution_ledger": True,
    }
    initialize_index = events.index(("initialize", True))
    assert all(
        name in {"environment", "account", "readiness", "reconcile", "risk"}
        for name, _ in events[:initialize_index]
    )
    assert events.count(("reconcile", False)) == 1
    assert events.count(("reconcile", True)) == 1


@pytest.mark.parametrize("runner", RUNNERS)
def test_baseline_startup_latch_does_not_relax_other_execution_errors(runner):
    identity = "a" * 64
    summary = {
        "active_orders": 0,
        "generation": 1,
        "fencing_epoch": 1,
        "as_of_monotonic_ns": time.monotonic_ns(),
        "session_enabled": True,
        "identity_binding_sha256": identity,
        "evidence_complete": True,
        "trading_blocked": True,
        "unknown_ids": [],
        "fee_unresolved_orders": [],
        "funding_unresolved_orders": [],
        "evidence_errors": [
            "account_risk_baseline_required",
            "execution_persistence_failed",
        ],
        "error_code": None,
    }
    snapshot = {
        "configured_venues": list(runner.VENUE_SYMBOLS),
        "reconciled_venues": list(runner.VENUE_SYMBOLS),
        "positions": [],
        "open_orders": [],
        "execution_summary": summary,
        "identity_binding_sha256": identity,
        "evidence_complete": True,
        "evidence_errors": [],
    }

    assert runner._reconcile_snapshot_ready_for_baseline(snapshot) is False
    for error in ("account_risk_snapshot_refresh_required", "execution_persistence_failed"):
        snapshot["execution_summary"] = dict(
            summary,
            evidence_errors=[error],
        )
        assert runner._reconcile_snapshot_ready_for_baseline(snapshot) is False


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize("failure_stage", ("store_start", "readiness"))
@pytest.mark.parametrize("inflight", ([], 0))
def test_demo_preflight_failure_is_redacted_persisted_and_closes_store(
    runner, failure_stage, inflight, monkeypatch, tmp_path, capsys
):
    manifest = json.loads(Path(runner.MANIFEST_PATH).read_text(encoding="utf-8"))
    candidate = next(
        row for row in manifest["candidates"] if row["strategy_id"] == runner.STRATEGY_ID
    )
    manifest_path = Path(runner.MANIFEST_PATH).resolve()
    monkeypatch.setattr(
        runner,
        "load_candidate",
        lambda _path: (manifest, candidate, manifest_path),
    )

    secret = "NEVER_SERIALIZE_THIS_CREDENTIAL"
    account = "NEVER_SERIALIZE_THIS_ACCOUNT"
    calls = []

    class VendorError(RuntimeError):
        code = "50119"

    class Store:
        def start(self):
            calls.append("start")
            if failure_stage == "store_start":
                raise VendorError(f"api_key={secret} account_id={account}")

        def stop(self, timeout):
            calls.append(("stop", timeout))
            return {
                "shutdown_state": "PASS",
                "queue_depth": 0,
                "inflight": inflight,
                "worker_alive": False,
                "close_thread_alive": False,
                "broker_update_conservation": True,
                "last_error_code": None,
                "credential": secret,
                "account_id": account,
            }

    monkeypatch.setattr(runner, "build_store", lambda *_args, **_kwargs: Store())
    monkeypatch.setattr(
        runner,
        "_rules_from_store",
        lambda _store, _mode: (
            runner.replay_rules(),
            dict.fromkeys(runner.VENUE_SYMBOLS, "exchange"),
        ),
    )
    monkeypatch.setattr(
        runner,
        "_funding_from_store",
        lambda _store: {
            venue: (
                Decimal("0"),
                datetime(2099, 1, 1, tzinfo=timezone.utc),
                28_800,
                "exchange",
            )
            for venue in runner.VENUE_SYMBOLS
        },
    )
    monkeypatch.setattr(runner, "validate_duration", lambda *_args, **_kwargs: {"status": "PASS"})

    def readiness(*_args, **_kwargs):
        if failure_stage == "readiness":
            raise VendorError(f"api_secret={secret} account={account}")
        raise AssertionError("readiness must not run after a start failure")

    monkeypatch.setattr(runner, "_readiness", readiness)
    output = tmp_path / f"{runner.STRATEGY_ID}-{failure_stage}.json"

    exit_code = runner.main(
        [
            "--mode",
            "demo",
            "--preflight",
            "--duration",
            str(runner.load_config()["run_timeout_seconds"]),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    assert output.is_file()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "PREFLIGHT_FAILED"
    assert report["readiness_complete"] is False
    assert report["orders_submitted"] == report["fills"] == 0
    assert report["execution_status"] == "NOT_RUN"
    assert report["store_stop_proven"] is True
    assert report["preflight_failure"] == {
        "failure_code": "PREFLIGHT_OPERATION_FAILED",
        "stage": failure_stage,
        "exception_type": "VendorError",
        "exchange_error_code": "50119",
        "detail": "REDACTED",
    }
    assert report["store_health"] == {
        "shutdown_state": "PASS",
        "queue_depth": 0,
        "inflight_count": 0,
        "worker_alive": False,
        "close_thread_alive": False,
        "broker_update_conservation": True,
        "last_error_present": False,
    }
    serialized = output.read_text(encoding="utf-8") + capsys.readouterr().out
    assert secret not in serialized
    assert account not in serialized
    assert calls[0] == "start"
    assert calls[-1][0] == "stop"


@pytest.mark.parametrize("runner", RUNNERS)
def test_preflight_failure_uses_finite_safe_readiness_code(runner):
    failure = runner.RunnerConfigurationError(
        "binance demo environment or dual-side mode is not ready"
    )

    assert runner._safe_preflight_failure_code(failure) == (
        "BINANCE_ENVIRONMENT_OR_POSITION_MODE_NOT_READY"
    )
    assert runner._safe_preflight_failure_code(RuntimeError("api_key=secret")) == (
        "PREFLIGHT_OPERATION_FAILED"
    )


@pytest.mark.parametrize("runner", RUNNERS)
def test_preflight_readiness_summary_excludes_private_account_payloads(runner):
    secret = "NEVER_SERIALIZE_PRIVATE_ACCOUNT_STATE"
    summary = runner._preflight_readiness_summary(
        {
            "status": "PASS",
            "venues": {
                "okx": {
                    "environment": {
                        "environment": "demo",
                        "simulated": True,
                        "verified": True,
                        "api_region": "global",
                        "credential": secret,
                    },
                    "position_mode": "dual_side",
                    "can_trade": True,
                    "ready": True,
                    "account_id": secret,
                },
                "binance": {
                    "environment": {
                        "environment": "demo",
                        "simulated": True,
                        "verified": True,
                        "credential": secret,
                    },
                    "position_mode": "dual_side",
                    "can_trade": True,
                    "ready": True,
                    "account_id": secret,
                },
            },
            "positions": [{"account_id": secret}],
            "open_orders": [{"client_order_id": secret}],
            "reconcile_snapshot": {"account_id": secret},
            "execution_summary": {"account_id": secret},
            "account_risk_snapshot": {"balance": secret},
            "exchange_operations": "READ_ONLY",
            "local_persistence": {
                "account_risk_baseline_initialized": True,
                "may_write_local_execution_ledger": True,
                "path": secret,
            },
        }
    )

    serialized = json.dumps(summary, sort_keys=True)
    assert secret not in serialized
    assert summary["status"] == "PASS"
    assert summary["position_count"] == 1
    assert summary["open_order_count"] == 1
    assert set(summary["venues"]) == {"okx", "binance"}
    assert summary["venues"]["okx"]["api_region"] == "global"
    assert summary["venues"]["binance"]["api_region"] is None


@pytest.mark.parametrize("runner", RUNNERS)
def test_runner_report_writer_is_atomic_owner_only_json(runner, tmp_path):
    output = tmp_path / "nested" / "report.json"

    returned = runner.write_private_json_report(output, {"status": "PASS"})

    assert returned == output
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "PASS"}
    assert stat.S_IMODE(output.stat().st_mode) & 0o077 == 0


@pytest.mark.parametrize("runner", RUNNERS)
def test_ac_gate_incomplete_candidate_blocks_paper_and_demo_before_store(runner, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "build_store", lambda *_args, **_kwargs: calls.append("store"))

    with pytest.raises(runner.RunnerConfigurationError, match="research candidate"):
        runner.run_network("paper-live", 1000)
    with pytest.raises(runner.DemoApprovalError, match="research candidate"):
        runner.run_network("demo", 1000)
    assert calls == []


@pytest.mark.parametrize("runner", RUNNERS)
def test_run_network_rejects_non_demo_preflight_before_store(runner, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "build_store", lambda *_args, **_kwargs: calls.append("store"))

    with pytest.raises(runner.RunnerConfigurationError, match="preflight is only valid"):
        runner.run_network("shadow", 1, preflight=True)

    assert calls == []


@pytest.mark.parametrize("runner", RUNNERS)
def test_ac_cfg_005_runner_only_reads_its_own_explicit_env_path(runner, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "OKX_DEMO_API_KEY=fake-okx-key\n"
        "OKX_DEMO_SECRET=fake-okx-secret\n"
        "OKX_DEMO_PASSPHRASE=fake-passphrase\n"
        "BINANCE_DEMO_API_KEY=fake-binance-key\n"
        "BINANCE_DEMO_SECRET=fake-binance-secret\n"
    )

    values = runner._load_demo_credentials(env)

    assert set(values) == {
        "OKX_DEMO_API_KEY",
        "OKX_DEMO_SECRET",
        "OKX_DEMO_PASSPHRASE",
        "BINANCE_DEMO_API_KEY",
        "BINANCE_DEMO_SECRET",
    }
    assert "cross_exchange_arbitrage_support" not in Path(runner.__file__).read_text()
