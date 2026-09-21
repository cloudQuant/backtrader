"""Focused offline tests for the Iteration 22 admission receipt tool."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "013_3_sa_midfreq_simnow"
PACKAGE = "iter22_admission_receipt_tool_example"


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
runner = importlib.import_module(f"{PACKAGE}.run")
tool = importlib.import_module(f"{PACKAGE}.admission_receipt_tool")


def _write_admitted_config(tmp_path: Path, *, research_status: str = "RESEARCH_ADMITTED") -> Path:
    """Create an isolated valid config with a hash-bound local calendar."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    config = copy.deepcopy(runner.load_config(EXAMPLE / "config.yaml")[0])
    calendar = {
        "schema_version": "iter22.czce-trading-calendar.v1",
        "exchange": "CZCE",
        "source": "unit-test-calendar",
        "as_of_utc": "2026-09-20T00:00:00Z",
        "trading_days": ["20260921", "20260922", "20260923", "20260924"],
    }
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps(calendar), encoding="utf-8")
    config["trading_calendar"] = {
        "artifact": str(calendar_path),
        "sha256": runner.sha256_file(calendar_path),
    }
    config["research"] = {"status": research_status}
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path


def _facts(config: dict, *, purpose: str = "natural_signal") -> dict:
    """Return complete non-secret runtime/evidence facts for one receipt request."""

    now = datetime.now(timezone.utc)
    evidence = {
        "gates": {"G1": "PASS", "G2": "PASS", "G3": "PASS"},
        "evidence_hashes": {"G1": "a" * 64, "G2": "b" * 64, "G3": "c" * 64},
        "session_calendar_sha256": config["trading_calendar"]["sha256"],
        "signal_preregistration_sha256": "d" * 64 if purpose == "natural_signal" else None,
        "engineering_trigger": None,
    }
    if purpose == "engineering_smoke":
        evidence["engineering_trigger"] = {
            "trigger_id": "unit-trigger-1",
            "instrument": "SA701",
            "trading_day": "20260921",
            "side": "long",
            "not_before_utc": (now - timedelta(minutes=2)).isoformat(),
            "not_after_utc": (now + timedelta(minutes=2)).isoformat(),
            "minimum_ingest_seq": 11,
        }
    return {
        "schema_version": tool.FACTS_SCHEMA,
        "request_id": "unit-request-1",
        "purpose": purpose,
        "issued_at_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_at_utc": (now + timedelta(minutes=30)).isoformat(),
        "limits": {
            "maximum_lots": 1,
            "maximum_write_requests": 10,
            "remaining_smoke_attempts": 0 if purpose == "natural_signal" else 1,
        },
        "runtime": {
            "account_fingerprint": "acct_0123456789abcdef",
            "trading_day": "20260921",
            "instrument": "SA701",
            "connection_generation": 7,
            "environment_profile": config["environment"],
            "native_sha256": "e" * 64,
            "ctp_package_sha256": "f" * 64,
            "preflight_sha256": "1" * 64,
            "stage_a_snapshot_sha256": "2" * 64,
            "stage_b_snapshot_sha256": "3" * 64,
            "stage_a_query_request_ids": {"account": 11, "positions": 12},
            "stage_b_query_request_ids": {"account": 21, "fees": 22, "margin": 23},
        },
        "evidence": evidence,
        "reviewer": {"id": "unit-reviewer", "approval_sha256": "4" * 64},
    }


def test_build_request_is_offline_and_binds_full_runtime_evidence(tmp_path, monkeypatch):
    config = tool.load_config(_write_admitted_config(tmp_path))
    facts = _facts(config)
    monkeypatch.setattr(
        runner,
        "BtApiStore",
        lambda *_args, **_kwargs: pytest.fail("receipt tool must not construct a Store"),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: pytest.fail("receipt tool must not access a network"),
    )

    request = tool.build_request(facts, config)

    assert request["schema_version"] == tool.REQUEST_SCHEMA
    assert "signature_hmac_sha256" not in request["unsigned_receipt"]
    assert request["unsigned_receipt"]["runtime_evidence"] == facts["runtime"]
    binding = request["unsigned_receipt"]["request_binding"]
    assert binding["config_hash"] == runner.config_hash(config)
    assert binding["code_hash"] == runner.code_hash()
    assert binding["facts_sha256"] == tool._sha256_json(request["facts"])


def test_natural_signal_request_rejects_non_admitted_config():
    config = tool.load_config(EXAMPLE / "config.yaml")

    with pytest.raises(tool.ReceiptToolError, match="natural_signal_requires_research_admitted"):
        tool.build_request(_facts(config), config)


def test_request_rejects_stale_calendar_artifact_and_long_or_future_validity(tmp_path):
    config_path = _write_admitted_config(tmp_path)
    config = tool.load_config(config_path)
    calendar_path = Path(config["trading_calendar"]["artifact"])
    calendar_path.unlink()
    with pytest.raises(tool.ReceiptToolError, match="calendar_artifact_unavailable_or_invalid"):
        tool.build_request(_facts(config), config)

    config_path = _write_admitted_config(tmp_path / "valid-calendar")
    config = tool.load_config(config_path)
    now = datetime.now(timezone.utc)
    long_lived = _facts(config)
    long_lived["issued_at_utc"] = (now - timedelta(minutes=1)).isoformat()
    long_lived["expires_at_utc"] = (now + timedelta(hours=2, minutes=1)).isoformat()
    with pytest.raises(tool.ReceiptToolError, match="receipt_ttl_exceeds_two_hours"):
        tool.build_request(long_lived, config)

    future_issued = _facts(config)
    future_issued["issued_at_utc"] = (now + timedelta(minutes=1)).isoformat()
    future_issued["expires_at_utc"] = (now + timedelta(minutes=31)).isoformat()
    with pytest.raises(tool.ReceiptToolError, match="receipt_validity_invalid"):
        tool.build_request(future_issued, config)


def test_cli_requires_explicit_signing_trust_root_and_validates_runner_contract(
    tmp_path, monkeypatch, capsys
):
    config_path = _write_admitted_config(tmp_path)
    config = tool.load_config(config_path)
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_facts(config)), encoding="utf-8")
    request_path = tmp_path / "request.json"
    receipt_path = tmp_path / "receipt.json"
    secret = "approval-secret-never-print-this-value-0123456789"

    assert (
        tool.main(
            [
                "--input",
                str(facts_path),
                "--config",
                str(config_path),
                "--output",
                str(request_path),
            ]
        )
        == 0
    )
    request_stdout = capsys.readouterr()
    assert secret not in request_stdout.out + request_stdout.err
    assert "REQUEST_WRITTEN" in request_stdout.out
    assert request_path.is_file()

    assert (
        tool.main(
            [
                "--request",
                str(request_path),
                "--config",
                str(config_path),
                "--output",
                str(receipt_path),
            ]
        )
        == 2
    )
    unsigned_result = capsys.readouterr()
    assert "sign_flag_required" in unsigned_result.err
    assert not receipt_path.exists()

    monkeypatch.setenv("ITER22_APPROVAL_KEY_ID", "unit-operator-key")
    monkeypatch.setenv("ITER22_APPROVAL_HMAC_KEY", secret)
    assert (
        tool.main(
            [
                "--request",
                str(request_path),
                "--config",
                str(config_path),
                "--output",
                str(receipt_path),
                "--sign",
            ]
        )
        == 0
    )
    signing_result = capsys.readouterr()
    assert secret not in signing_result.out + signing_result.err
    assert "RECEIPT_SIGNED_AND_VALIDATED" in signing_result.out
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["approval_key_id"] == "unit-operator-key"
    assert secret not in receipt_path.read_text(encoding="utf-8")
    validated = runner.validate_receipt(
        receipt_path,
        config=config,
        mode="simnow",
        purpose="natural_signal",
    )
    assert validated.validated is True


def test_signing_without_existing_trust_root_does_not_publish_receipt(
    tmp_path, monkeypatch, capsys
):
    config_path = _write_admitted_config(tmp_path)
    config = tool.load_config(config_path)
    facts_path = tmp_path / "facts.json"
    facts_path.write_text(json.dumps(_facts(config)), encoding="utf-8")
    request_path = tmp_path / "request.json"
    receipt_path = tmp_path / "receipt.json"
    assert (
        tool.main(
            [
                "--input",
                str(facts_path),
                "--config",
                str(config_path),
                "--output",
                str(request_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    monkeypatch.delenv("ITER22_APPROVAL_KEY_ID", raising=False)
    monkeypatch.delenv("ITER22_APPROVAL_HMAC_KEY", raising=False)
    assert (
        tool.main(
            [
                "--request",
                str(request_path),
                "--config",
                str(config_path),
                "--output",
                str(receipt_path),
                "--sign",
            ]
        )
        == 2
    )
    result = capsys.readouterr()
    assert "approval_trust_root_unavailable" in result.err
    assert not receipt_path.exists()
