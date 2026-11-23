"""S-12 acceptance tests: split 007_ctp_direct and 007_ctp_gateway templates and Runtime CLI contract (T-041/T-042).

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
EXAMPLES_007_DIRECT = REPO_ROOT / "examples/live/007_ctp_direct"
EXAMPLES_007_GATEWAY = REPO_ROOT / "examples/live/007_ctp_gateway"


def _load_gateway_runner_module():
    runner_path = EXAMPLES_007_GATEWAY / "gateway_client_runner.py"
    spec = importlib.util.spec_from_file_location("gateway_client_runner_s12", runner_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_s12_all_22_007_ctp_templates_declare_explicit_mode_and_validate():
    assert not (REPO_ROOT / "examples/live/007_ctp").exists()
    direct_cfgs = sorted(EXAMPLES_007_DIRECT.glob("*/config.yaml"))
    gateway_cfgs = sorted(EXAMPLES_007_GATEWAY.glob("*/config.yaml"))
    assert len(direct_cfgs) == 11
    assert len(gateway_cfgs) == 11

    runner = _load_gateway_runner_module()

    for cfg_path in direct_cfgs:
        name = cfg_path.parent.name
        assert name.endswith("_direct"), f"Non-direct folder inside 007_ctp_direct: {name}"
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8-sig"))
        assert isinstance(raw, dict), name
        assert raw.get("mode") == "direct", f"{name} must declare mode: direct"
        validated = validate_live_config(raw)
        assert validated["mode"] == "direct"
        run_src = (cfg_path.parent / "run.py").read_text(encoding="utf-8")
        assert "create_direct_store" in run_src, f"{name}/run.py must use create_direct_store"

    for cfg_path in gateway_cfgs:
        name = cfg_path.parent.name
        assert name.endswith("_gateway"), f"Non-gateway folder inside 007_ctp_gateway: {name}"
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8-sig"))
        assert isinstance(raw, dict), name
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


def test_s12_gateway_runner_rejects_missing_mode_and_delegates_shutdown_summary():
    runner = _load_gateway_runner_module()
    raw = yaml.safe_load(
        (EXAMPLES_007_GATEWAY / "sa_dual_ma_gateway/config.yaml").read_text(encoding="utf-8-sig")
    )

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

    # Direct NOT_STARTED summary preserved for write-free start abort mapping
    not_started = {"status": "NOT_STARTED", "reason": "stop_requested_during_start"}
    assert normalize_shutdown_summary(not_started, mode="direct")["status"] == "NOT_STARTED"


def test_s12_direct_and_gateway_dry_run_cli_and_runtime_supervision_contract(tmp_path):
    sub_env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    # 1. Gateway runner --dry-run succeeds offline with exit code 0
    gw_res = subprocess.run(
        [sys.executable, str(EXAMPLES_007_GATEWAY / "sa_dual_ma_gateway/run.py"), "--dry-run"],
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
        [sys.executable, str(EXAMPLES_007_DIRECT / "sa_dual_ma_direct/run.py"), "--dry-run"],
        cwd=REPO_ROOT,
        env=sub_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert dir_res.returncode == 0, dir_res.stdout + dir_res.stderr

    # 3. Direct runner rejects missing mode with exit code 2 (BLOCKED)
    raw_dir = yaml.safe_load(
        (EXAMPLES_007_DIRECT / "sa_dual_ma_direct/config.yaml").read_text(encoding="utf-8-sig")
    )
    raw_dir.pop("mode", None)
    bad_dir_cfg = tmp_path / "direct_no_mode.yaml"
    bad_dir_cfg.write_text(yaml.safe_dump(raw_dir, sort_keys=False), encoding="utf-8")
    blocked_dir = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES_007_DIRECT / "sa_dual_ma_direct/run.py"),
            "--config",
            str(bad_dir_cfg),
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        env=sub_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert blocked_dir.returncode == EXIT_BLOCKED == 2

    # 4. Gateway runner rejects missing mode with exit code 2 (BLOCKED)
    raw_gw = yaml.safe_load(
        (EXAMPLES_007_GATEWAY / "sa_dual_ma_gateway/config.yaml").read_text(encoding="utf-8-sig")
    )
    raw_gw.pop("mode", None)
    bad_cfg = tmp_path / "no_mode.yaml"
    bad_cfg.write_text(yaml.safe_dump(raw_gw, sort_keys=False), encoding="utf-8")
    blocked_res = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES_007_GATEWAY / "sa_dual_ma_gateway/run.py"),
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

    # 5. Runtime CLI flags (--run-id, --heartbeat-interval, --stop-request-file) accepted on --help
    help_res = subprocess.run(
        [sys.executable, str(EXAMPLES_007_GATEWAY / "sa_dual_ma_gateway/run.py"), "--help"],
        cwd=REPO_ROOT,
        env=sub_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert help_res.returncode == 0
    for flag in ("--run-id", "--heartbeat-interval", "--stop-request-file"):
        assert flag in help_res.stdout

    # 6. Canonical exit code mapping preserved (0/1/2/3/4)
    assert exit_code_for("STOPPED") == EXIT_STOPPED == 0
    assert exit_code_for("UNKNOWN") == EXIT_UNEXPECTED == 1
    assert exit_code_for("BLOCKED") == EXIT_BLOCKED == 2
    assert exit_code_for("STOPPED_WITH_WORKING_ORDERS") == EXIT_STOPPED_WITH_WORKING_ORDERS == 3
    assert exit_code_for("STOPPED_WITH_WRITE_IN_FLIGHT") == EXIT_STOPPED_WITH_WRITE_IN_FLIGHT == 4


def test_s12_all_11_direct_templates_compose_strict_direct_stack():
    import backtrader as bt
    from backtrader.brokers.direct_btapi_broker import DirectBtApiBroker
    from backtrader.feeds.direct_btapi_feed import DirectBtApiFeed
    from backtrader.stores.btapi_composition import ProcessModeFence
    from backtrader.stores.direct_btapi_store import DirectBtApiStore

    direct_dirs = sorted(
        p for p in EXAMPLES_007_DIRECT.iterdir() if p.is_dir() and p.name.endswith("_direct")
    )
    assert len(direct_dirs) == 11

    added_paths = []
    if str(EXAMPLES_007_DIRECT) not in sys.path:
        sys.path.insert(0, str(EXAMPLES_007_DIRECT))
        added_paths.append(str(EXAMPLES_007_DIRECT))

    try:
        for idx, strat_dir in enumerate(direct_dirs):
            ProcessModeFence._reset_for_tests()
            strat_dir_str = str(strat_dir)
            if strat_dir_str not in sys.path:
                sys.path.insert(0, strat_dir_str)
                added_paths.append(strat_dir_str)
            spec = importlib.util.spec_from_file_location(
                f"direct_template_s12_{idx}", strat_dir / "run.py"
            )
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            cfg, cfg_path = mod.load_config("config.yaml", strat_dir, "config.yaml")
            symbols = mod.validate_live_config(cfg)
            store = mod.create_store(cfg, {"user_id": "u", "password": "p"}, cfg_path)
            assert isinstance(store, DirectBtApiStore), strat_dir.name
            assert store.run_binding is not None and store.run_binding.mode == "direct"
            assert store.run_binding.route == "CTP___FUTURE"

            broker = mod.create_broker(store, cfg, first_init=True)
            assert isinstance(broker, DirectBtApiBroker), strat_dir.name
            assert broker.run_binding.matches(store.run_binding)

            cerebro = bt.Cerebro(stdstats=False)
            cerebro.setbroker(broker)
            fc = mod.check_direct_feed_scope(cfg, symbols=symbols, route="CTP___FUTURE")
            feeds = mod.add_feeds(cerebro, store, cfg, fc.scopes)
            assert len(feeds) == len(symbols)
            for feed in feeds:
                assert isinstance(feed, DirectBtApiFeed), strat_dir.name
                assert feed.run_binding.matches(store.run_binding)
    finally:
        ProcessModeFence._reset_for_tests()
        for entry in added_paths:
            if entry in sys.path:
                sys.path.remove(entry)
