"""S-12 acceptance tests: all 22 examples/live/007_ctp dual-mode templates and Runtime CLI contract (T-041/T-042).

Evidence level: UNIT + STATIC + CLI_DRY_RUN (zero network calls, zero real accounts).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from backtrader.brokers.base_btapi_broker import normalize_shutdown_summary
from backtrader.live_trading.run_status import (
    EXIT_BLOCKED,
    EXIT_STOPPED,
    EXIT_STOPPED_WITH_WORKING_ORDERS,
    EXIT_STOPPED_WITH_WRITE_IN_FLIGHT,
    EXIT_UNEXPECTED,
    exit_code_for,
)
from backtrader.stores import LiveCompositionError, validate_live_config

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_007 = REPO_ROOT / "examples/live/007_ctp"


def _load_gateway_runner_module():
    runner_path = EXAMPLES_007 / "gateway_client_runner.py"
    spec = importlib.util.spec_from_file_location("gateway_client_runner_s12", runner_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_s12_all_22_007_ctp_templates_declare_explicit_mode_and_validate():
    cfg_paths = sorted(EXAMPLES_007.glob("*/config.yaml"))
    assert len(cfg_paths) == 22

    direct_names = []
    gateway_names = []
    runner = _load_gateway_runner_module()

    for cfg_path in cfg_paths:
        name = cfg_path.parent.name
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8-sig"))
        assert isinstance(raw, dict), name
        if name.endswith("_direct"):
            assert raw.get("mode") == "direct", f"{name} must declare mode: direct"
            validated = validate_live_config(raw)
            assert validated["mode"] == "direct"
            direct_names.append(name)
        elif name.endswith("_gateway"):
            assert raw.get("mode") == "gateway", f"{name} must declare mode: gateway"
            validated = validate_live_config(raw)
            assert validated["mode"] == "gateway"
            # Strict Gateway invariants (D62S-03, D62S-04, D62S-05)
            gw = raw["gateway_strategy"]
            assert isinstance(gw["risk"], dict)
            assert isinstance(gw["execution"], dict)
            assert "direct.reserve" not in gw["requested_operations"]
            assert "direct.dispatch" not in gw["requested_operations"]
            assert "direct.delegated_cancel" in gw["requested_operations"]
            parsed = runner.validate_config(raw)
            assert parsed.exchange_name == "CTP___FUTURE"
            gateway_names.append(name)
        else:
            raise AssertionError(f"Unexpected 007_ctp directory name: {name}")

    assert len(direct_names) == 11
    assert len(gateway_names) == 11


def test_s12_gateway_runner_rejects_missing_mode_and_delegates_shutdown_summary():
    runner = _load_gateway_runner_module()
    raw = yaml.safe_load((EXAMPLES_007 / "sa_dual_ma_gateway/config.yaml").read_text(encoding="utf-8-sig"))

    # Missing mode rejected
    no_mode = {k: v for k, v in raw.items() if k != "mode"}
    with pytest.raises(ValueError, match="GATEWAY_MODE_REQUIRED"):
        runner.validate_config(no_mode)

    # Top-level execution rejected with dedicated error type
    with_exec = dict(raw, execution={"routing": {}})
    with pytest.raises(runner.GatewayExecutionConfigUnsupported):
        runner.validate_config(with_exec)

    # Direct config rejected by validate_live_config when mode swapped
    swapped = dict(raw, mode="direct")
    with pytest.raises(LiveCompositionError) as exc:
        validate_live_config(swapped)
    assert exc.value.code == "MODE_CONFLICT"

    # contract_broker_summary delegates identically to product normalize_shutdown_summary
    for sample in (
        {"status": "PASS", "gateway_working_orders": {"unresolved_working_orders": 0}},
        {"status": "PASS", "gateway_working_orders": {"unresolved_working_orders": 3}},
        {"status": "INCOMPLETE", "gateway_working_orders": {"unresolved_working_orders": 0}},
        {
            "status": "OBSERVATION_ONLY",
            "market_data_only": True,
            "active_order_count": 0,
            "gateway_working_orders": {"unresolved_working_orders": 0},
        },
    ):
        assert runner.contract_broker_summary(sample) == normalize_shutdown_summary(
            sample, mode="gateway"
        )


def test_s12_direct_and_gateway_dry_run_cli_and_runtime_supervision_contract(tmp_path):
    sub_env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    # 1. Gateway runner --dry-run succeeds offline with exit code 0
    gw_res = subprocess.run(
        [sys.executable, str(EXAMPLES_007 / "sa_dual_ma_gateway/run.py"), "--dry-run"],
        cwd=REPO_ROOT,
        env=sub_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert gw_res.returncode == 0, gw_res.stdout + gw_res.stderr
    gw_body = json.loads(gw_res.stdout.strip().splitlines()[-1])
    assert gw_body["status"] == "PASS"

    # 2. Direct runner --dry-run succeeds offline with exit code 0
    dir_res = subprocess.run(
        [sys.executable, str(EXAMPLES_007 / "sa_dual_ma_direct/run.py"), "--dry-run"],
        cwd=REPO_ROOT,
        env=sub_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert dir_res.returncode == 0, dir_res.stdout + dir_res.stderr

    # 3. Gateway runner rejects missing mode with exit code 2 (BLOCKED)
    raw_gw = yaml.safe_load(
        (EXAMPLES_007 / "sa_dual_ma_gateway/config.yaml").read_text(encoding="utf-8-sig")
    )
    raw_gw.pop("mode", None)
    bad_cfg = tmp_path / "no_mode.yaml"
    bad_cfg.write_text(yaml.safe_dump(raw_gw, sort_keys=False), encoding="utf-8")
    blocked_res = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES_007 / "sa_dual_ma_gateway/run.py"),
            "--config",
            str(bad_cfg),
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        env=sub_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert blocked_res.returncode == EXIT_BLOCKED == 2
    assert json.loads(blocked_res.stdout.strip().splitlines()[-1])["status"] == "BLOCKED"

    # 4. Runtime CLI flags (--run-id, --heartbeat-interval, --stop-request-file) accepted on --help
    help_res = subprocess.run(
        [sys.executable, str(EXAMPLES_007 / "sa_dual_ma_gateway/run.py"), "--help"],
        cwd=REPO_ROOT,
        env=sub_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert help_res.returncode == 0
    for flag in ("--run-id", "--heartbeat-interval", "--stop-request-file"):
        assert flag in help_res.stdout

    # 5. Canonical exit code mapping preserved (0/1/2/3/4)
    assert exit_code_for("STOPPED") == EXIT_STOPPED == 0
    assert exit_code_for("UNKNOWN") == EXIT_UNEXPECTED == 1
    assert exit_code_for("BLOCKED") == EXIT_BLOCKED == 2
    assert exit_code_for("STOPPED_WITH_WORKING_ORDERS") == EXIT_STOPPED_WITH_WORKING_ORDERS == 3
    assert exit_code_for("STOPPED_WITH_WRITE_IN_FLIGHT") == EXIT_STOPPED_WITH_WRITE_IN_FLIGHT == 4
