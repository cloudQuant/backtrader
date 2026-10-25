"""Focused contracts for the external Iteration 51 installed-wheel CLI fixture."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Optional

import pytest


_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "scripts" / "iteration51_installed_fixture.py"


def _load_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "iteration51_installed_fixture_test", _FIXTURE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_example(path: Path) -> dict[str, bytes]:
    path.mkdir(parents=True)
    payloads = {
        "run.py": b"public runner\n",
        "entry_tier.py": b"public tier helper\n",
        "alpha003_strategy.py": b"public strategy\n",
        "config.yaml": b"schema: backtrader.alpha003.simnow_runner.v1\nmode: dry\n",
    }
    for name, payload in payloads.items():
        (path / name).write_bytes(payload)
    return payloads


def test_copy_public_example_pins_exact_four_files_and_separate_config(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    workspace.mkdir()
    source = workspace / "source"
    payloads = _write_example(source)
    offline_config = workspace / "research-fixture.yaml"
    offline_config.write_text("mode: research\n", encoding="utf-8")

    copied, config_path, pins = fixture.copy_public_example(
        source,
        workspace / "copy",
        offline_config=offline_config,
    )

    assert config_path == copied / "fixture-config.yaml"
    assert {path.name for path in copied.iterdir()} == set(fixture.PUBLIC_FILES) | {
        "fixture-config.yaml"
    }
    assert set(pins) == set(fixture.PUBLIC_FILES) | {"fixture-config.yaml"}
    for name, payload in payloads.items():
        assert (copied / name).read_bytes() == payload
        assert pins[name]["sha256"] == hashlib.sha256(payload).hexdigest()


def test_copy_public_example_rejects_incomplete_or_reused_destination(tmp_path: Path) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    workspace.mkdir()
    source = workspace / "source"
    source.mkdir()
    for name in fixture.PUBLIC_FILES[:-1]:
        (source / name).write_text("public\n", encoding="utf-8")
    with pytest.raises(fixture.InstalledFixtureError, match="missing or not regular"):
        fixture.copy_public_example(source, workspace / "copy")

    complete_source = workspace / "complete"
    _write_example(complete_source)
    existing = workspace / "existing"
    existing.mkdir()
    with pytest.raises(fixture.InstalledFixtureError, match="must not already exist"):
        fixture.copy_public_example(complete_source, existing)


def test_offline_paths_must_be_staged_and_confined_to_external_workspace(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    workspace.mkdir()
    example = workspace / "example"
    example.mkdir()
    config_path = example / "fixture-config.yaml"
    config_path.write_text("unused\n", encoding="utf-8")
    bundle = workspace / "bundle.json"
    bundle.write_text("{}\n", encoding="utf-8")
    minute = workspace / "minute.json"
    minute.write_text('{"bars": []}\n', encoding="utf-8")
    output = {
        "directory": "outputs",
        "evaluate_with_fincore": False,
        "decision_tape_path": None,
    }
    selection = {"bundle": "../bundle.json", "daily_bundles": []}
    inputs = {
        "minute_tape": "../minute.json",
        "execution_quotes": None,
        "instrument_metadata": None,
    }

    resolved = fixture._config_paths(
        {"mode": "research", "output": output, "selection": selection, "inputs": inputs},
        config_path,
        workspace,
        "research",
    )
    assert resolved["selection.bundle"] == str(bundle.resolve())
    assert resolved["inputs.minute_tape"] == str(minute.resolve())
    assert fixture._input_evidence(resolved)["inputs.minute_tape"] == {
        "path": str(minute.resolve()),
        "sha256": hashlib.sha256(minute.read_bytes()).hexdigest(),
        "size_bytes": minute.stat().st_size,
    }

    inputs["minute_tape"] = str(Path(tmp_path) / "outside-minute.json")
    with pytest.raises(fixture.InstalledFixtureError, match="inside the external workspace"):
        fixture._config_paths(
            {"mode": "research", "output": output, "selection": selection, "inputs": inputs},
            config_path,
            workspace,
            "research",
        )


def test_replay_config_requires_all_inputs_and_new_confined_outputs(tmp_path: Path) -> None:
    fixture = _load_fixture()
    workspace = tmp_path / "external"
    example = workspace / "example"
    fixtures = workspace / "inputs"
    example.mkdir(parents=True)
    fixtures.mkdir()
    config_path = example / "replay.yaml"
    config_path.write_text("unused\n", encoding="utf-8")
    paths = {}
    for name in ("bundle", "minute", "quotes", "metadata"):
        source = fixtures / (name + ".json")
        source.write_text("{}\n", encoding="utf-8")
        paths[name] = "../inputs/" + source.name
    config = {
        "mode": "replay",
        "selection": {"bundle": paths["bundle"], "daily_bundles": []},
        "inputs": {
            "minute_tape": paths["minute"],
            "execution_quotes": paths["quotes"],
            "instrument_metadata": paths["metadata"],
        },
        "output": {
            "directory": "../output",
            "decision_tape_path": "../decision.jsonl",
            "evaluate_with_fincore": False,
        },
    }

    resolved = fixture._config_paths(config, config_path, workspace, "replay")
    assert resolved["inputs.minute_tape"] == str((fixtures / "minute.json").resolve())
    assert resolved["output.decision_tape_path"] == str((workspace / "decision.jsonl").resolve())

    (workspace / "output").mkdir()
    with pytest.raises(fixture.InstalledFixtureError, match="output directory must be new"):
        fixture._config_paths(config, config_path, workspace, "replay")


def test_cli_case_uses_isolated_child_and_reused_installed_origin_verifier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    config = example / "config.yaml"
    config.write_text("mode: dry\n", encoding="utf-8")
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for command construction")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    monkeypatch.setenv("PYTHONPATH", "checkout-shadow")
    monkeypatch.setenv("BT_SIMNOW_CONFIG_JSON", "must-not-reach-child")
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        child = {
            "exit_code": 0,
            "wheel_sha256": wheel_hash,
            "loaded_modules_verified": 17,
            "fresh_bytecode_cache": True,
        }
        stdout = json.dumps({"status": "DRY_VALIDATION_COMPLETE"}) + "\n"
        stdout += fixture._CHILD_MARKER + json.dumps(child) + "\n"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(fixture.subprocess, "run", fake_run)
    result = fixture.run_cli_case(
        example_dir=example,
        config_path=config,
        wheel_path=wheel,
        wheel_sha256=wheel_hash,
        mode="dry",
        factor_mode="native",
    )

    assert result["status"] == "DRY_VALIDATION_COMPLETE"
    assert result["summary"] == {"status": "DRY_VALIDATION_COMPLETE"}
    assert observed["command"][1:3] == ["-I", "-c"]
    assert "iteration50_installed_fixture.py" in observed["command"][4]
    compile(observed["command"][3], "<iteration51-installed-child>", "exec")
    assert json.loads(observed["command"][-1]) == result["cli_argv"]
    assert "--allow-write" not in observed["command"]
    assert result["cli_argv"] == [
        str((example / "run.py").resolve()),
        "--config",
        str(config.resolve()),
        "--mode",
        "dry",
        "--factor-mode",
        "native",
    ]
    assert observed["kwargs"]["cwd"] == str(example.resolve())
    assert "PYTHONPATH" not in observed["kwargs"]["env"]
    assert "BT_SIMNOW_CONFIG_JSON" not in observed["kwargs"]["env"]
    assert observed["kwargs"]["timeout"] == 180.0


def test_cli_fixture_rejects_live_and_write_options() -> None:
    fixture = _load_fixture()
    with pytest.raises(fixture.InstalledFixtureError, match="safe installed-fixture set"):
        fixture._child_command(
            verifier_path=_FIXTURE_PATH,
            wheel_path=_FIXTURE_PATH,
            wheel_sha256="0" * 64,
            example_dir=_FIXTURE_PATH.parent,
            config_path=_FIXTURE_PATH,
            mode="live",
            factor_mode="native",
        )


def test_synthetic_live_child_is_separate_from_the_offline_allowlist() -> None:
    fixture = _load_fixture()

    assert fixture.SAFE_MODES == ("dry", "research", "replay")
    assert fixture.SYNTHETIC_LIVE_CASES == (
        "read-only",
        "write",
        "write-denied",
        "tier-escalation",
    )
    compile(fixture._SYNTHETIC_LIVE_CHILD_CODE, "<synthetic-live-child>", "exec")
    with pytest.raises(fixture.InstalledFixtureError, match="fixed local set"):
        fixture._synthetic_live_child_command(
            wheel_path=_FIXTURE_PATH,
            wheel_sha256="0" * 64,
            example_dir=_FIXTURE_PATH.parent,
            workspace=_FIXTURE_PATH.parent,
            case="live",
            factor_mode="native",
        )


@pytest.mark.parametrize(
    ("case", "exit_code", "status", "error_code", "write_enabled"),
    (
        ("read-only", 0, "LIVE_EPOCH_SEQUENCE_COMPLETE", None, False),
        ("write", 0, "LIVE_EPOCH_SEQUENCE_COMPLETE", None, True),
        ("write-denied", 2, "BLOCKED", "LIVE_WRITE_GRANT_MISSING_IN_CONFIG", False),
        ("tier-escalation", 2, "BLOCKED", "ENTRY_TIER_ESCALATION_DENIED", False),
    ),
)
def test_synthetic_live_case_runs_isolated_command_and_checks_finite_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
    exit_code: int,
    status: str,
    error_code: Optional[str],
    write_enabled: bool,
) -> None:
    fixture = _load_fixture()
    example = tmp_path / "copied-example"
    example.mkdir()
    (example / "run.py").write_text("# copied public runner\n", encoding="utf-8")
    (example / "config.yaml").write_text("schema: public-template\n", encoding="utf-8")
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    live_case_dir = workspace / "iteration51-live-case-test"
    live_case_dir.mkdir()
    live_config = live_case_dir / "runner.yaml"
    wheel = tmp_path / "pinned.whl"
    wheel.write_bytes(b"wheel placeholder for synthetic live command")
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    cli_argv = [
        str((example / "run.py").resolve()),
        "--config",
        str(live_config.resolve()),
        "--mode",
        "live",
        "--factor-mode",
        "native",
    ]
    if case in {"write", "write-denied"}:
        cli_argv.append("--allow-write")
    if error_code is None:
        summary = {
            "status": status,
            "mode": "live",
            "cleanup_complete": True,
            "epoch_count": 1,
            "write_mode": write_enabled,
            "selection_source": "ctp_query_snapshot_equal_weight_v1",
            "epochs": [
                {
                    "status": "LIVE_RUN_COMPLETE",
                    "cleanup_complete": True,
                    "routes": {"DCE.M": "M2611", "DCE.Y": "Y2611", "DCE.A": "A2611"},
                    "selection_source": "saved_bundle_legacy",
                    "scheduler_clock": "host-utc-plus-monotonic",
                    "selection_evidence": {
                        "routes": {
                            "DCE.M": "M2611",
                            "DCE.Y": "Y2611",
                            "DCE.A": "A2611",
                        },
                        "authorized_targets": ["DCE.M", "DCE.A"],
                    },
                    "strategy_order_events": {
                        "status": "AVAILABLE",
                        "events": ([{"ref": 1, "target": "DCE.M"}] if case == "write" else []),
                    },
                }
            ],
        }
        instances = 1
        flags = [write_enabled]
    else:
        summary = {"status": status, "code": error_code}
        instances = 0
        flags = []
    child = {
        "case": case,
        "exit_code": exit_code,
        "cli_argv": cli_argv,
        "wheel_sha256": wheel_hash,
        "loaded_modules_verified": 12,
        "fresh_bytecode_cache": True,
        "ctp_wrapper_factory_unchanged": True,
        "ctp_wrapper_mro_verified": bool(instances),
        "ctp_trader_leaf_instances": instances,
        "ctp_md_leaf_instances": instances,
        "ctp_wrapper_mros": (
            [["RegisteredSimClient", "RegisteredSimWrapper", "CtpClientWrapper", "object"]]
            if instances
            else []
        ),
        "store_write_flags": flags,
        "network_attempts": 0,
        "synthetic_leaf_actions": (
            [{"action": "insert", "instrument": "M2611", "exchange": "DCE"}]
            if case == "write"
            else []
        ),
        "arm_calls": 1 if case == "write" else 0,
        "disarm_calls": 1 if case == "write" else 0,
        "synthetic_fill_count": 1 if case == "write" else 0,
        "ctp_order_callback_count": 1 if case == "write" else 0,
        "ctp_trade_callback_count": 1 if case == "write" else 0,
        "selection_bundle_sha256": "a" * 64,
        "synthetic_only": True,
        "virtual_scheduler": True,
        "virtual_scheduler_monotonic_is_real": True,
        "virtual_scheduler_advance_count": 1 if error_code is None else 0,
        "virtual_scheduler_delivered_ticks": 1 if error_code is None else 0,
        "virtual_scheduler_callback_delivery_count": 1 if case == "write" else 0,
        "virtual_scheduler_pending_callbacks": 0,
        "virtual_scheduler_late_callback_schedule_count": 0,
        "virtual_scheduler_final_utc": "2026-10-25T00:01:00+00:00",
        "runner_clock_patch_binding": "run.__globals__['RunnerWallClock']",
        "runner_clock_patch_target_is_function_globals": True,
        "runner_clock_patch_origin": str((example / "run.py").resolve()),
        "clock_origins": {
            "runner_wall_clock_binding": "copied run.py run.__globals__['RunnerWallClock']",
            "ctp_receive_wall_clock": (
                "backtrader.stores.btapistore.time.time -> synthetic virtual UTC"
            ),
            "monotonic_clock": "host time.monotonic_ns forwarded without virtualization",
            "scheduler_shared_state": (
                "RunnerWallClock and CTP leaves share one child-local instance"
            ),
        },
        "runner_clock_constructor_calls": 1 if error_code is None else 0,
        "runner_clock_shared_with_virtual_scheduler": error_code is None,
        "store_environment_shape_valid": True,
        "store_environment_api_kwargs_keys": ["fixture_marker"],
        "query_families": ["account", "orders", "positions", "trades"]
        if error_code is None
        else [],
        "subscriptions": ["A2611", "M2611", "Y2611"] if error_code is None else [],
        "runner_summary_scheduler_clock_labels": (
            [{"path": "epochs[0]", "value": "host-utc-plus-monotonic"}]
            if error_code is None
            else []
        ),
        "runner_summary_scheduler_clock_label_meaning": (
            "production summary default identifier; not the injected runtime clock"
        ),
        "synthetic_leaf_close_receipt": {
            "trader_client_count": instances,
            "md_client_count": instances,
            "trader_stop_calls": instances,
            "trader_disconnect_calls": instances,
            "md_stop_calls": instances,
            "trader_connected_after_close": [False] if instances else [],
            "trader_ready_after_close": [False] if instances else [],
            "md_started_after_close": [False] if instances else [],
            "wrappers_connected_after_close": [False] if instances else [],
        },
        "authorized_products": ["DCE.M", "DCE.A"],
    }
    child["raw_cli_summary_sha256"] = hashlib.sha256(
        json.dumps(summary).encode("utf-8")
    ).hexdigest()
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        stdout = json.dumps(summary) + "\n"
        stdout += fixture._LIVE_CHILD_MARKER + json.dumps(child) + "\n"
        return SimpleNamespace(returncode=exit_code, stdout=stdout, stderr="")

    monkeypatch.setenv("PYTHONPATH", "checkout-shadow")
    monkeypatch.setenv("BT_SIMNOW_CONFIG_JSON", "ambient-must-not-reach-child")
    monkeypatch.setattr(fixture.subprocess, "run", fake_run)
    result = fixture.run_synthetic_live_case(
        example_dir=example,
        workspace=workspace,
        wheel_path=wheel,
        wheel_sha256=wheel_hash,
        case=case,
    )

    assert result["case"] == case
    assert result["status"] == status
    assert result["evidence_level"] == (
        "INSTALLED_WHEEL_LOCAL_SYNTHETIC_CTP_SDK_LEAF_VIRTUAL_SCHEDULER_ONLY"
    )
    assert observed["command"][1:3] == ["-I", "-c"]
    assert "iteration50_installed_fixture.py" in observed["command"][4]
    compile(observed["command"][3], "<synthetic-live-child>", "exec")
    assert observed["command"][-2:] == [case, "native"]
    assert observed["kwargs"]["cwd"] == str(example.resolve())
    assert "PYTHONPATH" not in observed["kwargs"]["env"]
    assert "BT_SIMNOW_CONFIG_JSON" not in observed["kwargs"]["env"]
    assert observed["kwargs"]["timeout"] == 300.0
