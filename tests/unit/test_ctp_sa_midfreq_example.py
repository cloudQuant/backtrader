"""Focused acceptance oracles for the Iteration 22 SA SimNow example."""

from __future__ import annotations

import copy
import hashlib
import hmac
import importlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import backtrader as bt
import pytest
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "013_3_sa_midfreq_simnow"
PACKAGE = "iter22_sa_midfreq_example"


def _load_example_package() -> None:
    if PACKAGE in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        EXAMPLE / "__init__.py",
        submodule_search_locations=[str(EXAMPLE)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)


_load_example_package()
features = importlib.import_module(f"{PACKAGE}.features")
reporting = importlib.import_module(f"{PACKAGE}.reporting")
risk = importlib.import_module(f"{PACKAGE}.risk")
runner = importlib.import_module(f"{PACKAGE}.run")
signals = importlib.import_module(f"{PACKAGE}.signal_model")
strategy_module = importlib.import_module(f"{PACKAGE}.strategy")


def _config() -> dict:
    return runner.load_config(EXAMPLE / "config.yaml")[0]


@pytest.fixture(autouse=True)
def _isolate_example_dotenv(monkeypatch):
    """Keep unit results independent of an operator's ignored local credentials/profile."""

    monkeypatch.setattr(runner, "_load_env_file", lambda _path: None)
    monkeypatch.delenv("ITER22_SIMNOW_PROFILE", raising=False)


def _quote(**overrides):
    event = datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc).timestamp()
    value = {
        "schema_version": "ctp.quote.v2",
        "volume_semantics": "delta",
        "event_time_utc": datetime.fromtimestamp(event, timezone.utc).isoformat(),
        "recv_time_utc": datetime.fromtimestamp(event, timezone.utc).isoformat(),
        "recv_monotonic_ns": 100_000_000_000,
        "bid_price": 1500.0,
        "ask_price": 1501.0,
        "bid_volume": 15.0,
        "ask_volume": 5.0,
        "price": 1501.0,
        "cum_volume": 100.0,
        "delta_volume": 1.0,
        "volume": 1.0,
        "open_interest": 5000.0,
        "lower_limit": 1200.0,
        "upper_limit": 2200.0,
        "trading_day": "20260909",
        "action_day": "20260909",
        "connection_generation": 7,
        "ingest_seq": 1,
        "source": "ctp-fixture",
        "volume_complete": True,
        "volume_quality": "continuous",
        "quality_flags": (),
        "event_time_source": "fixture_utc",
        "continuity_status": "continuous",
    }
    value.update(overrides)
    return value


def _query(
    name: str,
    request_id: int,
    records,
    *,
    generation=7,
    account="0123456789abcdef",
):
    return {
        "query_name": name,
        "request_id": request_id,
        "connection_generation": generation,
        "account_fingerprint": account,
        "completed_at_utc": "2026-09-09T01:00:00Z",
        "complete": True,
        "accepted_complete": True,
        "is_last_seen": True,
        "timed_out": False,
        "unsupported": False,
        "error_code": None,
        "error_message": None,
        "records": list(records),
    }


def _instrument(expiry="20260917"):
    return {
        "InstrumentID": "SA701",
        "ExchangeID": "CZCE",
        "ProductID": "SA",
        "IsTrading": 1,
        "ExpireDate": expiry,
        "PriceTick": 1.0,
        "VolumeMultiple": 20,
        "MinLimitOrderVolume": 1,
    }


def _calendar(tmp_path: Path, days) -> tuple[Path, str, dict]:
    payload = {
        "schema_version": "iter22.czce-trading-calendar.v1",
        "exchange": "CZCE",
        "source": "frozen-czce-calendar-v1",
        "as_of_utc": "2026-09-09T00:00:00Z",
        "trading_days": list(days),
    }
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, reporting.sha256_file(path), payload


def _manual_config(tmp_path: Path, *, trading_day="20260910", expiry="20260917") -> dict:
    config = copy.deepcopy(_config())
    days = [
        "20260909",
        "20260910",
        "20260911",
        "20260914",
        "20260915",
        "20260916",
        "20260917",
    ]
    calendar_path, calendar_hash, calendar = _calendar(tmp_path, days)
    remaining = sum(trading_day < item <= expiry for item in days)
    config["instrument"] = "SA701"
    config["contract_selection"].update(
        mode="manual",
        manual_reviewed_at="2026-09-09T08:00:00+08:00",
        manual_source="review-ticket-1",
        manual_trading_days_to_expiry=remaining,
        manual_trading_days_source=calendar["source"],
        manual_trading_days_evidence_sha256=calendar_hash,
    )
    config["trading_calendar"] = {
        "artifact": str(calendar_path),
        "sha256": calendar_hash,
    }
    return config


def _signed_receipt(
    monkeypatch,
    tmp_path: Path,
    config: dict,
    *,
    purpose: str = "engineering_smoke",
    mutate: dict | None = None,
) -> tuple[Path, dict]:
    key_id = "test-operator-key"
    approval_key = "test-approval-key-material-at-least-32-bytes"
    monkeypatch.setenv("ITER22_APPROVAL_KEY_ID", key_id)
    monkeypatch.setenv("ITER22_APPROVAL_HMAC_KEY", approval_key)
    now = datetime.now(timezone.utc)
    receipt = {
        "schema_version": "iter22.simnow-admission.v2",
        "approval_key_id": key_id,
        "candidate_id": config["candidate_id"],
        "config_hash": runner.config_hash(config),
        "code_hash": runner.code_hash(),
        "mode": "simnow",
        "purpose": purpose,
        "environment": config["environment"],
        "issued_at_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_at_utc": (now + timedelta(hours=1)).isoformat(),
        "gates": {"G1": "PASS", "G2": "PASS", "G3": "PASS"},
        "maximum_lots": 1,
        "maximum_write_requests": 10,
        "remaining_smoke_attempts": 1 if purpose == "engineering_smoke" else 0,
        "research_status": config["research"]["status"],
        "instrument": "SA701",
        "account_fingerprint": "acct_0123456789abcdef",
        "trading_day": "20260910",
        "source_hashes": runner.source_file_hashes(),
        "dependency_hashes": runner.dependency_identity_hashes(),
        "native_sha256": "a" * 64,
        "ctp_package_sha256": "b" * 64,
        "reviewer": {"id": "reviewer-1", "approval_sha256": "c" * 64},
        "evidence_hashes": {"G1": "d" * 64, "G2": "e" * 64, "G3": "f" * 64},
        "research_config_sha256": reporting.sha256_json(config["research"]),
        "session_calendar_sha256": config["trading_calendar"]["sha256"],
    }
    if purpose == "engineering_smoke":
        trigger = {
            "trigger_id": "smoke-trigger-1",
            "instrument": "SA701",
            "trading_day": "20260910",
            "side": "long",
            "not_before_utc": (now - timedelta(minutes=5)).isoformat(),
            "not_after_utc": (now + timedelta(minutes=5)).isoformat(),
            "minimum_ingest_seq": 10,
        }
        receipt["engineering_trigger"] = trigger
        receipt["engineering_trigger_sha256"] = reporting.sha256_json(trigger)
    else:
        receipt["signal_preregistration_sha256"] = "9" * 64
    if mutate:
        receipt.update(mutate)
    canonical = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    receipt["signature_hmac_sha256"] = hmac.new(
        approval_key.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    path = tmp_path / f"{purpose}-receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path, receipt


def _snapshot(config: dict, *, trading_day="20260910", stage_b=False, account_records=None):
    account_records = (
        [{"Balance": 100000.0, "Available": 90000.0}]
        if account_records is None
        else account_records
    )
    records = {
        "account": account_records,
        "positions": [],
        "orders": [],
        "trades": [],
        "instruments": [_instrument()],
    }
    if stage_b:
        records.update(
            fees=[
                {
                    "InstrumentID": "SA701",
                    "OpenRatioByMoney": 0.0,
                    "OpenRatioByVolume": 2.0,
                    "CloseRatioByMoney": 0.0,
                    "CloseRatioByVolume": 4.0,
                    "CloseTodayRatioByMoney": 0.0,
                    "CloseTodayRatioByVolume": 4.0,
                }
            ],
            margin=[
                {
                    "InstrumentID": "SA701",
                    "LongMarginRatioByMoney": 0.12,
                    "ShortMarginRatioByMoney": 0.13,
                    "LongMarginRatioByVolume": 0.0,
                    "ShortMarginRatioByVolume": 0.0,
                }
            ],
        )
    queries = {
        name: _query(name, index + (100 if stage_b else 1), value)
        for index, (name, value) in enumerate(records.items())
    }
    return {
        "read_only_safe": True,
        "write_request_free": True,
        "request_count_delta": {
            "settlement_confirm": 0,
            "order_insert": 0,
            "order_action": 0,
        },
        "session": {
            "connected": True,
            "read_only_ready": True,
            "trading_ready": False,
            "ready": False,
            "auto_settlement_confirm": False,
            "environment_profile": "set1_group1",
            "trading_day": trading_day,
            "connection_generation": 7,
            "request_counts": {
                "settlement_confirm": 0,
                "order_insert": 0,
                "order_action": 0,
                "order_cancel": 0,
                "account_change": 0,
            },
        },
        "queries": queries,
    }


def test_default_config_and_front_profiles_are_fail_closed():
    config = _config()
    assert config["mode"] == "shadow"
    assert config["contract_selection"]["mode"] == "auto"
    assert config["trading_calendar"] == {"artifact": None, "sha256": None}
    assert runner.resolve_fronts(config, {}) == {
        "profile": "simnow_first_group1",
        "profile_basis": "simnow_first_group1",
        "sdk_profile": "set1_group1",
        "market_alignment": "actual_market_hours",
        "td_front": "tcp://180.168.146.187:10201",
        "md_front": "tcp://180.168.146.187:10211",
    }
    with pytest.raises(runner.RunnerConfigurationError, match="overridden together"):
        runner.resolve_fronts(config, {"CTP_TD_FRONT": "tcp://180.168.146.187:10201"})
    with pytest.raises(runner.RunnerConfigurationError, match="approved SimNow profile"):
        runner.resolve_fronts(
            config,
            {"CTP_TD_FRONT": "tcp://127.0.0.1:1", "CTP_MD_FRONT": "tcp://127.0.0.1:2"},
        )
    expected_arming_proof_keys = {
        "account_fingerprint",
        "trading_day",
        "instrument",
        "connection_generation",
        "environment_profile",
        "receipt_sha256",
        "native_sha256",
        "ctp_package_sha256",
        "source_hashes_sha256",
        "dependency_hashes_sha256",
        "preflight_sha256",
    }
    assert set(runner.ARMING_PROOF_KEYS) == expected_arming_proof_keys


def test_effective_profile_selection_is_frozen_copied_and_hash_bound():
    config = _config()
    default = runner.effective_profile_config(config, {})
    second = runner.effective_profile_config(
        config, {"ITER22_SIMNOW_PROFILE": "simnow_second_7x24"}
    )
    selected_during_load, _path = runner.load_config(
        EXAMPLE / "config.yaml",
        env_values={"ITER22_SIMNOW_PROFILE": "simnow_second_7x24"},
    )

    assert config["environment"] == "simnow_first_group1"
    assert default["environment"] == "simnow_first_group1"
    assert second["environment"] == "simnow_second_7x24"
    assert selected_during_load["environment"] == "simnow_second_7x24"
    assert runner.config_hash(second) != runner.config_hash(default)
    assert runner.resolve_fronts(second, {}) == {
        "profile": "simnow_second_7x24",
        "profile_basis": "simnow_second_7x24",
        "sdk_profile": "set2_7x24",
        "market_alignment": "engineering_only",
        "td_front": "tcp://180.168.146.187:10130",
        "md_front": "tcp://180.168.146.187:10131",
    }
    with pytest.raises(runner.RunnerConfigurationError, match="exact frozen"):
        runner.effective_profile_config(config, {"ITER22_SIMNOW_PROFILE": "set2_7x24"})
    with pytest.raises(runner.RunnerConfigurationError, match="exact frozen"):
        runner.effective_profile_config(config, {"ITER22_SIMNOW_PROFILE": " simnow_second_7x24"})
    with pytest.raises(runner.RunnerConfigurationError, match="selected SimNow profile"):
        runner.resolve_fronts(
            second,
            {
                "CTP_TD_FRONT": "tcp://180.168.146.187:10201",
                "CTP_MD_FRONT": "tcp://180.168.146.187:10211",
            },
        )


def test_reachable_front_selection_stays_within_the_selected_sdk_family():
    config = _config()
    config["environment"] = "simnow_second_7x24"
    calls = []

    def selector(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            profile="set2_7x24_4000x",
            td_front="tcp://fixture-td",
            md_front="tcp://fixture-md",
        )

    resolved = runner.resolve_fronts(
        config,
        {},
        select_reachable=True,
        reachable_selector=selector,
    )

    assert calls == [
        {
            "env": "set2",
            "profile": "set2_7x24_4000x",
            "require_profile": "set2_7x24_4000x",
        }
    ]
    assert resolved["profile"] == "simnow_second_7x24"
    assert resolved["sdk_profile"] == "set2_7x24_4000x"
    assert resolved["td_front"] == "tcp://fixture-td"
    assert resolved["md_front"] == "tcp://fixture-md"

    with pytest.raises(runner.RunnerConfigurationError, match="required exact profile"):
        runner.resolve_fronts(
            config,
            {},
            select_reachable=True,
            reachable_selector=lambda **_kwargs: SimpleNamespace(
                profile="set2_7x24",
                td_front="tcp://fixture-td",
                md_front="tcp://fixture-md",
            ),
        )


def test_profile_endpoints_are_frozen_and_receipt_cannot_follow_an_override(monkeypatch, tmp_path):
    config = copy.deepcopy(_config())
    config["profiles"]["simnow_first_group1"]["td_front"] = "tcp://127.0.0.1:1"
    with pytest.raises(runner.RunnerConfigurationError, match="frozen MD/TD pairs"):
        runner.validate_config(config)
    admitted_config = _manual_config(tmp_path)
    path, _raw = _signed_receipt(monkeypatch, tmp_path, admitted_config)
    receipt = runner.validate_receipt(
        path,
        config=admitted_config,
        mode="simnow",
        purpose="engineering_smoke",
    )
    with pytest.raises(runner.RunnerConfigurationError, match="receipt environment"):
        runner._validate_receipt_runtime_profile(
            receipt,
            {
                "profile": "simnow_first_group2",
                "account_fingerprint": "acct_0123456789abcdef",
            },
        )


def test_receipt_requires_operator_hmac_and_is_opaque(monkeypatch, tmp_path):
    config = _manual_config(tmp_path)
    path, raw = _signed_receipt(monkeypatch, tmp_path, config)
    receipt = runner.validate_receipt(
        path,
        config=config,
        mode="simnow",
        purpose="engineering_smoke",
    )
    changed = receipt.get("source_hashes")
    changed["run.py"] = "0" * 64
    assert receipt.get("source_hashes")["run.py"] != "0" * 64

    unsigned = dict(raw)
    unsigned.pop("signature_hmac_sha256")
    unsigned_path = tmp_path / "unsigned.json"
    unsigned_path.write_text(json.dumps(unsigned), encoding="utf-8")
    with pytest.raises(runner.RunnerConfigurationError, match="signature"):
        runner.validate_receipt(
            unsigned_path,
            config=config,
            mode="simnow",
            purpose="engineering_smoke",
        )

    invalid = dict(raw, signature_hmac_sha256="0" * 64)
    invalid_path = tmp_path / "invalid-signature.json"
    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(runner.RunnerConfigurationError, match="signature"):
        runner.validate_receipt(
            invalid_path,
            config=config,
            mode="simnow",
            purpose="engineering_smoke",
        )

    monkeypatch.delenv("ITER22_APPROVAL_HMAC_KEY")
    with pytest.raises(runner.RunnerConfigurationError, match="trust root"):
        runner.validate_receipt(
            path,
            config=config,
            mode="simnow",
            purpose="engineering_smoke",
        )


def test_receipt_rejects_critical_runtime_identity_drift(monkeypatch, tmp_path):
    config = _manual_config(tmp_path)
    path, _raw = _signed_receipt(monkeypatch, tmp_path, config)
    identities = runner.runtime_component_identities()
    assert set(identities) == {
        "backtrader",
        "backtrader_trade_logger",
        "backtrader_store",
        "backtrader_feed",
        "backtrader_broker",
        "bt_api_py",
        "bt_api_py_facade",
        "bt_api_py_execution_session",
    }
    assert all(item["found"] and item["path"] and item["sha256"] for item in identities.values())
    drifted = runner.dependency_identity_hashes()
    assert identities["backtrader_trade_logger"]["module"] == "backtrader.observers.trade_logger"
    drifted["backtrader_trade_logger"] = "0" * 64
    monkeypatch.setattr(runner, "dependency_identity_hashes", lambda: drifted)
    with pytest.raises(runner.RunnerConfigurationError, match="dependency hashes"):
        runner.validate_receipt(
            path,
            config=config,
            mode="simnow",
            purpose="engineering_smoke",
        )


def test_final_sa_report_requires_frozen_trade_logger_extension():
    generic = {
        "finalized": True,
        "run_id": "generic-run",
        "extensions": {"sa_midfreq": {"closed_bars": 64, "state": "STOPPED_FLAT"}},
    }
    strategy = SimpleNamespace(
        stats=SimpleNamespace(
            trade_logger=SimpleNamespace(final_report=lambda: copy.deepcopy(generic))
        )
    )
    result = runner._final_sa_report(strategy)
    assert result["closed_bars"] == 64
    assert result["trade_logger"] == generic

    generic["finalized"] = False
    with pytest.raises(RuntimeError, match="not finalized"):
        runner._final_sa_report(strategy)

    generic.update(finalized=True, extensions={})
    with pytest.raises(RuntimeError, match="missing the sa_midfreq extension"):
        runner._final_sa_report(strategy)


@pytest.mark.parametrize("unchecked", [True, False])
def test_run_network_rejects_untrusted_receipt_before_side_effects(
    monkeypatch, tmp_path, unchecked
):
    config = _manual_config(tmp_path)
    path, raw = _signed_receipt(monkeypatch, tmp_path, config)
    if unchecked:
        receipt = raw
    else:
        receipt = runner.AdmissionReceipt(raw, runner._RECEIPT_VALIDATION_MARKER)
    output = tmp_path / f"network-{unchecked}"
    with pytest.raises(runner.RunnerConfigurationError, match="validated receipt|provenance"):
        runner.run_network(
            config,
            mode="simnow",
            purpose="engineering_smoke",
            preflight_only=False,
            prepare_settlement=False,
            receipt=receipt,
            output_directory=output,
            run_seconds=60,
        )
    assert not output.exists()
    assert path.exists()


@pytest.mark.parametrize("purpose", ["engineering_smoke", "natural_signal"])
def test_research_rejected_blocks_every_order_purpose(monkeypatch, tmp_path, purpose):
    config = _manual_config(tmp_path)
    config["research"]["status"] = "RESEARCH_REJECTED"
    path, _raw = _signed_receipt(monkeypatch, tmp_path, config, purpose=purpose)
    with pytest.raises(runner.RunnerConfigurationError, match="research-rejected"):
        runner.validate_receipt(path, config=config, mode="simnow", purpose=purpose)


def test_receipt_binds_the_configured_session_calendar(monkeypatch, tmp_path):
    config = _manual_config(tmp_path)
    path, _raw = _signed_receipt(
        monkeypatch,
        tmp_path,
        config,
        mutate={"session_calendar_sha256": "0" * 64},
    )
    with pytest.raises(runner.RunnerConfigurationError, match="calendar hash"):
        runner.validate_receipt(
            path,
            config=config,
            mode="simnow",
            purpose="engineering_smoke",
        )


def test_receipt_requires_bound_engineering_trigger_or_natural_preregistration(
    monkeypatch, tmp_path
):
    engineering = _manual_config(tmp_path)
    path, _raw = _signed_receipt(
        monkeypatch,
        tmp_path,
        engineering,
        mutate={"engineering_trigger_sha256": "0" * 64},
    )
    with pytest.raises(runner.RunnerConfigurationError, match="trigger hash"):
        runner.validate_receipt(
            path,
            config=engineering,
            mode="simnow",
            purpose="engineering_smoke",
        )

    natural = _manual_config(tmp_path)
    natural["research"]["status"] = "RESEARCH_ADMITTED"
    path, _raw = _signed_receipt(
        monkeypatch,
        tmp_path,
        natural,
        purpose="natural_signal",
        mutate={"signal_preregistration_sha256": None},
    )
    with pytest.raises(runner.RunnerConfigurationError, match="preregistration"):
        runner.validate_receipt(
            path,
            config=natural,
            mode="simnow",
            purpose="natural_signal",
        )


def test_credentials_support_aliases_with_ctp_precedence_and_redaction():
    values = runner.credentials(
        {
            "CTP_USER_ID": "preferred",
            "SIMNOW_USER_ID": "ignored",
            "CTP_PASSWORD": "secret-1",
            "SIMNOW_BROKER_ID": "9999",
            "simnow_app_id": "app",
            "SIMNOW_AUTH_CODE": "auth",
        }
    )
    assert values["investor_id"] == "preferred"
    assert values["broker_id"] == "9999"
    redacted = reporting.redact(values, secret_values=values.values())
    assert "preferred" not in json.dumps(redacted)
    assert "secret-1" not in json.dumps(redacted)


def test_cli_failure_redacts_approval_hmac_secret():
    secret = "approval-hmac-secret-material-at-least-32-bytes"
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE / "run.py"), "--config", secret],
        cwd=REPO,
        env={**os.environ, "ITER22_APPROVAL_HMAC_KEY": secret},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert secret not in completed.stderr
    assert "***" in completed.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["--mode", "replay", "--purpose", "engineering_smoke"],
        ["--mode", "shadow", "--purpose", "natural_signal"],
        ["--mode", "shadow", "--scenario", "trend"],
        ["--mode", "simnow", "--preflight-only", "--run-seconds", "1"],
    ],
)
def test_cli_rejects_meaningless_mode_option_combinations(arguments):
    with pytest.raises(runner.RunnerConfigurationError):
        runner.main(arguments)


def test_api_diagnostic_parser_and_invocation_reject_unsafe_combinations(monkeypatch, tmp_path):
    parser = runner.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--api-diagnostic", "--preflight-only"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--api-diagnostic", "--prepare-settlement"])

    config = _config()
    config["environment"] = "simnow_second_7x24"
    monkeypatch.setattr(runner, "_load_env_file", lambda _path: None)
    monkeypatch.setenv("ITER22_SIMNOW_PROFILE", "simnow_second_7x24")
    with pytest.raises(runner.RunnerConfigurationError, match="shadow observation"):
        runner.run_api_diagnostic(
            config,
            mode="simnow",
            purpose="observation",
            receipt=None,
            output_directory=tmp_path / "simnow-is-forbidden",
            run_seconds=0.0,
        )
    assert not (tmp_path / "simnow-is-forbidden").exists()
    with pytest.raises(runner.RunnerConfigurationError, match="does not consume run duration"):
        runner.run_api_diagnostic(
            config,
            mode="shadow",
            purpose="observation",
            receipt=None,
            output_directory=tmp_path / "duration-is-forbidden",
            run_seconds=1.0,
        )
    assert not (tmp_path / "duration-is-forbidden").exists()

    monkeypatch.setenv("ITER22_SIMNOW_PROFILE", "simnow_first_group1")
    with pytest.raises(runner.RunnerConfigurationError, match="simnow_second_7x24"):
        runner.main(["--api-diagnostic"])


def test_settlement_session_establishment_uses_read_only_verification_before_validation():
    calls = []
    session = {
        "connected": True,
        "read_only_ready": True,
        "trading_ready": False,
        "auto_settlement_confirm": False,
        "environment_profile": "set1_group1_vpn",
        "request_counts": {
            "settlement_confirm": 0,
            "order_insert": 0,
            "order_action": 0,
        },
    }

    class Store:
        def verify_ctp_settlement(self, *, timeout):
            calls.append(("verify", timeout))
            return {"read_only_safe": True, "evidence_complete": False}

        def get_ctp_session_state(self):
            calls.append(("session", None))
            return copy.deepcopy(session)

    result = runner.establish_read_only_ctp_session(
        Store(),
        expected_profile="set1_group1_vpn",
    )

    assert result == {"read_only_safe": True, "evidence_complete": False}
    assert calls == [("verify", 5.0), ("session", None)]


def test_set2_api_diagnostic_is_query_only_and_never_claims_strategy_success(monkeypatch, tmp_path):
    config = _config()
    config["environment"] = "simnow_second_7x24"
    config["evidence"].update(
        minimum_free_bytes=1,
        state_directory=str(tmp_path / "state"),
    )
    snapshot = _snapshot(config)
    snapshot["session"].update(
        environment_profile="set2_7x24",
        account_fingerprint="acct_0123456789abcdef",
    )
    snapshot["snapshot_sha256"] = "a" * 64
    calls = []
    write_calls = []
    snapshot_calls = []
    contract_exchange = str(config["contract_selection"]["exchange"]).upper()

    class DiagnosticStore:
        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")
            return {
                "shutdown_state": "PASS",
                "last_error_code": "",
                "worker_alive": False,
                "close_thread_alive": False,
            }

        def get_ctp_preflight_snapshot(self, **kwargs):
            calls.append(("snapshot", dict(kwargs)))
            return copy.deepcopy(snapshot)

        def get_ctp_session_state(self):
            calls.append("session")
            return copy.deepcopy(snapshot["session"])

        def subscribe(self, *_args, **_kwargs):
            write_calls.append("subscribe")
            raise AssertionError("API diagnostic must not subscribe")

        def verify_ctp_settlement(self, *_args, **_kwargs):
            write_calls.append("settlement_verify")
            raise AssertionError("API diagnostic must not verify settlement")

        def prepare_ctp_settlement(self, *_args, **_kwargs):
            write_calls.append("settlement_prepare")
            raise AssertionError("API diagnostic must not prepare settlement")

        def configure_ctp_execution_authorization(self, *_args, **_kwargs):
            write_calls.append("execution_authorization")
            raise AssertionError("API diagnostic must not arm execution")

    identity = {
        "profile": "simnow_second_7x24",
        "profile_basis": "simnow_second_7x24",
        "sdk_profile": "set2_7x24",
        "market_alignment": "engineering_only",
        "account_fingerprint": "acct_0123456789abcdef",
    }
    store = DiagnosticStore()
    built = {}

    def build_store(config_arg, _env, **kwargs):
        built["config"] = copy.deepcopy(config_arg)
        built["kwargs"] = dict(kwargs)
        return store, identity, []

    monkeypatch.setattr(runner, "_load_env_file", lambda _path: None)
    monkeypatch.setenv("ITER22_SIMNOW_PROFILE", "simnow_second_7x24")
    monkeypatch.setattr(runner, "_build_live_store", build_store)
    monkeypatch.setattr(runner, "runtime_component_identities", dict)
    original_public_snapshot = runner.public_preflight_snapshot

    def observed_public_snapshot(*args, **kwargs):
        snapshot_calls.append((args, dict(kwargs)))
        return original_public_snapshot(*args, **kwargs)

    monkeypatch.setattr(runner, "public_preflight_snapshot", observed_public_snapshot)
    monkeypatch.setattr(
        runner,
        "native_probe",
        lambda: {
            "accepted": True,
            "ctp_package_sha256": "b" * 64,
            "loaded_module_sha256": "c" * 64,
            "native_files": [],
            "native_loaded": True,
        },
    )

    output = tmp_path / "api-diagnostic"
    result = runner.run_api_diagnostic(
        config,
        mode="shadow",
        purpose="observation",
        receipt=None,
        output_directory=output,
        run_seconds=0.0,
        run_id="set2-api-diagnostic",
    )

    assert built["config"]["environment"] == "simnow_second_7x24"
    assert built["kwargs"]["allow_order_writes"] is False
    assert built["kwargs"]["mode"] == "shadow"
    assert snapshot_calls == [
        ((store, None), {"product_id": "SA", "exchange_id": contract_exchange})
    ]
    assert calls == [
        "start",
        ("snapshot", {"product_id": "SA", "exchange_id": contract_exchange}),
        "session",
        "stop",
    ]
    assert write_calls == []
    assert result["status"] == "PASS_API_DIAGNOSTIC"
    assert result["strategy_status"] == "NOT_RUN"
    assert result["g3_gate_status"] == "NOT_RUN_API_DIAGNOSTIC"
    assert result["g4_gate_status"] == "NOT_RUN_API_DIAGNOSTIC"
    assert result["request_counts"] == {
        "settlement_confirm": 0,
        "order_insert": 0,
        "order_action": 0,
        "order_cancel": 0,
        "account_change": 0,
    }

    snapshot_with_write = copy.deepcopy(snapshot)
    snapshot_with_write["request_count_delta"]["order_action"] = 1
    with pytest.raises(runner.PreflightError, match="state-changing request"):
        runner.validate_api_diagnostic_snapshot(snapshot_with_write, identity=identity)

    diagnostic = json.loads((output / "api_diagnostic.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "PASS_API_DIAGNOSTIC"
    assert diagnostic["strategy_status"] == "NOT_RUN"
    assert diagnostic["contract_selection_status"] == "NOT_RUN_API_DIAGNOSTIC_NO_CONTRACT"
    assert diagnostic["reconciliation_status"] == "NOT_RUN_API_DIAGNOSTIC_NO_EXECUTION"
    assert diagnostic["shutdown"]["shutdown_state"] == "PASS"
    assert diagnostic["query_evidence"]["account"]["record_count"] == 1
    assert diagnostic["session"]["request_count_delta"] == {
        "settlement_confirm": 0,
        "order_insert": 0,
        "order_action": 0,
    }
    serialized_diagnostic = json.dumps(diagnostic, sort_keys=True)
    assert '"records":' not in serialized_diagnostic
    assert "100000" not in serialized_diagnostic
    assert json.loads((output / "preflight.json").read_text(encoding="utf-8"))["status"] == (
        "PASS_API_DIAGNOSTIC"
    )
    assert json.loads((output / "contract_selection.json").read_text(encoding="utf-8"))[
        "status"
    ] == ("NOT_RUN_API_DIAGNOSTIC_NO_CONTRACT")
    assert json.loads((output / "reconciliation.json").read_text(encoding="utf-8"))["status"] == (
        "NOT_RUN_API_DIAGNOSTIC_NO_EXECUTION"
    )
    assert json.loads((output / "daily_report.json").read_text(encoding="utf-8"))[
        "strategy_status"
    ] == ("NOT_RUN")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["environment"] == "simnow_second_7x24"
    assert manifest["environment_profile"] == "set2_7x24"
    assert manifest["strategy_status"] == "NOT_RUN"
    assert manifest["exit_status"] == "PASS_API_DIAGNOSTIC"


def test_set2_api_diagnostic_stops_store_when_start_raises(monkeypatch, tmp_path):
    config = _config()
    config["environment"] = "simnow_second_7x24"
    config["evidence"].update(
        minimum_free_bytes=1,
        state_directory=str(tmp_path / "state"),
    )
    calls = []

    class FailingStartStore:
        def start(self):
            calls.append("start")
            raise RuntimeError("simulated start failure")

        def stop(self):
            calls.append("stop")

    identity = {
        "profile": "simnow_second_7x24",
        "profile_basis": "simnow_second_7x24",
        "sdk_profile": "set2_7x24",
        "market_alignment": "engineering_only",
        "account_fingerprint": "acct_0123456789abcdef",
    }
    monkeypatch.setattr(runner, "_load_env_file", lambda _path: None)
    monkeypatch.setenv("ITER22_SIMNOW_PROFILE", "simnow_second_7x24")
    monkeypatch.setattr(
        runner,
        "_build_live_store",
        lambda *_args, **_kwargs: (FailingStartStore(), identity, []),
    )
    monkeypatch.setattr(runner, "runtime_component_identities", dict)
    monkeypatch.setattr(
        runner,
        "native_probe",
        lambda: {
            "accepted": True,
            "ctp_package_sha256": "b" * 64,
            "loaded_module_sha256": "c" * 64,
            "native_files": [],
            "native_loaded": True,
        },
    )

    output = tmp_path / "api-diagnostic-start-failure"
    with pytest.raises(RuntimeError, match="simulated start failure"):
        runner.run_api_diagnostic(
            config,
            mode="shadow",
            purpose="observation",
            receipt=None,
            output_directory=output,
            run_seconds=0.0,
            run_id="set2-api-start-failure",
        )

    assert calls == ["start", "stop"]
    assert json.loads((output / "api_diagnostic.json").read_text(encoding="utf-8"))["status"] == (
        "FAIL_CLOSED"
    )
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["exit_status"] == (
        "FAIL_CLOSED"
    )


def test_api_diagnostic_writes_safe_evidence_when_live_store_construction_fails(
    monkeypatch, tmp_path
):
    config = _config()
    config["environment"] = "simnow_second_7x24"
    config["evidence"].update(
        minimum_free_bytes=1,
        state_directory=str(tmp_path / "state"),
    )
    secret = "construction-secret-not-for-evidence"
    raw_front = "tcp://198.51.100.77:4567"

    def fail_build(*_args, **_kwargs):
        raise RuntimeError(f"selector failed at {raw_front} with {secret}")

    monkeypatch.setattr(runner, "_load_env_file", lambda _path: None)
    monkeypatch.setenv("ITER22_SIMNOW_PROFILE", "simnow_second_7x24")
    monkeypatch.setattr(runner, "_build_live_store", fail_build)

    output = tmp_path / "api-diagnostic-construction-failure"
    with pytest.raises(RuntimeError, match="selector failed"):
        runner.run_api_diagnostic(
            config,
            mode="shadow",
            purpose="observation",
            receipt=None,
            output_directory=output,
            run_seconds=0.0,
            run_id="set2-api-construction-failure",
        )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    diagnostic = json.loads((output / "api_diagnostic.json").read_text(encoding="utf-8"))
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(output.glob("*.json"))
    )
    assert manifest["exit_status"] == "FAIL_CLOSED"
    assert manifest["failure_stage"] == "live_store_construction"
    assert manifest["failure_code"] == "RuntimeError"
    assert manifest["account_fingerprint"] is None
    assert diagnostic == {
        "error_code": "RuntimeError",
        "failure_stage": "live_store_construction",
        "g3_gate_status": "NOT_RUN_API_DIAGNOSTIC",
        "g4_gate_status": "NOT_RUN_API_DIAGNOSTIC",
        "message": "live_store_construction_failed",
        "schema_version": "iter22.ctp-api-diagnostic.v1",
        "status": "FAIL_CLOSED",
        "strategy_status": "NOT_RUN",
    }
    assert secret not in serialized
    assert raw_front not in serialized


def test_set2_api_diagnostic_rejects_incomplete_shutdown_before_writing_pass(monkeypatch, tmp_path):
    config = _config()
    config["environment"] = "simnow_second_7x24"
    config["evidence"].update(
        minimum_free_bytes=1,
        state_directory=str(tmp_path / "state"),
    )
    snapshot = _snapshot(config)
    snapshot["session"].update(
        environment_profile="set2_7x24",
        account_fingerprint="acct_0123456789abcdef",
    )
    snapshot["snapshot_sha256"] = "a" * 64
    calls = []

    class IncompleteStopStore:
        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")
            return {
                "shutdown_state": "INCOMPLETE",
                "last_error_code": "",
                "worker_alive": True,
                "close_thread_alive": False,
            }

        def get_ctp_preflight_snapshot(self, **kwargs):
            calls.append(("snapshot", kwargs))
            return copy.deepcopy(snapshot)

        def get_ctp_session_state(self):
            calls.append("session")
            return copy.deepcopy(snapshot["session"])

    identity = {
        "profile": "simnow_second_7x24",
        "profile_basis": "simnow_second_7x24",
        "sdk_profile": "set2_7x24",
        "market_alignment": "engineering_only",
        "account_fingerprint": "acct_0123456789abcdef",
    }
    monkeypatch.setattr(runner, "_load_env_file", lambda _path: None)
    monkeypatch.setenv("ITER22_SIMNOW_PROFILE", "simnow_second_7x24")
    monkeypatch.setattr(
        runner,
        "_build_live_store",
        lambda *_args, **_kwargs: (IncompleteStopStore(), identity, []),
    )
    monkeypatch.setattr(runner, "runtime_component_identities", dict)
    monkeypatch.setattr(
        runner,
        "native_probe",
        lambda: {
            "accepted": True,
            "ctp_package_sha256": "b" * 64,
            "loaded_module_sha256": "c" * 64,
            "native_files": [],
            "native_loaded": True,
        },
    )

    output = tmp_path / "api-diagnostic-incomplete-shutdown"
    with pytest.raises(runner.PreflightError, match="shutdown is not PASS"):
        runner.run_api_diagnostic(
            config,
            mode="shadow",
            purpose="observation",
            receipt=None,
            output_directory=output,
            run_seconds=0.0,
            run_id="set2-api-incomplete-shutdown",
        )

    assert calls == [
        "start",
        (
            "snapshot",
            {
                "product_id": "SA",
                "exchange_id": str(config["contract_selection"]["exchange"]).upper(),
            },
        ),
        "session",
        "stop",
    ]
    diagnostic = json.loads((output / "api_diagnostic.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert diagnostic["status"] == "FAIL_CLOSED"
    assert manifest["api_diagnostic_status"] == "FAIL_CLOSED_API_DIAGNOSTIC"
    assert manifest["exit_status"] == "FAIL_CLOSED"


@pytest.mark.parametrize(
    ("state", "completed", "monitor_exit", "expected_exit_code"),
    [
        ("STOPPED_FLAT", True, "flat_completed", 0),
        ("STOPPED_FLAT", False, "flat_completed", runner.RECOVERY_INCOMPLETE_EXIT_CODE),
        ("MANUAL_INTERVENTION", False, None, runner.RECOVERY_INCOMPLETE_EXIT_CODE),
        (
            "MANUAL_INTERVENTION",
            False,
            "forced_termination",
            runner.RECOVERY_INCOMPLETE_EXIT_CODE,
        ),
        (
            "MANUAL_INTERVENTION",
            False,
            "operator_takeover",
            runner.RECOVERY_INCOMPLETE_EXIT_CODE,
        ),
    ],
)
def test_cli_recovery_exit_code_requires_sdk_completed_stopped_flat(
    monkeypatch, tmp_path, state, completed, monitor_exit, expected_exit_code
):
    report = {
        "state": state,
        "purpose": "execution_recovery",
        "execution_recovery": {
            "recovery_only": True,
            "completed": completed,
            "monitor_exit": monitor_exit,
        },
    }
    monkeypatch.setattr(
        runner, "load_config", lambda _path, **_kwargs: ({}, tmp_path / "config.yaml")
    )
    monkeypatch.setattr(runner, "_load_env_file", lambda _path: None)
    monkeypatch.setattr(runner, "effective_profile_config", lambda config, _env: config)
    monkeypatch.setattr(runner, "validate_receipt", lambda *_args, **_kwargs: {"valid": True})
    monkeypatch.setattr(runner, "_run_id", lambda _mode: "cli-recovery")
    monkeypatch.setattr(
        runner,
        "_evidence_directory",
        lambda _config, _run_id_value, _output_dir: tmp_path,
    )
    monkeypatch.setattr(runner, "run_network", lambda *_args, **_kwargs: report)

    exit_code = runner.main(
        [
            "--config",
            str(tmp_path / "config.yaml"),
            "--mode",
            "simnow",
            "--purpose",
            "engineering_smoke",
            "--admission-receipt",
            str(tmp_path / "receipt.json"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == expected_exit_code


def test_quote_normalization_uses_separate_wall_and_monotonic_clocks():
    raw = _quote()
    event_epoch = datetime.fromisoformat(raw["event_time_utc"]).timestamp()
    result = features.normalize_quote(
        raw,
        tick_size=1.0,
        now_wall_utc=event_epoch + 1.0,
        now_monotonic=101.0,
    )
    assert result.valid
    assert result.quote.event_time == event_epoch
    assert result.quote.recv_monotonic == 100.0
    stale_receive = features.normalize_quote(
        raw,
        tick_size=1.0,
        now_wall_utc=event_epoch + 1.0,
        now_monotonic=103.0,
    )
    assert stale_receive.reason == "stale_receive_time"
    stale_event = features.normalize_quote(
        raw,
        tick_size=1.0,
        now_wall_utc=event_epoch + 3.0,
        now_monotonic=101.0,
    )
    assert stale_event.reason == "stale_event_time"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"volume_semantics": ""}, "volume_semantics_not_delta"),
        ({"lower_limit": None}, "invalid_lower_limit"),
        ({"upper_limit": 1500.5}, "daily_price_limits_off_tick_grid"),
        ({"volume_complete": False}, "ctp_volume_incomplete"),
        ({"schema_version": "ctp.quote.v1"}, "unsupported_or_missing_quote_schema"),
    ],
)
def test_ctp_v2_missing_or_invented_fields_are_rejected(changes, reason):
    result = features.normalize_quote(_quote(**changes), tick_size=1.0)
    assert not result.valid
    assert result.reason == reason


@pytest.mark.parametrize(
    "field",
    [
        "event_time_utc",
        "recv_time_utc",
        "recv_monotonic_ns",
        "cum_volume",
        "delta_volume",
        "volume",
        "open_interest",
        "volume_complete",
        "volume_quality",
        "quality_flags",
        "event_time_source",
        "continuity_status",
        "trading_day",
        "action_day",
        "connection_generation",
        "ingest_seq",
        "source",
    ],
)
def test_ctp_v2_required_contract_fields_cannot_be_defaulted(field):
    raw = _quote()
    raw.pop(field)
    result = features.normalize_quote(raw, tick_size=1.0)
    assert not result.valid
    assert result.reason.startswith("ctp_required_field_missing:")


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"continuity_status": "gap"}, "ctp_continuity_not_continuous:gap"),
        ({"volume_quality": "estimated"}, "ctp_volume_quality_not_continuous:estimated"),
    ],
)
def test_ctp_v2_requires_contiguous_source_volume(changes, reason):
    result = features.normalize_quote(_quote(**changes), tick_size=1.0)
    assert not result.valid
    assert result.reason == reason


def test_quote_window_never_reuses_ingest_sequence_after_clear():
    window = features.QuoteFeatureWindow(1.0)
    first = features.normalize_quote(_quote(ingest_seq=7), tick_size=1.0).quote
    assert first is not None and window.add(first)
    window.clear()
    reused = features.normalize_quote(_quote(ingest_seq=7), tick_size=1.0).quote
    assert reused is not None and not window.add(reused)
    assert window.last_invalid_reason == "nonincreasing_global_ingest_seq"


def test_ctp_v2_volume_aliases_must_agree():
    result = features.normalize_quote(_quote(volume=2.0), tick_size=1.0)
    assert not result.valid
    assert result.reason == "delta_volume_alias_mismatch"

    result = features.normalize_quote(
        _quote(cumulative_volume=99.0),
        tick_size=1.0,
    )
    assert not result.valid
    assert result.reason == "cumulative_volume_alias_mismatch"


def test_fast_feature_formulas_match_hand_calculation():
    window = features.QuoteFeatureWindow(1.0)
    for index in range(61):
        quote = features.QuoteSnapshot(
            event_time=float(index),
            recv_monotonic=100.0 + index,
            ingest_seq=index + 1,
            bid=100.0,
            ask=101.0,
            bid_size=9.0,
            ask_size=1.0,
            last=101.0,
            cum_volume=1000.0 + index,
            delta_volume=1.0,
            open_interest=5000.0,
            lower_limit=80.0,
            upper_limit=120.0,
            trading_day="20260909",
            action_day="20260909",
            connection_generation=1,
            source="oracle",
        )
        assert window.add(quote)
    result = window.calculate()
    assert result.ready
    assert result.imbalance_5s == pytest.approx(0.8)
    assert result.microprice == pytest.approx(100.9)
    assert result.micro_dev == pytest.approx(0.4)
    assert result.ofi_5s == pytest.approx(0.0)
    assert result.momentum_15s == pytest.approx(0.0)
    assert result.sigma_60s_price == pytest.approx(0.0)
    assert result.valid_changes_60s == 60
    swapped = features.QuoteFeatureWindow(1.0)
    for index in range(61):
        swapped.add(
            features.QuoteSnapshot(
                event_time=float(index),
                recv_monotonic=100.0 + index,
                ingest_seq=index + 1,
                bid=100.0,
                ask=101.0,
                bid_size=1.0,
                ask_size=9.0,
                last=100.0,
                cum_volume=1000.0 + index,
                delta_volume=1.0,
                open_interest=5000.0,
                lower_limit=80.0,
                upper_limit=120.0,
                trading_day="20260909",
                action_day="20260909",
                connection_generation=1,
                source="oracle",
            )
        )
    swapped_result = swapped.calculate()
    assert swapped_result.imbalance_5s == pytest.approx(-0.8)
    assert swapped_result.microprice == pytest.approx(100.1)
    assert swapped_result.micro_dev == pytest.approx(-0.4)


def test_minute_features_and_cost_gate_use_exact_oracles():
    closes = [(1000.0 + 60.0 * index, 100.0 + index) for index in range(6)]
    minute = signals.minute_features(
        closes=closes,
        current_volume=20.0,
        previous_volumes=[("20260909", 10.0)] * 20,
        trading_day="20260909",
        ema5=105.0,
        ema20=100.0,
        atr14=10.0,
        tick_size=1.0,
        bar_id="b1",
        bar_end=1300.0,
        available_at=1300.5,
    )
    assert minute.ready
    assert minute.trend == pytest.approx(0.5)
    assert minute.return1 == pytest.approx(0.1)
    assert minute.return3 == pytest.approx(0.3)
    assert minute.return5 == pytest.approx(0.5)
    assert minute.volume_ratio == pytest.approx(2.0)
    costs = signals.CostInputs(
        tick_size=1.0,
        multiplier=20.0,
        lots=1,
        entry_price=1501.0,
        exit_price=1500.0,
        open_money_rate=0.0,
        open_volume_rate=2.0,
        close_money_rate=0.0,
        close_volume_rate=4.0,
        entry_slip_ticks=1.0,
        exit_slip_ticks=1.0,
        edge_buffer_ticks=1.0,
        verified=True,
        source="account-query",
    )
    boundary = signals.roundtrip_cost(1.0, costs, move_proxy_ticks=4.3)
    assert boundary.roundtrip_cost_ticks == pytest.approx(3.3)
    assert boundary.required_ticks == pytest.approx(4.3)
    assert not boundary.admitted
    admitted = signals.roundtrip_cost(1.0, costs, move_proxy_ticks=4.31)
    assert admitted.admitted


def test_confirmation_resets_on_bar_direction_and_invalidity():
    tracker = signals.ConfirmationTracker(seconds=2.0, quotes=3)
    assert not tracker.observe(direction=1, bar_id="b1", quote_time=1.0, eligible=True)
    assert not tracker.observe(direction=1, bar_id="b1", quote_time=2.0, eligible=True)
    assert tracker.observe(direction=1, bar_id="b1", quote_time=3.0, eligible=True)
    assert not tracker.observe(direction=-1, bar_id="b1", quote_time=4.0, eligible=True)
    assert tracker.count == 1
    assert not tracker.observe(direction=-1, bar_id="b2", quote_time=5.0, eligible=True)
    assert tracker.count == 1
    assert not tracker.observe(direction=-1, bar_id="b2", quote_time=6.0, eligible=False)
    assert tracker.count == 0


def test_contract_auto_fails_without_authoritative_calendar():
    policy = _config()["contract_selection"]
    with pytest.raises(runner.PreflightError, match="BLOCKED_CTP_TRADING_CALENDAR"):
        runner.select_contract([_instrument()], policy, today=date(2026, 9, 9))


def test_calendar_reader_fails_closed_for_hash_matched_invalid_json(tmp_path):
    """A present, hash-matched artifact still needs a valid calendar document."""

    artifact = tmp_path / "invalid-calendar.json"
    artifact.write_text("{invalid calendar json", encoding="utf-8")
    config = _config()
    config["trading_calendar"] = {
        "artifact": str(artifact),
        "sha256": reporting.sha256_file(artifact),
    }

    with pytest.raises(runner.PreflightError, match="BLOCKED_CTP_TRADING_CALENDAR"):
        runner._load_trading_calendar(config)


def test_contract_auto_uses_complete_previous_trading_day_oi_and_volume():
    policy = _config()["contract_selection"]
    first = {
        **_instrument("20261015"),
        "InstrumentID": "SA701",
        "trading_days_to_expiry": 20,
        "ranking_evidence_complete": True,
        "ranking_trading_day": "20260908",
        "expected_prior_trading_day": "20260908",
        "OpenInterest": 1000,
        "Volume": 500,
    }
    second = {
        **first,
        "InstrumentID": "SA705",
        "OpenInterest": 1200,
        "Volume": 300,
    }
    selected = runner.select_contract([first, second], policy, today=date(2026, 9, 9))
    assert selected["instrument"] == "SA705"
    assert selected["ranking_trading_day"] == "20260908"

    current_day = copy.deepcopy(first)
    current_day["ranking_trading_day"] = "20260909"
    with pytest.raises(runner.PreflightError, match="prior complete TradingDay"):
        runner.select_contract([current_day], policy, today=date(2026, 9, 9))

    missing_volume = copy.deepcopy(first)
    missing_volume.pop("Volume")
    with pytest.raises(runner.PreflightError, match="volume is incomplete"):
        runner.select_contract([missing_volume], policy, today=date(2026, 9, 9))


def test_contract_auto_uses_complete_previous_trading_day_ranking_only():
    policy = _config()["contract_selection"]
    base = {
        **_instrument(expiry="20261020"),
        "trading_days_to_expiry": 20,
        "ranking_evidence_complete": True,
        "ranking_trading_day": "20260908",
        "expected_prior_trading_day": "20260908",
        "Volume": 100,
    }
    winner = {**base, "InstrumentID": "SA701", "OpenInterest": 200}
    runner_up = {**base, "InstrumentID": "SA705", "OpenInterest": 100}
    selected = runner.select_contract([runner_up, winner], policy, today=date(2026, 9, 9))
    assert selected["instrument"] == "SA701"
    assert selected["ranking_trading_day"] == "20260908"

    with pytest.raises(runner.PreflightError, match="prior complete TradingDay"):
        runner.select_contract(
            [{**winner, "ranking_trading_day": "20260909"}],
            policy,
            today=date(2026, 9, 9),
        )
    incomplete = dict(winner)
    incomplete.pop("Volume")
    with pytest.raises(runner.PreflightError, match="volume is incomplete"):
        runner.select_contract([incomplete], policy, today=date(2026, 9, 9))


def test_manual_contract_uses_session_trading_day_at_night(tmp_path):
    config = _manual_config(tmp_path, trading_day="20260910")
    stage_a = runner.validate_stage_a(
        _snapshot(config, trading_day="20260910"),
        config,
        receipt=None,
        expected_account="acct_0123456789abcdef",
        expected_profile="set1_group1",
    )
    selection = stage_a["selection"]
    assert selection["instrument"] == "SA701"
    # From session TradingDay 09-10 the remaining dates are 11,14,15,16,17.
    assert selection["remaining_trading_days"] == 5
    assert selection["validated_metadata"] == {
        "price_tick": 1.0,
        "volume_multiple": 20.0,
        "minimum_order_lots": 1,
    }


def test_manual_contract_evidence_hash_and_raw_ctp_fields_are_mandatory(tmp_path):
    config = _manual_config(tmp_path)
    config["contract_selection"]["manual_trading_days_evidence_sha256"] = "0" * 64
    with pytest.raises(runner.PreflightError, match="does not match"):
        runner.validate_stage_a(
            _snapshot(config),
            config,
            receipt=None,
            expected_account="acct_0123456789abcdef",
            expected_profile="set1_group1",
        )
    config = _manual_config(tmp_path)
    broken = _snapshot(config)
    broken["queries"]["instruments"]["records"][0].pop("PriceTick")
    with pytest.raises(runner.PreflightError, match="PriceTick/VolumeMultiple"):
        runner.validate_stage_a(
            broken,
            config,
            receipt=None,
            expected_account="acct_0123456789abcdef",
            expected_profile="set1_group1",
        )


def test_two_stage_preflight_rejects_empty_or_multiple_account(tmp_path):
    config = _manual_config(tmp_path)
    stage_a = runner.validate_stage_a(
        _snapshot(config),
        config,
        receipt=None,
        expected_account="acct_0123456789abcdef",
        expected_profile="set1_group1",
    )
    for account_records in ([], [{"Balance": 1}, {"Balance": 2}]):
        with pytest.raises(runner.PreflightError, match="exactly one"):
            runner.validate_preflight(
                _snapshot(config, stage_b=True, account_records=account_records),
                config,
                mode="shadow",
                stage_a=stage_a,
                expected_account="acct_0123456789abcdef",
                expected_profile="set1_group1",
            )
    passed = runner.validate_preflight(
        _snapshot(config, stage_b=True),
        config,
        mode="shadow",
        stage_a=stage_a,
        expected_account="acct_0123456789abcdef",
        expected_profile="set1_group1",
    )
    assert passed["ready_for_shadow"] is True
    assert passed["fee"]["source"] == "ctp_account_commission_query"


def test_preflight_rejects_reused_ids_and_incomplete_ctp_account_records(tmp_path):
    config = _manual_config(tmp_path)
    stage_a = runner.validate_stage_a(
        _snapshot(config),
        config,
        receipt=None,
        expected_account="acct_0123456789abcdef",
        expected_profile="set1_group1",
    )

    reused = _snapshot(config, stage_b=True)
    reused["queries"]["account"]["request_id"] = 1
    with pytest.raises(runner.PreflightError, match="globally distinct"):
        runner.validate_preflight(
            reused,
            config,
            mode="shadow",
            stage_a=stage_a,
            expected_account="acct_0123456789abcdef",
            expected_profile="set1_group1",
        )

    incomplete_fee = _snapshot(config, stage_b=True)
    incomplete_fee["queries"]["fees"]["records"][0].pop("CloseTodayRatioByVolume")
    with pytest.raises(runner.PreflightError, match="fee record fields are incomplete"):
        runner.validate_preflight(
            incomplete_fee,
            config,
            mode="shadow",
            stage_a=stage_a,
            expected_account="acct_0123456789abcdef",
            expected_profile="set1_group1",
        )

    wrong_margin = _snapshot(config, stage_b=True)
    wrong_margin["queries"]["margin"]["records"][0]["InstrumentID"] = "SA705"
    with pytest.raises(runner.PreflightError, match="margin record is not bound"):
        runner.validate_preflight(
            wrong_margin,
            config,
            mode="shadow",
            stage_a=stage_a,
            expected_account="acct_0123456789abcdef",
            expected_profile="set1_group1",
        )

    invalid_position = _snapshot(config, stage_b=True)
    invalid_position["queries"]["positions"]["records"] = [
        {
            "InstrumentID": "SA701",
            "ExchangeID": "CZCE",
            "PosiDirection": "2",
            "HedgeFlag": "1",
            "Position": 1,
            "TodayPosition": 1,
            "YdPosition": 0,
            "LongFrozen": 2,
            "ShortFrozen": 0,
        }
    ]
    with pytest.raises(runner.PreflightError, match="frozen quantity exceeds"):
        runner.validate_preflight(
            invalid_position,
            config,
            mode="shadow",
            stage_a=stage_a,
            expected_account="acct_0123456789abcdef",
            expected_profile="set1_group1",
        )


def test_live_store_uses_one_managed_btapi_session_and_common_journal(tmp_path):
    class FakeStore:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    env = {
        "CTP_USER_ID": "investor",
        "CTP_PASSWORD": "password",
        "CTP_BROKER_ID": "9999",
        "CTP_APP_ID": "app",
        "CTP_AUTH_CODE": "auth",
        "ITER22_APPROVAL_KEY_ID": "operator-key-1",
        "ITER22_APPROVAL_HMAC_KEY": "hmac-secret-material-at-least-32-bytes",
    }
    first, identity, secrets = runner._build_live_store(
        _config(),
        env,
        mode="simnow",
        purpose="engineering_smoke",
        state_directory=tmp_path,
        allow_order_writes=True,
        store_cls=FakeStore,
        reachable_selector=lambda **_kwargs: SimpleNamespace(
            profile="set1_group1_vpn",
            td_front="tcp://fixture-td",
            md_front="tcp://fixture-md",
        ),
    )
    second, _identity, _secrets = runner._build_live_store(
        _config(),
        env,
        mode="simnow",
        purpose="natural_signal",
        state_directory=tmp_path,
        allow_order_writes=False,
        store_cls=FakeStore,
        reachable_selector=lambda **_kwargs: SimpleNamespace(
            profile="set1_group1_vpn",
            td_front="tcp://fixture-td",
            md_front="tcp://fixture-md",
        ),
    )
    assert first.kwargs["provider"] == "btapi"
    assert first.kwargs["backend"] == "direct"
    first_config = first.kwargs["config"]
    second_config = second.kwargs["config"]
    assert first_config["execution_config"]["market_data_only"] is True
    assert second_config["execution_config"]["market_data_only"] is True
    assert (
        first_config["execution_config"]["order_journal"]
        == second_config["execution_config"]["order_journal"]
    )
    assert first_config["exchange_kwargs"][runner.CTP_EXCHANGE]["auto_settlement_confirm"] is False
    assert "execution_authorization_key_id" not in first_config
    assert "execution_authorization_secret" not in first_config
    assert first.kwargs["execution_authorization_key_id"] == env["ITER22_APPROVAL_KEY_ID"]
    assert first.kwargs["execution_authorization_secret"] == env["ITER22_APPROVAL_HMAC_KEY"]
    assert identity["account_fingerprint"].startswith("acct_")
    assert env["ITER22_APPROVAL_HMAC_KEY"] in secrets


def test_shadow_full_network_run_holds_account_lock_before_store_start(monkeypatch, tmp_path):
    config = _manual_config(tmp_path)
    events = []

    class ObservedLock:
        def __init__(self, path):
            self.path = Path(path)

        def __enter__(self):
            events.append(("lock_enter", self.path.name))
            return self

        def __exit__(self, *_args):
            events.append(("lock_exit", self.path.name))

    class FailingStore:
        def start(self):
            assert events == [("lock_enter", "writer.lock")]
            events.append(("store_start", None))
            raise RuntimeError("stop-after-lock-proof")

    identity = {
        "profile": config["environment"],
        "profile_basis": config["environment"],
        "sdk_profile": "set1_group1",
        "market_alignment": "actual_market_hours",
        "account_fingerprint": "acct_0123456789abcdef",
    }
    monkeypatch.setattr(runner, "AccountLock", ObservedLock)
    monkeypatch.setattr(
        runner,
        "_build_live_store",
        lambda *_args, **_kwargs: (FailingStore(), identity, []),
    )
    monkeypatch.setattr(
        runner,
        "native_probe",
        lambda: {
            "accepted": True,
            "bt_api_ctp_version": "test",
            "bt_api_ctp_path": "/test",
            "bt_api_ctp_sha256": "a" * 64,
            "native_files": [],
            "native_loaded": True,
        },
    )
    monkeypatch.setattr(runner, "runtime_component_identities", dict)
    with pytest.raises(RuntimeError, match="stop-after-lock-proof"):
        runner.run_network(
            config,
            mode="shadow",
            purpose="observation",
            preflight_only=False,
            prepare_settlement=False,
            receipt=None,
            output_directory=tmp_path / "shadow-lock-proof",
            run_seconds=1.0,
        )
    assert events == [
        ("lock_enter", "writer.lock"),
        ("store_start", None),
        ("lock_exit", "writer.lock"),
    ]


def test_run_network_records_calendar_gate_in_failure_evidence(monkeypatch, tmp_path):
    """A missing authoritative calendar is a G3 block, not a generic failure."""

    config = _config()
    config["evidence"].update(
        minimum_free_bytes=1,
        state_directory=str(tmp_path / "state"),
    )
    calls = []
    write_calls = []

    class CalendarGateStore:
        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

        def verify_ctp_settlement(self, *, timeout):
            calls.append(("settlement", timeout))
            return {"evidence_complete": True, "read_only_safe": True}

        def subscribe(self, *_args, **_kwargs):
            write_calls.append("subscribe")
            raise AssertionError("calendar-blocked preflight must not subscribe")

        def prepare_ctp_settlement(self, *_args, **_kwargs):
            write_calls.append("settlement_prepare")
            raise AssertionError("calendar-blocked preflight must not prepare settlement")

        def configure_ctp_execution_authorization(self, *_args, **_kwargs):
            write_calls.append("execution_authorization")
            raise AssertionError("calendar-blocked preflight must not arm execution")

    identity = {
        "profile": "simnow_first_group1",
        "profile_basis": "simnow_first_group1",
        "sdk_profile": "set1_group1",
        "market_alignment": "actual_market_hours",
        "account_fingerprint": "acct_0123456789abcdef",
    }
    store = CalendarGateStore()
    monkeypatch.setattr(
        runner,
        "_build_live_store",
        lambda *_args, **_kwargs: (store, identity, []),
    )
    monkeypatch.setattr(
        runner,
        "native_probe",
        lambda: {
            "accepted": True,
            "bt_api_ctp_version": "test",
            "bt_api_ctp_path": "/test",
            "ctp_package_sha256": "a" * 64,
            "native_files": [],
            "native_loaded": True,
        },
    )
    monkeypatch.setattr(runner, "runtime_component_identities", dict)

    def stage_a_snapshot(*_args, **kwargs):
        calls.append(("stage_a_snapshot", dict(kwargs)))
        return {"stage": "a"}

    def calendar_block(*_args, **_kwargs):
        calls.append("validate_stage_a")
        raise runner.PreflightError(
            "BLOCKED_CTP_TRADING_CALENDAR: remaining trading days are unproven"
        )

    monkeypatch.setattr(runner, "public_preflight_snapshot", stage_a_snapshot)
    monkeypatch.setattr(runner, "validate_stage_a", calendar_block)

    output = tmp_path / "calendar-gate-failure"
    with pytest.raises(runner.PreflightError, match="BLOCKED_CTP_TRADING_CALENDAR"):
        runner.run_network(
            config,
            mode="simnow",
            purpose="observation",
            preflight_only=True,
            prepare_settlement=False,
            receipt=None,
            output_directory=output,
            run_seconds=0.0,
        )

    assert calls == [
        "start",
        ("settlement", 5.0),
        ("stage_a_snapshot", {"product_id": "SA", "exchange_id": "CZCE"}),
        "validate_stage_a",
        "stop",
    ]
    assert write_calls == []
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    reconciliation = json.loads((output / "reconciliation.json").read_text(encoding="utf-8"))
    daily_report = json.loads((output / "daily_report.json").read_text(encoding="utf-8"))
    for payload in (manifest, failure, reconciliation, daily_report):
        assert payload["g3_gate_status"] == "BLOCKED_CTP_TRADING_CALENDAR"
        assert payload["g4_gate_status"] == "BLOCKED_G3"
    assert manifest["exit_status"] == "FAIL_CLOSED"
    assert failure["status"] == "FAIL_CLOSED"


@pytest.mark.parametrize("monitor_exit", ["flat_completed", "forced_termination"])
def test_startup_recovery_monitor_holds_store_and_account_lock_until_terminal_evidence(
    monkeypatch, tmp_path, monitor_exit
):
    config = _manual_config(tmp_path)
    config["evidence"]["state_directory"] = str(tmp_path / "state")
    config["evidence"]["minimum_free_bytes"] = 1
    receipt_path, _raw = _signed_receipt(monkeypatch, tmp_path, config)
    receipt = runner.validate_receipt(
        receipt_path,
        config=config,
        mode="simnow",
        purpose="engineering_smoke",
    )
    events = []
    state = {"lock_held": False, "store_started": False}

    class ObservedLock:
        def __init__(self, path):
            self.path = Path(path)

        def __enter__(self):
            assert state == {"lock_held": False, "store_started": False}
            state["lock_held"] = True
            events.append("lock_enter")
            return self

        def __exit__(self, *_args):
            assert state == {"lock_held": True, "store_started": False}
            state["lock_held"] = False
            events.append("lock_exit")

    class RecoveryStore:
        def __init__(self):
            self.plans = [_manual_recovery_plan()]
            if monitor_exit == "flat_completed":
                self.plans.append(_flat_recovery_plan())

        def start(self):
            assert state == {"lock_held": True, "store_started": False}
            state["store_started"] = True
            events.append("store_start")

        def stop(self):
            assert state == {"lock_held": True, "store_started": True}
            state["store_started"] = False
            events.append("store_stop")

        def verify_ctp_settlement(self, timeout):
            assert timeout == 5.0
            return {"evidence_complete": True, "read_only_safe": True}

        def subscribe(self, instrument):
            assert instrument == "SA701"

        def configure_ctp_execution_authorization(self, grant):
            return {
                "configured": True,
                "market_data_only": True,
                "grant_sha256": runner.sha256_json(grant),
            }

        def prepare_execution_recovery(self, proof):
            assert state == {"lock_held": True, "store_started": True}
            events.append("prepare")
            return self.plans.pop(0)

        def arm_execution_recovery(self, proof, *, recovery_token_sha256):
            pytest.fail("manual/FLAT monitoring must never arm recovery")

        def complete_execution_recovery(self, *, recovery_token_sha256):
            assert state == {"lock_held": True, "store_started": True}
            events.append("complete")
            return {
                "completed": True,
                "armed": False,
                "market_data_only": True,
                "recovery_only": False,
                "requires_new_preflight": True,
                "recovery_token_sha256": recovery_token_sha256,
            }

    identity = {
        "profile": config["environment"],
        "profile_basis": config["environment"],
        "sdk_profile": "set1_group1",
        "market_alignment": "actual_market_hours",
        "account_fingerprint": "acct_0123456789abcdef",
    }
    stage_a = {"selection": {"instrument": "SA701"}}
    stage_b = {
        "session": {"trading_day": "20260910"},
        "account": {"equity": 100000.0},
        "query_identity": {"trading_day": "20260910", "connection_generation": 7},
        "selection": {"instrument": "SA701"},
        "fee": {"source": "account_query"},
        "metadata": {},
        "ready_for_simnow": False,
        "ready_for_recovery": True,
        "recovery_required": True,
    }
    snapshots = iter([{"stage": "a"}, {"stage": "b"}])
    snapshot_calls = []
    monkeypatch.setattr(runner, "AccountLock", ObservedLock)
    monkeypatch.setattr(
        runner,
        "_build_live_store",
        lambda *_args, **_kwargs: (RecoveryStore(), identity, []),
    )
    monkeypatch.setattr(
        runner,
        "native_probe",
        lambda: {
            "accepted": True,
            "ctp_package_sha256": "b" * 64,
            "loaded_module_sha256": "a" * 64,
            "native_files": [],
            "native_loaded": True,
        },
    )

    def public_snapshot(*args, **kwargs):
        snapshot_calls.append((args, kwargs))
        return next(snapshots)

    monkeypatch.setattr(runner, "public_preflight_snapshot", public_snapshot)
    monkeypatch.setattr(runner, "validate_stage_a", lambda *_args, **_kwargs: stage_a)
    monkeypatch.setattr(runner, "validate_preflight", lambda *_args, **_kwargs: dict(stage_b))
    monkeypatch.setattr(
        runner,
        "_build_execution_authorization_grant",
        lambda **_kwargs: {"authorization": "test"},
    )

    def observed_sleep(seconds):
        assert seconds == runner.RECOVERY_MONITOR_POLL_SECONDS
        assert state == {"lock_held": True, "store_started": True}
        events.append("monitor_wait")
        if monitor_exit == "forced_termination":
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    monkeypatch.setattr(runner.time, "sleep", observed_sleep)

    result = runner.run_network(
        config,
        mode="simnow",
        purpose="engineering_smoke",
        preflight_only=False,
        prepare_settlement=False,
        receipt=receipt,
        output_directory=tmp_path / "recovery-monitor",
        run_seconds=60.0,
    )

    expected_state = "STOPPED_FLAT" if monitor_exit == "flat_completed" else "MANUAL_INTERVENTION"
    assert result["state"] == expected_state
    assert result["execution_recovery"]["monitor_exit"] == monitor_exit
    expected_middle = (
        ["monitor_wait", "prepare", "complete"]
        if monitor_exit == "flat_completed"
        else ["monitor_wait"]
    )
    assert events == [
        "lock_enter",
        "store_start",
        "prepare",
        *expected_middle,
        "store_stop",
        "lock_exit",
    ]
    assert len(snapshot_calls) == 2
    assert snapshot_calls[0][0][1] is None
    assert snapshot_calls[0][1] == {"product_id": "SA", "exchange_id": "CZCE"}
    assert snapshot_calls[1][0][1] == "SA701"
    assert snapshot_calls[1][1] == {"exchange_id": "CZCE"}
    manifest = json.loads(
        (tmp_path / "recovery-monitor" / "manifest.json").read_text(encoding="utf-8")
    )
    expected_exit_status = (
        "RECOVERY_STOPPED_FLAT"
        if monitor_exit == "flat_completed"
        else "RECOVERY_FORCED_TERMINATION"
    )
    assert manifest["exit_status"] == expected_exit_status


def test_daily_risk_uses_gross_minus_fee_once_and_requires_new_day_reconciliation(tmp_path):
    path = tmp_path / "risk.json"
    store = risk.DailyRiskStore(path)
    with pytest.raises(ValueError, match="complete reconciliation"):
        store.load_or_create(
            account_fingerprint="acct_a",
            trading_day="20260909",
            starting_equity=100000.0,
        )
    record = store.load_or_create(
        account_fingerprint="acct_a",
        trading_day="20260909",
        starting_equity=100000.0,
        reconciliation_complete=True,
    )
    store.record_closed_trade(10.0, 3.0)
    assert record.realized_pnl == 10.0
    assert record.fees == 3.0
    admitted, _, _ = store.admission(
        unrealized_pnl=-6.0,
        daily_loss_cny=500.0,
        daily_loss_fraction=0.005,
    )
    assert admitted  # 10 gross - 3 fee - 6 unrealized = +1, not -2.
    for _ in range(3):
        store.record_closed_trade(1.0, 2.0)
    assert record.consecutive_losses == 3
    assert record.halted_reason == "three_consecutive_losses"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("starting_equity", float("nan"), "must be finite"),
        ("realized_pnl", float("inf"), "must be finite"),
        ("fees", -1.0, "outside allowed bounds"),
        ("write_requests", -1, "nonnegative integer"),
    ],
)
def test_daily_risk_rejects_nonfinite_or_negative_persisted_values(tmp_path, field, value, message):
    path = tmp_path / "risk.json"
    store = risk.DailyRiskStore(path)
    store.load_or_create(
        account_fingerprint="acct_a",
        trading_day="20260909",
        starting_equity=100000.0,
        reconciliation_complete=True,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload, allow_nan=True), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        risk.DailyRiskStore(path).load_or_create(
            account_fingerprint="acct_a",
            trading_day="20260909",
            starting_equity=100000.0,
        )


def test_risk_persistence_failure_blocks_entry_but_allows_one_durable_emergency_per_action(
    tmp_path,
):
    store = risk.DailyRiskStore(tmp_path / "risk.json")
    store.load_or_create(
        account_fingerprint="acct_a",
        trading_day="20260909",
        starting_equity=100000.0,
        reconciliation_complete=True,
    )
    store.persistence_ok = False
    assert not store.reserve_entry(30)
    assert not store.reserve_write(emergency=False)
    assert store.reserve_write(
        emergency=True,
        reserve=2,
        allow_unpersisted_emergency=True,
        emergency_key="exit",
    )
    assert not store.reserve_write(
        emergency=True,
        reserve=2,
        allow_unpersisted_emergency=True,
        emergency_key="exit",
    )
    assert store.reserve_write(
        emergency=True,
        reserve=2,
        allow_unpersisted_emergency=True,
        emergency_key="cancel:1",
    )
    assert store.volatile_emergency_keys == {"exit", "cancel:1"}
    assert store.admission(unrealized_pnl=0.0)[0] is False


def test_strategy_reserve_catches_save_failure_and_keeps_one_emergency_path(monkeypatch, tmp_path):
    store = risk.DailyRiskStore(tmp_path / "risk.json")
    store.load_or_create(
        account_fingerprint="acct_a",
        trading_day="20260909",
        starting_equity=100000.0,
        reconciliation_complete=True,
    )

    def fail_save():
        store.persistence_ok = False
        store.last_error = "OSError"
        raise OSError("injected")

    monkeypatch.setattr(store, "save", fail_save)
    transitions = []
    holder = SimpleNamespace(
        p=SimpleNamespace(
            risk_store=store,
            maximum_entry_attempts=30,
            entry_budget_key="all",
            maximum_write_requests=100,
            emergency_write_reserve=20,
            mode="simnow",
            admitted=True,
            preflight_ready=True,
        ),
        _risk_failure_count=0,
        _risk_failure_reason="",
        _active_order=None,
        _gross_position_lots=lambda: 1,
        position=SimpleNamespace(size=1),
        state="OPEN",
        _drain_started=None,
        _clock=SimpleNamespace(monotonic_now=lambda: 10.0),
        _transition=lambda state, reason, now=None: transitions.append((state, reason, now)),
    )
    holder._latch_risk_failure = strategy_module.SAMidFrequencyStrategy._latch_risk_failure.__get__(
        holder
    )
    reserve = strategy_module.SAMidFrequencyStrategy._reserve
    assert reserve(holder, entry=True) is False
    assert transitions[-1][0] == "DRAINING"
    holder.state = "DRAINING"
    assert reserve(holder, entry=False, emergency=True, emergency_key="exit") is True
    assert reserve(holder, entry=False, emergency=True, emergency_key="exit") is False
    assert store.volatile_emergency_keys == {"exit"}


def test_entry_and_smoke_attempt_budgets_persist_across_process_objects(tmp_path):
    path = tmp_path / "risk.json"
    first = risk.DailyRiskStore(path)
    first.load_or_create(
        account_fingerprint="acct_a",
        trading_day="20260909",
        starting_equity=100000.0,
        reconciliation_complete=True,
    )
    assert first.reserve_entry(2, budget_key="engineering_smoke")
    second = risk.DailyRiskStore(path)
    record = second.load_or_create(
        account_fingerprint="acct_a",
        trading_day="20260909",
        starting_equity=999999.0,
    )
    assert record.starting_equity == 100000.0
    assert second.reserve_entry(2, budget_key="engineering_smoke")
    assert not second.reserve_entry(2, budget_key="engineering_smoke")
    assert record.smoke_entry_attempts == 2
    assert record.entry_attempts == 2


def test_gfd_and_fill_time_bounds_have_exact_3_5_60_900_boundaries():
    deadline = risk.GFDOrderDeadline(3.0, 5.0)
    deadline.submitted(10.0)
    assert deadline.action(12.999) == "wait"
    assert deadline.action(13.0) == "cancel"
    deadline.cancel_requested(13.0)
    assert deadline.action(17.999) == "wait_for_cancel_confirmation"
    assert deadline.action(18.0) == "unknown"
    bounds = risk.FillTimeBounds(earliest=100.0, latest=102.0, source="callback", trusted=False)
    assert not bounds.normal_exit_allowed(161.999, 60.0)
    assert bounds.normal_exit_allowed(162.0, 60.0)
    assert not bounds.maximum_expired(999.999, 900.0)
    assert bounds.maximum_expired(1000.0, 900.0)


@pytest.mark.parametrize(("direction", "expected_side"), [(1, "long"), (-1, "short")])
def test_strategy_entry_reaches_real_dual_side_broker_with_explicit_position_side(
    direction, expected_side
):
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 1500.0, 1501.0, 1499.0, 1500.0)]}
    )
    store = make_store(api=client, supports_dual_side=True)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    data._start()
    assert data.load() is True
    broker = store.getbroker(position_mode="dual_side", sdk_preflight=False)
    broker.start()
    transitions = []
    submitted_at = []
    holder = SimpleNamespace(
        state="FLAT",
        _active_order=None,
        data=data,
        p=SimpleNamespace(candidate_id="iter22-sa-v0", maximum_intent_age_seconds=1.0),
        _clock=SimpleNamespace(monotonic_now=lambda: 100.0),
        _reserve=lambda **_kwargs: True,
        _aligned_limit=lambda _side, _quote: 1500.0,
        _order_roles={},
        _entry_sent_monotonic=None,
        deadline=SimpleNamespace(submitted=submitted_at.append),
        _transition=lambda state, reason, now=None: transitions.append((state, reason, now)),
    )
    holder.buy = lambda **kwargs: broker.buy(owner=holder, **kwargs)
    holder.sell = lambda **kwargs: broker.sell(owner=holder, **kwargs)
    try:
        strategy_module.SAMidFrequencyStrategy._submit_entry(
            holder,
            direction,
            SimpleNamespace(recv_monotonic=100.0),
            "decision-v1",
        )
        payload = client.submitted_orders[-1]
        assert payload["position_mode"] == "dual_side"
        assert payload["position_side"] == expected_side
        assert payload["offset"] == "open"
        assert payload["time_in_force"] == "GFD"
        assert transitions[-1][0] == "ENTRY_PENDING"
    finally:
        broker.stop()
        data.stop()


def test_strategy_entry_intent_expires_before_any_risk_reservation():
    reservations = []
    transitions = []
    holder = SimpleNamespace(
        state="FLAT",
        _active_order=None,
        _clock=SimpleNamespace(monotonic_now=lambda: 102.000001),
        p=SimpleNamespace(maximum_intent_age_seconds=1.0),
        _reserve=lambda **kwargs: reservations.append(kwargs) or True,
        _transition=lambda state, reason, now=None: transitions.append((state, reason, now)),
    )
    strategy_module.SAMidFrequencyStrategy._submit_entry(
        holder,
        1,
        SimpleNamespace(recv_monotonic=101.0),
        "decision-v1",
    )
    assert reservations == []
    assert transitions == [("HALTED", "entry_intent_expired", 101.0)]


@pytest.mark.parametrize(
    ("position_side", "expected_order_side"), [("long", "sell"), ("short", "buy")]
)
def test_strategy_exit_reaches_real_dual_side_broker_with_explicit_position_side(
    position_side, expected_order_side
):
    client = FakeBtApiClient(
        positions=[
            {
                "instrument": DEFAULT_SYMBOL,
                "volume": 1,
                "direction": position_side,
                "price": 1500.0,
            }
        ],
        history={DEFAULT_SYMBOL: [make_bar(0, 1500.0, 1501.0, 1499.0, 1500.0)]},
    )
    store = make_store(api=client, supports_dual_side=True)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    data._start()
    assert data.load() is True
    broker = store.getbroker(position_mode="dual_side", sdk_preflight=False)
    broker.start()
    transitions = []
    holder = SimpleNamespace(
        broker=broker,
        data=data,
        position=broker.getposition(data),
        _active_order=None,
        _active_cycle_id="cycle-test-1",
        _order_cycles={},
        last_quote=object(),
        _reserve=lambda **_kwargs: True,
        _aligned_limit=lambda _side, _quote: 1500.0,
        _order_roles={},
        deadline=SimpleNamespace(submitted=lambda _now: None),
        _transition=lambda state, reason, now=None: transitions.append((state, reason, now)),
    )
    holder.getposition = lambda current_data, current_broker, side=None: (
        current_broker.getposition(current_data, side=side)
    )
    holder.buy = lambda **kwargs: broker.buy(owner=holder, **kwargs)
    holder.sell = lambda **kwargs: broker.sell(owner=holder, **kwargs)
    holder.close = bt.Strategy.close.__get__(holder)
    try:
        strategy_module.SAMidFrequencyStrategy._request_exit(
            holder, "maximum_hold", 200.0, emergency=True
        )
        payload = client.submitted_orders[-1]
        assert payload["side"] == expected_order_side
        assert payload["position_mode"] == "dual_side"
        assert payload["position_side"] == position_side
        assert payload["offset"] == "close"
        assert payload["time_in_force"] == "GFD"
        assert transitions[-1][0] == "EXIT_PENDING"
    finally:
        broker.stop()
        data.stop()


def test_residual_partial_close_requotes_exactly_twice_then_enters_unknown():
    class TerminalExitOrder:
        Partial = 3
        Completed = 4

        def __init__(self, ref):
            self.ref = ref
            self.size = 1
            self.status = self.Completed
            self.executed = SimpleNamespace(size=0, price=0, comm=0)
            self.info = {}

        def getstatusname(self):
            return "Completed"

        def alive(self):
            return False

    requotes = []
    unknown = []
    transitions = []
    holder = SimpleNamespace(
        p=SimpleNamespace(
            instrument="SA701",
            mode="simnow",
            max_exit_requotes=2,
            account_fingerprint="acct_0123456789abcdef",
            trading_day="20260909",
            connection_generation=7,
        ),
        data=SimpleNamespace(_name="SA701"),
        last_quote=None,
        _clock=SimpleNamespace(monotonic_now=lambda: 100.0),
        _order_roles={1: "exit", 2: "exit", 3: "exit"},
        _order_cycles={1: "cycle-test-1", 2: "cycle-test-1", 3: "cycle-test-1"},
        _active_cycle_id="cycle-test-1",
        _orders=[],
        _record=lambda *_args, **_kwargs: None,
        _fill_bounds=None,
        _order_terminal_refs=set(),
        _active_order=None,
        deadline=SimpleNamespace(confirmed_terminal=lambda: None),
        _gross_position_lots=lambda: 1,
        _exit_requotes_used=0,
        _transition=lambda state, reason, now=None: transitions.append((state, reason, now)),
        _request_exit=lambda reason, now, emergency: requotes.append((reason, now, emergency)),
        _enter_unknown=lambda reason, now: unknown.append((reason, now)),
    )
    notify = strategy_module.SAMidFrequencyStrategy.notify_order
    for ref in (1, 2, 3):
        order = TerminalExitOrder(ref)
        holder._active_order = order
        notify(holder, order)
    assert [item[0] for item in requotes] == [
        "residual_partial_close",
        "residual_partial_close",
    ]
    assert holder._exit_requotes_used == 2
    assert unknown == [("exit_terminal_with_residual", 100.0)]
    assert [item[1] for item in transitions] == [
        "residual_exit_requote_1",
        "residual_exit_requote_2",
    ]


def _reconciliation_snapshot(suffix: int, snapshot_hash="same"):
    queries = {
        name: {
            "request_id": suffix * 10 + index,
            "complete": True,
            "is_last_seen": True,
            "timed_out": False,
            "unsupported": False,
            "error_code": None,
        }
        for index, name in enumerate(("account", "positions", "orders", "trades"), 1)
    }
    queries["orders"]["records"] = [
        {
            "InstrumentID": "SA701",
            "ExchangeID": "CZCE",
            "FrontID": 1,
            "SessionID": 2,
            "OrderRef": f"order-{suffix}",
            "OrderSysID": f"sys-{suffix}",
        }
    ]
    queries["trades"]["records"] = [
        {
            "InstrumentID": "SA701",
            "ExchangeID": "CZCE",
            "TradeID": f"trade-{suffix}",
            "OrderSysID": f"sys-{suffix}",
        }
    ]
    return {
        "request_id": f"snapshot-{suffix}",
        "query_results": queries,
        "evidence_complete": True,
        "flat": True,
        "position_lots": 0,
        "active_order_count": 0,
        "nonzero_positions": [],
        "active_orders": [],
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "connection_generation": 7,
        "account_fingerprint": "0123456789abcdef",
        "trading_day": "20260909",
        "snapshot_hash": snapshot_hash,
        "completed_monotonic": 200.0 + suffix,
    }


def test_reconciliation_requires_two_distinct_complete_snapshots():
    class Env:
        stopped = 0

        def runstop(self):
            self.stopped += 1

    holder = SimpleNamespace(
        p=SimpleNamespace(
            account_fingerprint="acct_0123456789abcdef",
            connection_generation=7,
            trading_day="20260909",
            instrument="SA701",
        ),
        _clock=SimpleNamespace(monotonic_now=lambda: 999.0),
        _reconciliation_hash="",
        _reconciliation_count=0,
        _reconciliation_phase="drain_flat",
        _reconciliation_request_id="",
        _reconciliation_request_ids_seen=set(),
        _reconciliation_round_request_ids=[],
        _reconciliation_proofs=[],
        _reconciliation_identity=None,
        _reconciliation_started=100.0,
        _last_reconciliation_requested=100.0,
        _record=lambda *_args, **_kwargs: None,
        env=Env(),
        state="RECOVERING",
    )
    transitions = []

    def transition(state, reason, now=None):
        holder.state = state
        transitions.append((state, reason, now))

    holder._transition = transition
    consume = strategy_module.SAMidFrequencyStrategy.notify_reconciliation
    duplicate_ids = _reconciliation_snapshot(0)
    duplicate_ids["query_results"]["positions"]["request_id"] = duplicate_ids["query_results"][
        "account"
    ]["request_id"]
    assert consume(holder, duplicate_ids) is False
    first = _reconciliation_snapshot(1)
    assert consume(holder, first) is False
    assert consume(holder, first) is False
    assert holder.env.stopped == 0
    assert consume(holder, _reconciliation_snapshot(2)) is True
    assert holder.env.stopped == 1
    assert holder._reconciliation_proofs[-1]["request_ids"] == ["snapshot-1", "snapshot-2"]
    assert holder._reconciliation_proofs[-1]["distinct_request_ids"] is True
    assert holder._reconciliation_proofs[-1]["ctp_order_identity_complete"] is True
    assert holder._reconciliation_proofs[-1]["ctp_trade_identity_complete"] is True
    assert transitions[-1][0] == "STOPPED_FLAT"


def test_reconciliation_rejects_missing_broker_summary_counts():
    holder = SimpleNamespace(
        p=SimpleNamespace(
            account_fingerprint="acct_0123456789abcdef",
            connection_generation=7,
            trading_day="20260909",
            instrument="SA701",
        ),
        _clock=SimpleNamespace(monotonic_now=lambda: 999.0),
        _reconciliation_hash="",
        _reconciliation_count=0,
        _reconciliation_phase="drain_flat",
        _reconciliation_request_id="",
        _reconciliation_request_ids_seen=set(),
        _reconciliation_round_request_ids=[],
        _reconciliation_proofs=[],
        _reconciliation_identity=None,
        _reconciliation_started=100.0,
        _last_reconciliation_requested=100.0,
        env=SimpleNamespace(runstop=lambda: None),
        _transition=lambda *_args: None,
    )
    snapshot = _reconciliation_snapshot(1)
    snapshot.pop("position_lots")
    assert strategy_module.SAMidFrequencyStrategy.notify_reconciliation(holder, snapshot) is False


def test_unknown_reconciliation_has_two_automatic_rounds_then_read_only_monitoring():
    phases = []
    transitions = []
    holder = SimpleNamespace(
        p=SimpleNamespace(
            reconciliation_request_interval=1.0,
            maximum_unknown_reconciliation_rounds=2,
        ),
        _reconciliation_phase="unknown_resolution",
        _reconciliation_started=0.0,
        _last_reconciliation_requested=None,
        _reconciliation_requests_issued=0,
        broker=SimpleNamespace(),
        _transition=lambda state, reason, now=None: transitions.append((state, reason, now)),
        _block=lambda reason: pytest.fail(reason),
    )
    holder.notify_reconciliation = (
        strategy_module.SAMidFrequencyStrategy.notify_reconciliation.__get__(holder)
    )

    def request(_callback):
        phases.append(holder._reconciliation_phase)
        return {"queued": True}

    holder.broker.request_ctp_reconciliation = request
    holder._request_reconciliation = (
        strategy_module.SAMidFrequencyStrategy._request_reconciliation.__get__(holder)
    )
    holder._enter_manual_monitor = (
        strategy_module.SAMidFrequencyStrategy._enter_manual_monitor.__get__(holder)
    )
    holder._request_reconciliation(0.0)
    holder._request_reconciliation(1.0)
    holder._request_reconciliation(2.0)
    holder._request_reconciliation(3.0)
    assert phases[:2] == ["unknown_resolution", "unknown_resolution"]
    assert phases[2:] == ["manual_monitor", "manual_monitor"]
    assert transitions[-1][0] == "MANUAL_INTERVENTION"


def test_simnow_start_requires_complete_durable_execution_summary():
    def start_with(summary):
        transitions = []
        reconciliations = []
        holder = SimpleNamespace(
            p=SimpleNamespace(
                mode="simnow",
                purpose="engineering_smoke",
                research_status="RESEARCH_NOT_ESTABLISHED",
                lots=1,
                admitted=True,
                preflight_ready=True,
            ),
            broker=SimpleNamespace(get_execution_summary=lambda: summary),
            _clock=SimpleNamespace(monotonic_now=lambda: 10.0),
            _gross_position_lots=lambda: 0,
            _transition=lambda state, reason, now=None: transitions.append((state, reason, now)),
            _block=lambda _reason: None,
            _begin_reconciliation=lambda phase, reason, now: reconciliations.append(
                (phase, reason, now)
            ),
            _unknown_intents=0,
            _unknown_origin_was_draining=False,
        )
        strategy_module.SAMidFrequencyStrategy.start(holder)
        return transitions, reconciliations, holder

    safe = {
        "session_enabled": True,
        "trading_blocked": False,
        "evidence_errors": [],
        "active_orders": 0,
        "unknown_ids": [],
    }
    transitions, reconciliations, _holder = start_with(safe)
    assert transitions[-1][:2] == ("WARMING", "warmup_not_complete")
    assert reconciliations == []

    incomplete = {**safe, "unknown_ids": "not-a-list"}
    transitions, reconciliations, holder = start_with(incomplete)
    assert transitions == []
    assert reconciliations == [("unknown_resolution", "durable_intent_evidence_incomplete", 10.0)]
    assert holder._unknown_intents == 1


def test_strategy_evidence_failure_is_latched_without_escaping_callback():
    class BrokenReporter:
        calls = 0

        def append(self, *_args):
            self.calls += 1
            raise reporting.EvidenceWriteError("injected")

    reporter = BrokenReporter()
    holder = SimpleNamespace(
        reporter=reporter,
        _evidence_recording_failed=False,
        _evidence_failure_count=0,
        _evidence_failure_reason="",
        _clock=SimpleNamespace(monotonic_now=lambda: 10.0),
        _active_order=None,
        _gross_position_lots=lambda: 0,
        position=SimpleNamespace(size=0),
        state="FLAT",
        state_reason="",
    )
    record = strategy_module.SAMidFrequencyStrategy._record
    record(holder, "quotes", {"seq": 1})
    record(holder, "quotes", {"seq": 2})
    assert reporter.calls == 1
    assert holder.state == "HALTED"
    assert holder.state_reason == "evidence_write_failed"
    assert holder._evidence_failure_count == 1


def test_bar_identity_accepts_datetime_extensions():
    holder = SimpleNamespace(
        _latest_bar_event={
            "symbol": "SA701",
            "exchange": "CZCE",
            "asset_type": "futures",
            "bucket_start": datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc),
            "bucket_end": datetime(2026, 9, 9, 1, 1, tzinfo=timezone.utc),
            "available_at": datetime(2026, 9, 9, 1, 1, 0, 500000, tzinfo=timezone.utc),
            "bar_id": "bar-1",
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "volume_complete": True,
            "trading_day": "20260909",
            "action_day": "20260909",
            "connection_generation": 7,
            "first_ingest_seq": 1,
            "last_ingest_seq": 2,
            "bar_sequence": 1,
            "closure_reason": "tick",
        },
        p=SimpleNamespace(
            trading_day="20260909",
            connection_generation=7,
            instrument="SA701",
            watermark_milliseconds=500,
        ),
        data=SimpleNamespace(_name="SA701"),
        _last_bar_sequence=0,
        _last_bar_ingest_seq=0,
    )
    unavailable = copy.deepcopy(holder)
    unavailable._latest_bar_event["available_at"] = unavailable._latest_bar_event["bucket_end"]
    assert not strategy_module.SAMidFrequencyStrategy._bar_identity(unavailable, 0.0)[4]
    bar_id, end, available, day, valid, reason = (
        strategy_module.SAMidFrequencyStrategy._bar_identity(holder, 0.0)
    )
    assert bar_id == "bar-1"
    assert available - end == pytest.approx(0.5)
    assert day == "20260909"
    assert valid and not reason


def _bare_quote_strategy():
    event = datetime(2026, 9, 9, 1, 0, tzinfo=timezone.utc).timestamp()
    holder = object.__new__(strategy_module.SAMidFrequencyStrategy)
    holder.p = SimpleNamespace(
        tick_size=1.0,
        trading_day="20260909",
        connection_generation=7,
        sessions=strategy_module.DEFAULT_SESSIONS,
        max_quote_age_seconds=2.0,
        mode="shadow",
        session_calendar_sha256="",
    )
    holder._clock = SimpleNamespace(utc_now=lambda: event, monotonic_now=lambda: 100.0)
    holder.quote_window = features.QuoteFeatureWindow(1.0)
    holder.confirmation = signals.ConfirmationTracker()
    holder._current_session_id = ""
    holder._current_session_end = 0.0
    holder._session_has_new_bar = False
    holder._invalid_quotes = 0
    holder._block_counts = {}
    holder._observation_last_key = None
    holder._observation_last_contiguous_event = None
    holder._observation_first_event = None
    holder._observation_last_event = None
    holder._observation_seconds_by_session = {}
    holder._observation_generations = set()
    holder._qualified_quotes = 0
    holder.last_quote = None
    holder.last_fast = None
    holder._record = lambda *_args, **_kwargs: None
    holder._advance_time = lambda *_args, **_kwargs: None
    holder._evaluate_entry = lambda *_args, **_kwargs: None
    return holder


def test_strategy_rejects_old_trading_day_generation_and_missing_dynamic_limits():
    notify = strategy_module.SAMidFrequencyStrategy.notify_tick
    old_day = _bare_quote_strategy()
    notify(old_day, _quote(trading_day="20260908"))
    assert old_day._block_counts["quote:trading_day_mismatch"] == 1
    old_generation = _bare_quote_strategy()
    notify(old_generation, _quote(connection_generation=6))
    assert old_generation._block_counts["quote:connection_generation_mismatch"] == 1
    missing_limit = _bare_quote_strategy()
    notify(missing_limit, _quote(lower_limit=None))
    assert missing_limit._block_counts["quote:invalid_lower_limit"] == 1
    valid = _bare_quote_strategy()
    notify(valid, _quote())
    assert valid.last_quote.lower_limit == 1200.0
    assert valid.last_quote.upper_limit == 2200.0


def test_g3_and_g4_are_machine_judgeable_and_zero_cycle_is_incomplete():
    identity = {
        "profile": "simnow_first_group1",
        "sdk_profile": "set1_group1",
        "market_alignment": "actual_market_hours",
    }
    report = {
        "quote_window_seconds": 60.0,
        "observation_evidence": {
            "valid_session_seconds": 3600.0,
            "qualified_completed_bars": 60,
            "expected_connection_generation": 7,
            "trading_day": "20260909",
        },
    }
    terminal = {
        "connection_generation": 7,
        "trading_day": "20260909",
        "environment_profile": "set1_group1",
        "request_counts": {
            "settlement_confirm": 0,
            "order_insert": 0,
            "order_action": 0,
        },
    }
    assert runner._observation_evidence(report, terminal, identity)["g3_gate_status"] == "PASS"
    terminal["request_counts"]["order_insert"] = 1
    assert (
        runner._observation_evidence(report, terminal, identity)["g3_gate_status"] == "INCOMPLETE"
    )
    receipt = {
        "purpose": "engineering_smoke",
        "account_fingerprint": "acct_0123456789abcdef",
        "trading_day": "20260909",
        "instrument": "SA701",
    }
    zero = {
        "state": "STOPPED_FLAT",
        "position_lots": 0,
        "unknown_intents": 0,
        "active_order": None,
        "account_fingerprint": "acct_0123456789abcdef",
        "trading_day": "20260909",
        "connection_generation": 7,
        "instrument": "SA701",
        "engineering_trigger_fired": False,
    }
    assert (
        runner._g4_evidence(zero, purpose="engineering_smoke", receipt=receipt)["g4_gate_status"]
        == "INCOMPLETE"
    )
    cycle = {
        "cycle_id": "1" * 64,
        "cycle_identity_sha256": "2" * 64,
        "account_fingerprint": "acct_0123456789abcdef",
        "trading_day": "20260909",
        "connection_generation": 7,
        "instrument": "SA701",
        "exchange": "CZCE",
        "order_identities": [
            {
                "instrument": "SA701",
                "exchange": "CZCE",
                "front_id": "1",
                "session_id": "2",
                "order_ref": "entry-ref",
                "order_sys_id": "entry-sys",
            },
            {
                "instrument": "SA701",
                "exchange": "CZCE",
                "front_id": "1",
                "session_id": "2",
                "order_ref": "exit-ref",
                "order_sys_id": "exit-sys",
            },
        ],
        "trade_identities": [
            {
                "instrument": "SA701",
                "exchange": "CZCE",
                "trade_id": "entry-trade",
                "order_sys_id": "entry-sys",
            },
            {
                "instrument": "SA701",
                "exchange": "CZCE",
                "trade_id": "exit-trade",
                "order_sys_id": "exit-sys",
            },
        ],
    }
    closed = {
        **zero,
        "trades": [
            {
                **cycle,
                "hypothetical": False,
                "gross_pnl": 1.0,
                "ctp_identity_complete": True,
            }
        ],
        "reconciliation_proofs": [
            {
                **cycle,
                "phase": "closed",
                "complete": True,
                "distinct_request_ids": True,
                "request_ids": ["a", "b"],
                "ctp_order_identity_complete": True,
                "ctp_trade_identity_complete": True,
                "cycle_binding_complete": True,
            }
        ],
        "engineering_trigger_fired": True,
    }
    shutdown = {
        "status": "PASS",
        "remote_flat_proven": True,
        "store_shutdown_state": "PASS",
        "active_order_count": 0,
        "local_position_count": 0,
        "remote_position_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
    }
    assert (
        runner._g4_evidence(
            closed,
            purpose="engineering_smoke",
            receipt=receipt,
            shutdown_summary=shutdown,
        )["g4_gate_status"]
        == "PASS"
    )


def test_evidence_normal_queue_overflow_latches_and_counts(monkeypatch, tmp_path):
    release = threading.Event()
    original = reporting.EvidenceWriter._writer_loop

    def paused(writer):
        release.wait(5.0)
        original(writer)

    monkeypatch.setattr(reporting.EvidenceWriter, "_writer_loop", paused)
    writer = reporting.EvidenceWriter(
        tmp_path,
        min_free_bytes=0,
        audit_queue_limit=1,
        audit_flush_interval=0.01,
    )
    writer.append("quotes", {"seq": 1})
    with pytest.raises(reporting.EvidenceWriteError, match="queue"):
        writer.append("quotes", {"seq": 2})
    assert writer.opening_allowed is False
    assert writer.dropped_counts["quotes"] == 1
    release.set()
    writer.close()


def test_evidence_critical_is_fsynced_even_after_low_disk_latch(monkeypatch, tmp_path):
    writer = reporting.EvidenceWriter(tmp_path, min_free_bytes=0)
    fsync_calls = []
    real_fsync = reporting.os.fsync

    def observed_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    def low_disk():
        writer._latch_failure("disk_free_below_limit")
        return False

    monkeypatch.setattr(reporting.os, "fsync", observed_fsync)
    monkeypatch.setattr(writer, "_check_disk", low_disk)
    with pytest.raises(reporting.EvidenceWriteError, match="disk_free"):
        writer.append("quotes", {"seq": 1})
    path = writer.append("orders", {"ref": 1})
    assert path.read_text(encoding="utf-8").strip() == '{"ref":1}'
    assert fsync_calls
    assert writer.counts["orders"] == writer.enqueued_counts["orders"] == 1
    writer.close()


def test_evidence_close_drains_all_accepted_normal_records(tmp_path):
    writer = reporting.EvidenceWriter(
        tmp_path,
        min_free_bytes=0,
        audit_queue_limit=20,
        audit_flush_interval=0.01,
    )
    for sequence in range(10):
        writer.append("signals", {"seq": sequence})
    assert writer.close(timeout=5.0)
    assert writer.enqueued_counts["signals"] == 10
    assert writer.counts["signals"] == 10
    assert writer.pending_counts["signals"] == 0


def test_manifest_failure_cannot_be_overwritten_by_success_status(tmp_path):
    writer = reporting.EvidenceWriter(tmp_path, min_free_bytes=0)
    manifest = writer.manifest(
        run_id="r1",
        purpose="observation",
        mode="shadow",
        environment="simnow_first_group1",
        candidate_id="iter22-sa-v0",
        config_hash="c",
        code_hash="s",
        data_hash="d",
        account_id_hash="acct_a",
        instrument="SA701",
        trading_day="20260909",
        started_at_utc="2026-09-09T00:00:00Z",
        fee_source="query",
        hypothetical_fills=False,
    )
    writer._latch_failure("test_failure")
    writer.finalize_manifest(manifest, "PASS_SHADOW_G3")
    saved = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert saved["exit_status"] == "FAIL_EVIDENCE_INCOMPLETE"
    assert saved["evidence_health"]["complete"] is False


def test_evidence_rotation_limit_fails_closed_without_deleting_frozen_files(tmp_path):
    writer = reporting.EvidenceWriter(
        tmp_path,
        min_free_bytes=0,
        rotate_bytes=12,
        max_rotated_files_per_stream=1,
    )
    writer.append("risk_events", {"event": "first"})
    writer.append("risk_events", {"event": "second"})
    frozen = tmp_path / "risk_events.jsonl.0001"
    assert frozen.is_file()
    with pytest.raises(reporting.EvidenceWriteError, match="rotation"):
        writer.append("risk_events", {"event": "third"})
    assert frozen.is_file()
    assert writer.opening_allowed is False
    assert writer.failure_reason == "evidence_rotation_limit"
    writer.close()


def test_retention_deletes_only_released_unprotected_runs_and_audits_protection(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
    directories = []
    for day in range(1, 23):
        run_id = f"run-{day:02d}"
        directory = root / run_id
        directory.mkdir()
        manifest = {
            "schema_version": "iter22.manifest.v1",
            "run_id": run_id,
            "trading_day": f"202601{day:02d}",
            "exit_status": "PASS_REPLAY_PATH",
        }
        path = directory / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        directories.append((directory, manifest, path))

    for directory, manifest, path in directories[:2]:
        (directory / "retention-release.json").write_text(
            json.dumps(
                {
                    "schema_version": "iter22.retention-release.v1",
                    "run_id": manifest["run_id"],
                    "manifest_sha256": reporting.sha256_file(path),
                    "released_at_utc": "2026-09-09T00:00:00Z",
                    "released_by": "acceptance-owner",
                    "reason": "explicit test release",
                }
            ),
            encoding="utf-8",
        )
    protected_directory, protected_manifest, _path = directories[0]
    (protected_directory / "evidence-protection.json").write_text(
        json.dumps(
            {
                "schema_version": "iter22.evidence-protection.v1",
                "run_id": protected_manifest["run_id"],
                "kind": "acceptance",
                "reference_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )

    result = runner.apply_evidence_retention(root, retain_trading_days=20)
    assert result["status"] == "COMPLETE"
    assert protected_directory.is_dir()
    assert not directories[1][0].exists()
    assert result["deleted_runs"] == ["run-02"]
    assert result["protected_runs"] == ["run-01"]
    audit = (root / "retention_audit.jsonl").read_text(encoding="utf-8")
    assert "SKIPPED_PROTECTED" in audit
    assert "DELETED" in audit


def test_native_replay_is_deterministic_real_cerebro_path_without_pnl(tmp_path):
    assert not hasattr(strategy_module.SAMidFrequencyStrategy, "report")
    config = _config()
    first = runner.run_replay(
        config,
        output_directory=tmp_path / "first",
        scenario="no_signal",
        run_id="replay-first",
    )
    second = runner.run_replay(
        config,
        output_directory=tmp_path / "second",
        scenario="no_signal",
        run_id="replay-second",
    )
    assert first["business_summary_hash"] == second["business_summary_hash"]
    assert first["trade_logger"]["finalized"] is True
    assert first["trade_logger"]["extensions"]["sa_midfreq"]["mode"] == "replay"
    # Each completed 1m BtApiFeed bar reaches both the native callback surface
    # and the LineSeries path. TradeLogger reports each source bar once.
    fixture = json.loads((EXAMPLE / config["replay"]["fixture"]).read_text(encoding="utf-8"))
    expected_source_bars = sum(
        int(
            (
                datetime.fromisoformat(session_end).timestamp()
                - datetime.fromisoformat(session_start).timestamp()
            )
            // 60
        )
        for session_start, session_end in fixture["sessions"]
    )
    assert first["trade_logger"]["event_counts"]["bars"] == expected_source_bars
    assert first["runtime_chain"] == {
        "cerebro": "backtrader.cerebro.Cerebro",
        "store": "backtrader.stores.btapistore.BtApiStore",
        "feed": "backtrader.feeds.btapifeed.BtApiFeed",
        "broker": "backtrader.brokers.btapibroker.BtApiBroker",
        "strategy": f"{PACKAGE}.strategy.SAMidFrequencyStrategy",
    }
    assert first["closed_bars"] == second["closed_bars"] == 64
    assert first["observation_evidence"]["qualified_completed_bars"] >= 60
    assert first["orders"] == []
    assert first["sdk_write_requests"] == 0
    assert first["execution_basis"] == "none"
    assert first["hypothetical_fills"] is False
    assert first["pnl_fields_emitted"] is False
    assert "gross_pnl" not in first and "net_pnl" not in first
    daily = json.loads((tmp_path / "first" / "daily_report.json").read_text(encoding="utf-8"))
    assert daily["execution_basis"] == "none"
    assert daily["pnl_fields_emitted"] is False
    assert "gross_pnl" not in daily and "net_pnl_estimated" not in daily
    daily_markdown = (tmp_path / "first" / "daily_report.md").read_text(encoding="utf-8")
    assert "# Iteration 22 Daily Report" in daily_markdown
    assert '"pnl_fields_emitted": false' in daily_markdown
    manifest = json.loads((tmp_path / "first" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["exit_status"] == "PASS_REPLAY_PATH"
    assert manifest["execution_basis"] == "none"
    assert manifest["evidence_dropped_counts"] == dict.fromkeys(reporting.EvidenceWriter.STREAMS, 0)
    assert manifest["source_components"]["backtrader"]["path"].startswith(str(REPO))
    assert manifest["source_components"]["backtrader_trade_logger"]["path"].endswith(
        "backtrader/observers/trade_logger.py"
    )
    trade_logger_directory = tmp_path / "first" / "trade-logger"
    assert (trade_logger_directory / "system.log").is_file()
    for high_rate_file in (
        "tick.log",
        "bar.log",
        "position.log",
        "indicator.log",
        "value.log",
        "current_position.yaml",
    ):
        assert not (trade_logger_directory / high_rate_file).exists()


def test_sa_trade_logger_extension_is_visible_in_a_live_cerebro_snapshot(monkeypatch, tmp_path):
    snapshots = []
    original_attach = runner._attach_trade_logger

    def attach_with_probe(cerebro, output_directory):
        original_attach(cerebro, output_directory)

        class SnapshotProbe(bt.Analyzer):
            def next(self):
                snapshots.append(copy.deepcopy(self.strategy.stats.trade_logger.snapshot()))

        cerebro.addanalyzer(SnapshotProbe, _name="trade_logger_snapshot_probe")

    monkeypatch.setattr(runner, "_attach_trade_logger", attach_with_probe)
    runner.run_replay(
        _config(),
        output_directory=tmp_path / "snapshot-live",
        scenario="no_signal",
        run_id="snapshot-live",
    )

    live_extensions = [
        item.get("extensions", {}).get("sa_midfreq", {})
        for item in snapshots
        if item.get("finalized") is False
    ]
    assert live_extensions
    assert any(item.get("mode") == "replay" for item in live_extensions)
    assert any(item.get("closed_bars", 0) > 0 for item in live_extensions)


def test_sa_trade_logger_update_failure_is_diagnosed_and_fails_closed(monkeypatch, tmp_path):
    def reject_context(_self, _mapping, namespace="strategy"):
        assert namespace == "sa_midfreq"
        raise RuntimeError("observer test rejection")

    monkeypatch.setattr(bt.observers.TradeLogger, "update_report_context", reject_context)
    output_directory = tmp_path / "context-failure"

    with pytest.raises(RuntimeError, match="missing the sa_midfreq extension"):
        runner.run_replay(
            _config(),
            output_directory=output_directory,
            scenario="no_signal",
            run_id="context-failure",
        )

    records = [
        json.loads(line)
        for line in (output_directory / "risk_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    diagnostics = [
        item for item in records if item.get("event") == "trade_logger_context_publish_failed"
    ]
    assert any(
        item["reason"] == "update_raised" and item["exception_type"] == "RuntimeError"
        for item in diagnostics
    )
    assert not any(item["exception_type"] == "IndexError" for item in diagnostics)
    failure = json.loads((output_directory / "failure.json").read_text(encoding="utf-8"))
    assert failure["status"] == "FAIL_CLOSED"


def test_sa_stale_trade_logger_extension_is_rejected_without_per_tick_retries(
    monkeypatch, tmp_path
):
    """A later publication failure cannot export the earlier live snapshot."""
    original_update = bt.observers.TradeLogger.update_report_context
    calls = []

    def accept_once_then_raise(observer, mapping, namespace="strategy"):
        calls.append(namespace)
        if len(calls) == 1:
            return original_update(observer, mapping, namespace=namespace)
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(bt.observers.TradeLogger, "update_report_context", accept_once_then_raise)
    output_directory = tmp_path / "stale-context"

    with pytest.raises(RuntimeError, match="stale after a publish failure"):
        runner.run_replay(
            _config(),
            output_directory=output_directory,
            scenario="no_signal",
            run_id="stale-context",
        )

    records = [
        json.loads(line)
        for line in (output_directory / "risk_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(
        item.get("event") == "trade_logger_context_publish_failed"
        and item.get("reason") == "update_raised"
        and item.get("exception_type") == "RuntimeError"
        for item in records
    )
    # The replay has thousands of quotes.  Publication remains bounded by
    # completed bars plus the 128-quote cadence, rather than every quote.
    assert 2 <= len(calls) < 200
    failure = json.loads((output_directory / "failure.json").read_text(encoding="utf-8"))
    assert failure["status"] == "FAIL_CLOSED"


def test_sa_report_position_lots_use_dual_leg_cache_without_broker_queries():
    class Broker:
        def __init__(self):
            self.getposition_calls = 0

        def get_param(self, name, default=None):
            return "dual_side" if name == "position_mode" else default

        def get_cached_report_state(self):
            return {
                "positions": {"SA701": SimpleNamespace(size=0)},
                "position_legs": {
                    "SA701": {
                        "long": SimpleNamespace(size=1),
                        "short": SimpleNamespace(size=1),
                    }
                },
            }

        def getposition(self, _data, **_kwargs):
            self.getposition_calls += 1
            raise AssertionError("report cache helper must not call getposition")

    broker = Broker()
    holder = SimpleNamespace(broker=broker, data=SimpleNamespace(_name="SA701"))
    holder._finite_lots = strategy_module.SAMidFrequencyStrategy._finite_lots
    holder._cached_mapping_value = strategy_module.SAMidFrequencyStrategy._cached_mapping_value
    holder._report_data = strategy_module.SAMidFrequencyStrategy._report_data.__get__(holder)

    lots, complete = strategy_module.SAMidFrequencyStrategy._cached_report_position_lots(holder)

    assert (lots, complete) == (2, True)
    assert broker.getposition_calls == 0

    class NetOnlyBroker(Broker):
        def get_cached_report_state(self):
            return {"positions": {"SA701": {"size": -3}}}

    holder.broker = NetOnlyBroker()
    lots, complete = strategy_module.SAMidFrequencyStrategy._cached_report_position_lots(holder)
    assert (lots, complete) == (3, False)
    assert holder.broker.getposition_calls == 0


def test_business_summary_hash_excludes_trade_logger_runtime_telemetry():
    report = {
        "state": "STOPPED_FLAT",
        "closed_bars": 64,
        "orders": [],
        "trade_logger": {
            "run_id": "observer-run-1",
            "generated_at": "2026-09-10T00:00:01+00:00",
            "started_at": "2026-09-10T00:00:00+00:00",
            "finalized_at": "2026-09-10T00:00:01+00:00",
            "event_counts": {"bars": 64, "ticks": 65},
            "monitoring": {"counts": {"observer_callbacks": 64}},
        },
    }
    expected = reporting.business_summary_hash(report)

    runtime_changed = copy.deepcopy(report)
    runtime_changed["trade_logger"].update(
        run_id="observer-run-2",
        generated_at="2026-09-10T00:02:00+00:00",
        finalized_at="2026-09-10T00:02:00+00:00",
        event_counts={"bars": 999, "ticks": 1001},
    )
    runtime_changed["business_summary_hash"] = expected
    assert reporting.business_summary_hash(runtime_changed) == expected

    business_changed = copy.deepcopy(runtime_changed)
    business_changed["closed_bars"] = 63
    assert reporting.business_summary_hash(business_changed) != expected


def test_replay_client_exposes_frozen_eof_watermark_without_runstop():
    clock = runner.ReplayClock(100.0)
    client = runner.ReplayClient([], clock, eof_event_time_watermark=160.5)
    assert client.is_source_exhausted("SA701") is True
    assert client.get_source_event_time_watermark("SA701") == 160.5
    assert not hasattr(client, "set_stop_callback")


def test_ctp_package_manifest_uses_the_frozen_canonical_json_contract():
    manifest = [
        {"path": "__init__.py", "sha256": "1" * 64},
        {"path": "ctp/client.py", "sha256": "2" * 64},
    ]
    diagnostics = {
        "ctp_package_manifest": manifest,
        "ctp_package_sha256": reporting.sha256_json(manifest),
    }

    assert runner._validate_ctp_package_manifest(diagnostics) == manifest

    drifted = copy.deepcopy(diagnostics)
    drifted["ctp_package_manifest"][1]["sha256"] = "3" * 64
    with pytest.raises(runner.PreflightError, match="manifest hash"):
        runner._validate_ctp_package_manifest(drifted)


def test_native_probe_rejects_a_child_report_with_package_drift(monkeypatch):
    manifest = [{"path": "__init__.py", "sha256": "1" * 64}]
    child = {
        "ready": True,
        "native_loaded": True,
        "ctp_package_manifest": manifest,
        "ctp_package_sha256": reporting.sha256_json(manifest),
        "ctp_package_manifest_verified": False,
        "native_files": [{"path": "/tmp/native.so", "sha256": "2" * 64}],
    }
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(child),
        ),
    )

    result = runner.native_probe()

    assert result["accepted"] is False
    assert result["ctp_package_manifest"] == manifest


def test_strategy_identity_is_stable_across_receipt_renewal_and_bound_to_source(monkeypatch):
    config = _config()
    monkeypatch.setattr(
        runner,
        "source_file_hashes",
        lambda: {"run.py": "a" * 64, "strategy.py": "b" * 64},
    )
    first = runner._strategy_identity_sha256(
        config,
        purpose="engineering_smoke",
    )
    second = runner._strategy_identity_sha256(
        config,
        purpose="engineering_smoke",
    )

    assert first == second
    assert len(first) == 64
    assert all(character in "0123456789abcdef" for character in first)

    monkeypatch.setattr(
        runner,
        "source_file_hashes",
        lambda: {"run.py": "e" * 64, "strategy.py": "b" * 64},
    )
    assert first != runner._strategy_identity_sha256(config, purpose="engineering_smoke")

    changed_config = copy.deepcopy(config)
    changed_config["candidate_id"] = "iter22-sa-v1"
    assert first != runner._strategy_identity_sha256(changed_config, purpose="engineering_smoke")
    assert first != runner._strategy_identity_sha256(config, purpose="natural_signal")

    first_arm_proof = dict.fromkeys(runner.ARMING_PROOF_KEYS, "f" * 64)
    first_arm_proof.update(
        connection_generation=7,
        instrument="CZCE.SA701",
        trading_day="20260910",
        environment_profile="set1_group1",
        account_fingerprint="acct_0123456789abcdef",
        receipt_sha256="c" * 64,
    )
    renewed_arm_proof = {**first_arm_proof, "receipt_sha256": "d" * 64}
    assert runner.sha256_json(first_arm_proof) != runner.sha256_json(renewed_arm_proof)


def test_nonflat_preflight_is_admitted_only_to_execution_recovery(tmp_path):
    config = _manual_config(tmp_path)
    stage_a = runner.validate_stage_a(
        _snapshot(config),
        config,
        receipt=None,
        expected_account="acct_0123456789abcdef",
        expected_profile="set1_group1",
    )
    stage_b = _snapshot(config, stage_b=True)
    stage_b["session"].update(
        trading_ready=True,
        ready=True,
        settlement_state="confirmed",
    )
    stage_b["queries"]["positions"]["records"] = [
        {
            "InstrumentID": "SA701",
            "ExchangeID": "CZCE",
            "PosiDirection": "2",
            "HedgeFlag": "1",
            "Position": 1,
            "TodayPosition": 1,
            "YdPosition": 0,
            "LongFrozen": 0,
            "ShortFrozen": 0,
        }
    ]

    with pytest.raises(runner.PreflightError, match="readiness is incomplete"):
        runner.validate_preflight(
            stage_b,
            config,
            mode="simnow",
            stage_a=stage_a,
            expected_account="acct_0123456789abcdef",
            expected_profile="set1_group1",
        )

    result = runner.validate_preflight(
        stage_b,
        config,
        mode="simnow",
        stage_a=stage_a,
        expected_account="acct_0123456789abcdef",
        expected_profile="set1_group1",
        allow_execution_recovery=True,
    )
    assert result["ready_for_simnow"] is False
    assert result["ready_for_recovery"] is True
    assert result["recovery_required"] is True


class _RecoveryOrchestrationStore:
    def __init__(self, plans, *, completion_error=False):
        self.plans = [copy.deepcopy(plan) for plan in plans]
        self.events = []
        self.completion_error = completion_error
        self.market_data_only = True

    def prepare_execution_recovery(self, proof):
        self.events.append(("prepare", dict(proof)))
        self.market_data_only = True
        return self.plans.pop(0)

    def arm_execution_recovery(self, proof, *, recovery_token_sha256):
        self.events.append(("arm", recovery_token_sha256, dict(proof)))
        self.market_data_only = False
        return {
            "recovery_only": True,
            "execution_cycle_id": "sdk-cycle-1",
            "proof_sha256": "f" * 64,
        }

    def cancel_execution_recovery_orders(self, *, recovery_token_sha256):
        self.events.append(("cancel", recovery_token_sha256))
        return [{"queued": True}]

    def wait_for_commands(self, timeout):
        self.events.append(("wait", timeout))
        return True

    def complete_execution_recovery(self, *, recovery_token_sha256):
        self.events.append(("complete", recovery_token_sha256))
        self.market_data_only = True
        if self.completion_error:
            raise RuntimeError("query barrier failed")
        return {
            "completed": True,
            "armed": False,
            "market_data_only": True,
            "recovery_only": False,
            "requires_new_preflight": True,
            "recovery_token_sha256": recovery_token_sha256,
        }


def test_external_unowned_recovery_plan_performs_zero_writes(tmp_path):
    store = _RecoveryOrchestrationStore(
        [
            {
                "status": "MANUAL_INTERVENTION",
                "execution_cycle_id": None,
                "recovery_token_sha256": "",
                "allowed_cancels": [],
                "allowed_closes": [],
                "unknown_ids": ["external_position"],
            }
        ]
    )

    result = runner._orchestrate_execution_recovery(
        store,
        {"proof": "read-only"},
        command_timeout=1.0,
    )

    assert result["plan"]["status"] == "MANUAL_INTERVENTION"
    assert result["write_actions"] == {"arms": 0, "cancels": 0, "closes": 0}
    assert [event[0] for event in store.events] == ["prepare"]
    terminal = runner._terminal_recovery_result(
        result,
        run_id="recovery-run",
        identity={"account_fingerprint": "acct", "sdk_profile": "simnow"},
        instrument="SA701",
        output_directory=tmp_path,
    )
    assert terminal["state"] == "MANUAL_INTERVENTION"
    assert terminal["position_lots"] is None
    assert terminal["remote_active_orders"] is None


def _flat_recovery_plan(token="4" * 64):
    zeros = {
        "long_today": "0",
        "long_yesterday": "0",
        "short_today": "0",
        "short_yesterday": "0",
    }
    return {
        "status": "FLAT",
        "execution_cycle_id": None,
        "recovery_token_sha256": token,
        "allowed_actions": ["complete"],
        "allowed_cancels": [],
        "allowed_closes": [],
        "unknown_ids": [],
        "remote_position": zeros,
        "owned_position": dict(zeros),
    }


def test_initial_flat_recovery_runs_completion_barrier_before_stopped_flat(tmp_path):
    plan = _flat_recovery_plan()
    store = _RecoveryOrchestrationStore([plan])

    outcome = runner._orchestrate_execution_recovery(
        store,
        {"proof": "bound"},
        command_timeout=1.0,
    )
    result = runner._terminal_recovery_result(
        outcome,
        run_id="recovery-run",
        identity={"account_fingerprint": "acct", "sdk_profile": "simnow"},
        instrument="SA701",
        output_directory=tmp_path,
    )

    assert [event[0] for event in store.events] == ["prepare", "complete"]
    assert outcome["write_actions"] == {"arms": 0, "cancels": 0, "closes": 0}
    assert outcome["completion"]["completed"] is True
    assert result["state"] == "STOPPED_FLAT"
    assert result["execution_recovery"]["completed"] is True
    assert result["execution_recovery"]["normal_closed_cycles"] == 0


def test_flat_recovery_completion_failure_stays_manual_and_read_only(tmp_path):
    store = _RecoveryOrchestrationStore(
        [_flat_recovery_plan()],
        completion_error=True,
    )

    outcome = runner._orchestrate_execution_recovery(
        store,
        {"proof": "bound"},
        command_timeout=1.0,
    )
    result = runner._terminal_recovery_result(
        outcome,
        run_id="recovery-run",
        identity={"account_fingerprint": "acct", "sdk_profile": "simnow"},
        instrument="SA701",
        output_directory=tmp_path,
    )

    assert [event[0] for event in store.events] == ["prepare", "complete"]
    assert store.market_data_only is True
    assert outcome["completion"] == {
        "completed": False,
        "status": "failed",
        "error_code": "recovery_completion_failed",
    }
    assert result["state"] == "MANUAL_INTERVENTION"
    assert result["execution_recovery"]["status"] == "MANUAL_INTERVENTION"
    assert result["execution_recovery"]["prepared_status"] == "FLAT"
    assert result["execution_recovery"]["completed"] is False


def _manual_recovery_plan(reason="external_position"):
    return {
        "status": "MANUAL_INTERVENTION",
        "execution_cycle_id": None,
        "recovery_token_sha256": "",
        "allowed_actions": [],
        "allowed_cancels": [],
        "allowed_closes": [],
        "unknown_ids": [reason],
    }


def _monitor_recovery(
    store,
    initial,
    tmp_path,
    *,
    stop_reason=lambda: None,
    sleep=lambda _seconds: None,
    persist=None,
):
    return runner._monitor_read_only_execution_recovery(
        store,
        {"proof": "bound"},
        initial,
        run_id="recovery-run",
        account_fingerprint="acct_0123456789abcdef",
        trading_day="20260910",
        instrument="SA701",
        operator_takeover_path=tmp_path / "operator_takeover.json",
        stop_reason=stop_reason,
        persist=persist,
        sleep=sleep,
        poll_interval=0.0,
    )


def test_manual_startup_recovery_keeps_resources_and_queries_until_sdk_flat(tmp_path):
    store = _RecoveryOrchestrationStore(
        [_manual_recovery_plan(), _manual_recovery_plan("still_unknown"), _flat_recovery_plan()]
    )
    initial = runner._orchestrate_execution_recovery(
        store,
        {"proof": "bound"},
        command_timeout=1.0,
    )
    resources = {"store_started": True, "account_lock_held": True}
    persisted = []

    def sleep(_seconds):
        assert resources == {"store_started": True, "account_lock_held": True}

    outcome = _monitor_recovery(
        store,
        initial,
        tmp_path,
        sleep=sleep,
        persist=lambda value: persisted.append(copy.deepcopy(value)),
    )

    assert outcome["monitor_exit"] == "flat_completed"
    assert outcome["monitor_iterations"] == 2
    assert outcome["completion"]["completed"] is True
    assert outcome["write_actions"] == {"arms": 0, "cancels": 0, "closes": 0}
    assert [event[0] for event in store.events] == [
        "prepare",
        "prepare",
        "prepare",
        "complete",
    ]
    assert any(snapshot["monitor_active"] is True for snapshot in persisted)
    assert persisted[-1]["monitor_active"] is False
    resources.update(store_started=False, account_lock_held=False)
    terminal = runner._terminal_recovery_result(
        outcome,
        run_id="recovery-run",
        identity={"account_fingerprint": "acct_0123456789abcdef", "sdk_profile": "simnow"},
        instrument="SA701",
        output_directory=tmp_path,
    )
    assert terminal["state"] == "STOPPED_FLAT"


def test_flat_completion_failure_keeps_monitoring_until_a_later_sdk_completion(tmp_path):
    class FailFirstCompletionStore(_RecoveryOrchestrationStore):
        def __init__(self, plans):
            super().__init__(plans)
            self.completion_calls = 0

        def complete_execution_recovery(self, *, recovery_token_sha256):
            self.completion_calls += 1
            if self.completion_calls == 1:
                self.events.append(("complete", recovery_token_sha256))
                self.market_data_only = True
                raise RuntimeError("first query barrier failed")
            return super().complete_execution_recovery(recovery_token_sha256=recovery_token_sha256)

    store = FailFirstCompletionStore([_flat_recovery_plan("4" * 64), _flat_recovery_plan("5" * 64)])
    initial = runner._orchestrate_execution_recovery(
        store,
        {"proof": "bound"},
        command_timeout=1.0,
    )
    assert initial["completion"]["completed"] is False

    outcome = _monitor_recovery(store, initial, tmp_path)

    assert outcome["monitor_exit"] == "flat_completed"
    assert outcome["monitor_iterations"] == 1
    assert outcome["completion"]["completed"] is True
    assert store.market_data_only is True
    assert [event[0] for event in store.events] == [
        "prepare",
        "complete",
        "prepare",
        "complete",
    ]
    assert not {"arm", "cancel"} & {event[0] for event in store.events}


def test_signed_operator_takeover_is_bound_to_current_recovery_evidence(monkeypatch, tmp_path):
    key_id = "test-operator-key"
    secret = "test-approval-key-material-at-least-32-bytes"
    monkeypatch.setenv("ITER22_APPROVAL_KEY_ID", key_id)
    monkeypatch.setenv("ITER22_APPROVAL_HMAC_KEY", secret)
    plan = _manual_recovery_plan()
    store = _RecoveryOrchestrationStore([plan])
    initial = runner._orchestrate_execution_recovery(
        store,
        {"proof": "bound"},
        command_timeout=1.0,
    )
    takeover = {
        "schema_version": "backtrader.ctp.operator-takeover.v1",
        "action": "takeover_execution_recovery",
        "approval_key_id": key_id,
        "run_id": "recovery-run",
        "account_fingerprint": "acct_0123456789abcdef",
        "trading_day": "20260910",
        "instrument": "CZCE.SA701",
        "recovery_evidence_sha256": runner._recovery_takeover_scope_sha256(plan),
        "acknowledged_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    canonical = json.dumps(
        takeover,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    takeover["signature_hmac_sha256"] = hmac.new(
        secret.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    (tmp_path / "operator_takeover.json").write_text(json.dumps(takeover), encoding="utf-8")

    outcome = _monitor_recovery(
        store,
        initial,
        tmp_path,
        sleep=lambda _seconds: pytest.fail("verified takeover must exit before another poll"),
    )
    terminal = runner._terminal_recovery_result(
        outcome,
        run_id="recovery-run",
        identity={"account_fingerprint": "acct_0123456789abcdef", "sdk_profile": "simnow"},
        instrument="SA701",
        output_directory=tmp_path,
    )

    assert outcome["monitor_exit"] == "operator_takeover"
    assert outcome["operator_takeover"]["verified"] is True
    assert terminal["state"] == "MANUAL_INTERVENTION"
    assert terminal["state_reason"] == "verified_operator_takeover"
    assert terminal["g4_gate_status"] == "NOT_RUN"
    assert [event[0] for event in store.events] == ["prepare"]


def test_unverified_takeover_does_not_exit_and_sigterm_is_non_pass(monkeypatch, tmp_path):
    monkeypatch.setenv("ITER22_APPROVAL_KEY_ID", "test-operator-key")
    monkeypatch.setenv("ITER22_APPROVAL_HMAC_KEY", "test-approval-key-material-at-least-32-bytes")
    store = _RecoveryOrchestrationStore([_manual_recovery_plan()])
    initial = runner._orchestrate_execution_recovery(
        store,
        {"proof": "bound"},
        command_timeout=1.0,
    )
    (tmp_path / "operator_takeover.json").write_text(
        json.dumps({"signature_hmac_sha256": "0" * 64}), encoding="utf-8"
    )
    state = {"forced": False}

    def sleep(_seconds):
        state["forced"] = True

    outcome = _monitor_recovery(
        store,
        initial,
        tmp_path,
        stop_reason=lambda: "operator_sigterm" if state["forced"] else None,
        sleep=sleep,
    )
    terminal = runner._terminal_recovery_result(
        outcome,
        run_id="recovery-run",
        identity={"account_fingerprint": "acct_0123456789abcdef", "sdk_profile": "simnow"},
        instrument="SA701",
        output_directory=tmp_path,
    )

    assert outcome["monitor_exit"] == "forced_termination"
    assert any(item["event"] == "operator_takeover_rejected" for item in outcome["history"])
    assert terminal["state"] == "MANUAL_INTERVENTION"
    assert terminal["state_reason"] == "operator_sigterm"
    assert terminal["g4_gate_status"] == "NOT_RUN"
    assert not terminal["state"].startswith("PASS")


def test_recovery_cancels_then_rotates_token_before_close_arm():
    first = {
        "status": "RECOVERABLE",
        "execution_cycle_id": "sdk-cycle-1",
        "recovery_token_sha256": "1" * 64,
        "allowed_actions": ["cancel"],
        "allowed_cancels": [{"client_order_id": "old-order"}],
        "allowed_closes": [],
    }
    second = {
        "status": "RECOVERABLE",
        "execution_cycle_id": "sdk-cycle-1",
        "instrument": "CZCE.SA701",
        "recovery_token_sha256": "2" * 64,
        "allowed_actions": ["close"],
        "allowed_cancels": [],
        "allowed_closes": [
            {
                "execution_cycle_id": "sdk-cycle-1",
                "symbol": "SA701",
                "exchange_id": "CZCE",
                "position_side": "long",
                "side": "sell",
                "offset": "close",
                "quantity": "1",
                "quantity_unit": "contracts",
            }
        ],
    }
    store = _RecoveryOrchestrationStore([first, second])

    result = runner._orchestrate_execution_recovery(
        store,
        {"proof": "bound"},
        command_timeout=2.0,
    )

    assert result["plan"] == second
    assert result["armed_for_close"] is True
    assert result["write_actions"] == {"arms": 2, "cancels": 1, "closes": 0}
    assert [event[0] for event in store.events] == [
        "prepare",
        "arm",
        "cancel",
        "wait",
        "prepare",
        "arm",
    ]
    assert store.events[1][1] == "1" * 64
    assert store.events[-1][1] == "2" * 64


def test_recovery_cancel_then_flat_runs_new_token_completion_barrier(tmp_path):
    first = {
        "status": "RECOVERABLE",
        "execution_cycle_id": "sdk-cycle-1",
        "recovery_token_sha256": "1" * 64,
        "allowed_actions": ["cancel"],
        "allowed_cancels": [{"client_order_id": "old-order"}],
        "allowed_closes": [],
    }
    second = _flat_recovery_plan("2" * 64)
    store = _RecoveryOrchestrationStore([first, second])

    outcome = runner._orchestrate_execution_recovery(
        store,
        {"proof": "bound"},
        command_timeout=2.0,
    )
    result = runner._terminal_recovery_result(
        outcome,
        run_id="recovery-run",
        identity={"account_fingerprint": "acct", "sdk_profile": "simnow"},
        instrument="SA701",
        output_directory=tmp_path,
    )

    assert [event[0] for event in store.events] == [
        "prepare",
        "arm",
        "cancel",
        "wait",
        "prepare",
        "complete",
    ]
    assert store.events[-1][1] == "2" * 64
    assert outcome["write_actions"] == {"arms": 1, "cancels": 1, "closes": 0}
    assert result["state"] == "STOPPED_FLAT"
    assert result["execution_recovery"]["completed"] is True


def test_recovery_cancel_refresh_rejects_reused_one_shot_token():
    first = {
        "status": "RECOVERABLE",
        "execution_cycle_id": "sdk-cycle-1",
        "recovery_token_sha256": "1" * 64,
        "allowed_actions": ["cancel"],
        "allowed_cancels": [{"client_order_id": "old-order"}],
        "allowed_closes": [],
    }
    store = _RecoveryOrchestrationStore([first, _flat_recovery_plan("1" * 64)])

    with pytest.raises(runner.PreflightError, match="did not rotate"):
        runner._orchestrate_execution_recovery(
            store,
            {"proof": "bound"},
            command_timeout=2.0,
        )

    assert [event[0] for event in store.events] == [
        "prepare",
        "arm",
        "cancel",
        "wait",
        "prepare",
    ]
    assert store.market_data_only is True


def test_recovery_cancel_refresh_rejects_changed_nonflat_cycle():
    first = {
        "status": "RECOVERABLE",
        "execution_cycle_id": "sdk-cycle-1",
        "recovery_token_sha256": "1" * 64,
        "allowed_actions": ["cancel"],
        "allowed_cancels": [{"client_order_id": "old-order"}],
        "allowed_closes": [],
    }
    second = _strategy_recovery_plan()
    second["execution_cycle_id"] = "sdk-cycle-2"
    second["recovery_token_sha256"] = "2" * 64
    second["allowed_closes"][0]["execution_cycle_id"] = "sdk-cycle-2"
    store = _RecoveryOrchestrationStore([first, second])

    with pytest.raises(runner.PreflightError, match="changed its execution cycle"):
        runner._orchestrate_execution_recovery(
            store,
            {"proof": "bound"},
            command_timeout=2.0,
        )

    assert [event[0] for event in store.events] == [
        "prepare",
        "arm",
        "cancel",
        "wait",
        "prepare",
    ]
    assert store.market_data_only is True


def _strategy_recovery_plan():
    return {
        "status": "RECOVERABLE",
        "can_arm_recovery": True,
        "execution_cycle_id": "sdk-cycle-1",
        "recovery_token_sha256": "3" * 64,
        "allowed_actions": ["close"],
        "instrument": "CZCE.SA701",
        "owned_position": {
            "long_today": "1",
            "long_yesterday": "0",
            "short_today": "0",
            "short_yesterday": "0",
        },
        "allowed_cancels": [],
        "allowed_closes": [
            {
                "execution_cycle_id": "sdk-cycle-1",
                "symbol": "SA701",
                "exchange_id": "CZCE",
                "position_side": "long",
                "side": "sell",
                "offset": "close",
                "quantity": "1",
                "quantity_unit": "contracts",
            }
        ],
    }


def test_czce_recovery_rejects_close_today_before_arming():
    plan = _strategy_recovery_plan()
    plan["allowed_closes"][0]["offset"] = "close_today"
    store = _RecoveryOrchestrationStore([plan])

    with pytest.raises(runner.PreflightError, match="not executable"):
        runner._orchestrate_execution_recovery(
            store,
            {"instrument": "CZCE.SA701"},
            command_timeout=1.0,
        )

    assert [event[0] for event in store.events] == ["prepare"]


def test_restart_enters_sdk_recovery_without_an_entry_order_object():
    plan = _strategy_recovery_plan()
    drains = []
    holder = SimpleNamespace(
        p=SimpleNamespace(
            mode="simnow",
            purpose="engineering_smoke",
            research_status="RESEARCH_NOT_ESTABLISHED",
            lots=1,
            execution_recovery=plan,
            instrument="SA701",
        ),
        broker=SimpleNamespace(get_execution_recovery=lambda: copy.deepcopy(plan)),
        data=SimpleNamespace(_name="SA701"),
        _active_order=None,
        _gross_position_lots=lambda: 1,
        _position_legs=lambda: (1, 0),
        request_drain=lambda reason: drains.append(reason),
        _transition=lambda *_args, **_kwargs: pytest.fail("unexpected transition"),
    )
    holder._bind_startup_recovery = (
        strategy_module.SAMidFrequencyStrategy._bind_startup_recovery.__get__(holder)
    )

    strategy_module.SAMidFrequencyStrategy.start(holder)

    assert drains == ["sdk_owned_startup_recovery"]
    assert holder._active_cycle_id == "sdk-cycle-1"
    assert holder._recovery_allowed_close["offset"] == "close"
    assert holder._active_order is None


class _TerminalRecoveryOrder:
    Partial = 3
    Completed = 4

    def __init__(self):
        self.ref = 41
        self.size = -1
        self.status = self.Completed
        self.executed = SimpleNamespace(size=-1, price=1500.0, comm=4.0)
        self.info = {
            "execution_cycle_id": "sdk-cycle-1",
            "offset": "close",
            "exchange_id": "CZCE",
        }

    def getstatusname(self):
        return "Completed"

    def alive(self):
        return False


def _recovery_completion_strategy_holder():
    callbacks = []
    stopped = []
    order = _TerminalRecoveryOrder()

    def request(callback, *, recovery_token_sha256):
        callbacks.append((callback, recovery_token_sha256))
        return {"queued": True}

    holder = SimpleNamespace(
        p=SimpleNamespace(
            account_fingerprint="acct_0123456789abcdef",
            trading_day="20260909",
            connection_generation=7,
            instrument="SA701",
            mode="simnow",
            maximum_intent_age_seconds=1.0,
        ),
        broker=SimpleNamespace(request_execution_recovery_completion=request),
        data=SimpleNamespace(_name="SA701"),
        env=SimpleNamespace(runstop=lambda: stopped.append(True)),
        state="EXIT_PENDING",
        state_reason="",
        _order_roles={order.ref: "recovery_exit"},
        _order_cycles={order.ref: "sdk-cycle-1"},
        _orders=[],
        _record=lambda *_args, **_kwargs: None,
        _fill_bounds=None,
        _order_terminal_refs=set(),
        _active_order=order,
        _gross_position_lots=lambda: 0,
        _recovery_plan=_strategy_recovery_plan(),
        _recovery_completion=None,
        _reconciliation_phase=None,
        _reconciliation_started=None,
        _clock=SimpleNamespace(monotonic_now=lambda: 100.0),
        deadline=SimpleNamespace(confirmed_terminal=lambda: None),
    )

    def transition(state, reason, now=None):
        holder.state = state
        holder.state_reason = reason

    holder._transition = transition
    holder._begin_execution_recovery_completion = (
        strategy_module.SAMidFrequencyStrategy._begin_execution_recovery_completion.__get__(holder)
    )
    holder.notify_execution_recovery_completion = (
        strategy_module.SAMidFrequencyStrategy.notify_execution_recovery_completion.__get__(holder)
    )
    return holder, order, callbacks, stopped


def test_recovery_order_completion_reaches_stopped_flat_without_a_g4_cycle():
    holder, order, callbacks, stopped = _recovery_completion_strategy_holder()

    strategy_module.SAMidFrequencyStrategy.notify_order(holder, order)

    assert holder.state == "RECOVERING"
    assert callbacks[0][1] == "3" * 64
    assert holder._orders[-1]["role"] == "recovery_exit"
    assert holder._orders[-1]["normal_cycle"] is False
    callback = callbacks[0][0]
    assert callback({"completed": True, "status": "completed", "error_code": None}) is True
    assert holder.state == "STOPPED_FLAT"
    assert holder._recovery_completion["completed"] is True
    assert stopped == [True]


def test_unproven_recovery_completion_stays_manual_and_blocks_future_entry():
    holder, order, callbacks, stopped = _recovery_completion_strategy_holder()
    strategy_module.SAMidFrequencyStrategy.notify_order(holder, order)
    callback = callbacks[0][0]

    assert (
        callback(
            {
                "completed": False,
                "status": "failed",
                "error_code": "recovery_completion_unproven",
            }
        )
        is False
    )
    reservations = []
    holder._active_order = None
    holder._reserve = lambda **kwargs: reservations.append(kwargs) or True
    strategy_module.SAMidFrequencyStrategy._submit_entry(
        holder,
        1,
        SimpleNamespace(recv_monotonic=100.0),
        "decision-v1",
    )
    assert holder.state == "MANUAL_INTERVENTION"
    assert reservations == []
    assert stopped == []


def test_recovery_cannot_transition_stopped_flat_without_exact_sdk_completion():
    aborts = []
    holder = SimpleNamespace(
        _recovery_only=True,
        _recovery_completion=None,
        broker=SimpleNamespace(abort_execution_recovery=lambda reason: aborts.append(reason)),
        _state_history=[],
        _record=lambda *_args, **_kwargs: None,
    )

    strategy_module.SAMidFrequencyStrategy._transition(
        holder, "STOPPED_FLAT", "drain_reconciled_flat", 10.0
    )

    assert holder.state == "MANUAL_INTERVENTION"
    assert holder.state_reason == "sdk_recovery_completion_required"
    assert aborts == ["strategy_sdk_recovery_completion_required"]


def test_recovery_exit_deadline_aborts_without_generic_cancel():
    aborts = []
    cancels = []
    reconciliations = []
    order = SimpleNamespace(ref=81)
    holder = SimpleNamespace(
        p=SimpleNamespace(runtime_control=None, run_deadline_monotonic=None),
        broker=SimpleNamespace(abort_execution_recovery=lambda reason: aborts.append(reason)),
        state="EXIT_PENDING",
        state_reason="",
        _active_order=order,
        _recovery_only=True,
        _recovery_completion=None,
        _order_roles={order.ref: "recovery_exit"},
        _state_history=[],
        _record=lambda *_args, **_kwargs: None,
        _request_reconciliation=lambda now: reconciliations.append(now),
        cancel=lambda candidate: cancels.append(candidate),
        deadline=SimpleNamespace(action=lambda now: "cancel"),
    )
    holder._transition = strategy_module.SAMidFrequencyStrategy._transition.__get__(holder)
    holder._enter_manual_monitor = (
        strategy_module.SAMidFrequencyStrategy._enter_manual_monitor.__get__(holder)
    )

    strategy_module.SAMidFrequencyStrategy._advance_time(holder, 20.0)

    assert holder.state == "MANUAL_INTERVENTION"
    assert holder.state_reason == "recovery_exit_deadline_requires_new_plan"
    assert aborts == ["strategy_recovery_exit_deadline_requires_new_plan"]
    assert cancels == []
    assert reconciliations == [20.0]


def test_recovery_final_report_is_excluded_from_g4_normal_cycle_accounting():
    raw = {
        "state": "STOPPED_FLAT",
        "position_lots": 0,
        "unknown_intents": 0,
        "active_order": None,
        "orders": [
            {"ref": 41, "role": "recovery_exit", "status": "Submitted"},
            {"ref": 41, "role": "recovery_exit", "status": "Completed"},
        ],
        "execution_recovery": {
            "recovery_only": True,
            "status": "RECOVERABLE",
            "completed": True,
        },
    }
    outcome = {
        "history": [{"event": "prepare"}, {"event": "arm"}],
        "write_actions": {"arms": 1, "cancels": 0, "closes": 0},
    }

    finalized, recovery = runner._finalize_recovery_runtime_result(raw, outcome)

    assert finalized["g4_gate_status"] == "NOT_RUN"
    assert finalized["g4_checks"] == {}
    assert finalized["actual_closed_cycles"] == 0
    assert recovery["normal_closed_cycles"] == 0
    assert recovery["write_actions"] == {"arms": 1, "cancels": 0, "closes": 1}
    shutdown = {
        "status": "PASS",
        "remote_flat_proven": True,
        "store_shutdown_state": "PASS",
        "active_order_count": 0,
        "local_position_count": 0,
        "remote_position_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
    }
    assert runner._report_stopped_flat(finalized, shutdown) is True

    invalid = copy.deepcopy(raw)
    invalid["orders"].append({"ref": 42, "role": "entry"})
    with pytest.raises(RuntimeError, match="normal cycle order"):
        runner._finalize_recovery_runtime_result(invalid, outcome)


def test_no_production_or_credential_material_appears_in_example_sources():
    config_text = (EXAMPLE / "config.yaml").read_text(encoding="utf-8")
    assert "production" not in config_text.lower()
    assert "182.254.243.31" not in config_text
    for filename in ("config.yaml", "README.md"):
        text = (EXAMPLE / filename).read_text(encoding="utf-8")
        assert "preferred" not in text
        assert "secret-1" not in text
