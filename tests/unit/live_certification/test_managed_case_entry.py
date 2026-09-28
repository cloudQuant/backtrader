"""Offline contracts for the staged 007 managed certification entrypoint."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Optional

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = (
    REPOSITORY_ROOT
    / "examples"
    / "007_ctp"
    / "live_certification"
    / "simnow_penetration"
    / "managed_case_entry.py"
)


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "iteration41_007_managed_case_entry_test", ENTRYPOINT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_staged_case(
    root: Path, case_id: str = "T01", config: Optional[str] = None
):
    case_dir = root / case_id
    case_dir.mkdir(parents=True)
    run_path = case_dir / "run.py"
    run_path.write_text(
        "from managed_case_entry import main\n"
        f"raise SystemExit(main({case_id!r}, __file__))\n",
        encoding="utf-8",
    )
    if config is None:
        config = (
            "config_schema_version: 4\n"
            "strategy:\n"
            f"  id: example.007_ctp.simnow_penetration.{case_id}\n"
            "runtime:\n"
            "  mode: simulation\n"
            "  preset: sandbox\n"
            "parameters:\n"
            f"  scenario: {case_id}\n"
        )
    (case_dir / "config.yaml").write_text(config, encoding="utf-8")
    return run_path


def _prepare_entrypoint(tmp_path, monkeypatch):
    module = _load_entrypoint()
    cases_root = tmp_path / "cases"
    cases_root.mkdir()
    monkeypatch.setattr(module, "_CASES_ROOT", cases_root)
    return module, cases_root


def test_valid_case_mapping_and_exact_config_stay_blocked(tmp_path, monkeypatch, capsys):
    module, cases_root = _prepare_entrypoint(tmp_path, monkeypatch)
    run_path = _write_staged_case(cases_root)
    modules_before = set(sys.modules)

    exit_code = module.main("T01", str(run_path))

    output = capsys.readouterr().out
    result = json.loads(output)
    assert exit_code == 2
    assert result == {
        "case_id": "T01",
        "evidence_boundary": "STAGING_ONLY_NOT_AUTHORITY",
        "external_request_counts": {"network": 0, "order_write": 0},
        "reason": "managed_ctp_certification_not_registered",
        "scenario_id": "TRADE-OPEN-01",
        "status": "BLOCKED",
    }
    assert result["status"] != "PASS"
    new_modules = set(sys.modules) - modules_before
    assert not any(name.split(".")[0] == "backtrader" for name in new_modules)
    assert not any(
        name.split(".")[0] in {"bt_api_py", "ctpbeebt"}
        for name in new_modules
    )


def test_all_33_code_owned_ids_pass_structure_and_remain_blocked(
    tmp_path, monkeypatch, capsys
):
    module, cases_root = _prepare_entrypoint(tmp_path, monkeypatch)
    scenarios = module._load_code_owned_scenarios()

    assert len(scenarios) == 33
    for case_id, scenario in scenarios.items():
        run_path = _write_staged_case(cases_root, case_id=case_id)
        exit_code = module.main(case_id, str(run_path))
        result = json.loads(capsys.readouterr().out)
        assert exit_code == 2
        assert result["status"] == "BLOCKED"
        assert result["reason"] == "managed_ctp_certification_not_registered"
        assert result["case_id"] == case_id
        assert result["scenario_id"] == scenario.scenario_id
        assert result["external_request_counts"] == {"network": 0, "order_write": 0}


@pytest.mark.parametrize(
    ("case_id", "config", "expected_reason"),
    (
        (
            "T01",
            "config_schema_version: 4\n"
            "strategy:\n"
            "  id: example.007_ctp.simnow_penetration.T01\n"
            "runtime:\n"
            "  mode: simulation\n"
            "  preset: sandbox\n"
            "parameters:\n"
            "  scenario: T01\n"
            "ctp:\n"
            "  password: never-print-this\n",
            "managed_ctp_certification_config_invalid",
        ),
        (
            "T01",
            "config_schema_version: 4\n"
            "strategy:\n"
            "  id: example.007_ctp.simnow_penetration.T01\n"
            "runtime:\n"
            "  mode: simulation\n"
            "  preset: sandbox\n"
            "parameters:\n"
            "  scenario: T01\n"
            "secrets_ref: runtime_secrets\n",
            "managed_ctp_certification_config_invalid",
        ),
        (
            "T01",
            "config_schema_version: 4\n"
            "strategy:\n"
            "  id: example.007_ctp.simnow_penetration.T01\n"
            "runtime:\n"
            "  mode: simulation\n"
            "  preset: sandbox\n"
            "parameters:\n"
            "  scenario: T01\n"
            "secrets_ref: none\n",
            "managed_ctp_certification_not_registered",
        ),
        (
            "T01",
            "config_schema_version: 4\n"
            "strategy:\n"
            "  id: example.007_ctp.simnow_penetration.T01\n"
            "runtime:\n"
            "  mode: simulation\n"
            "  preset: sandbox\n"
            "parameters:\n"
            "  scenario: T01\n"
            "  scenario: T02\n",
            "managed_ctp_certification_config_invalid",
        ),
        (
            "NOT_A_CASE",
            "config_schema_version: 4\n",
            "managed_ctp_certification_case_id_invalid",
        ),
    ),
)
def test_invalid_scope_or_config_is_redacted_and_blocked(
    tmp_path, monkeypatch, capsys, case_id, config, expected_reason
):
    module, cases_root = _prepare_entrypoint(tmp_path, monkeypatch)
    run_path = _write_staged_case(cases_root, case_id="T01", config=config)

    exit_code = module.main(case_id, str(run_path))

    output = capsys.readouterr().out
    result = json.loads(output)
    assert exit_code == 2
    assert result["status"] == "BLOCKED"
    assert result["reason"] == expected_reason
    assert result["external_request_counts"] == {"network": 0, "order_write": 0}
    assert "never-print-this" not in output


def test_wrong_direct_path_is_rejected_before_reading_its_config(
    tmp_path, monkeypatch, capsys
):
    module, cases_root = _prepare_entrypoint(tmp_path, monkeypatch)
    run_path = _write_staged_case(cases_root)
    copied_path = cases_root.parent / "copy" / "run.py"
    copied_path.parent.mkdir()
    copied_path.write_text("raise AssertionError('must not execute')\n", encoding="utf-8")

    exit_code = module.main("T01", str(copied_path))

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "managed_ctp_certification_path_invalid"
    assert "case_id" in result and result["case_id"] == "T01"
    assert not (copied_path.parent / "config.yaml").exists()
    assert run_path.exists()
