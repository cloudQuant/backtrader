"""In-process live Store-config handoff contracts for the 028 runner."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
RUNNER_PATH = EXAMPLE / "run.py"


def _load_runner():
    example_path = str(EXAMPLE)
    if example_path not in sys.path:
        sys.path.insert(0, example_path)
    spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_store_config_override_runner_under_test", RUNNER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _override():
    return {
        "config": {"password": "SYNTHETIC_SECRET_VALUE", "profile": "synthetic"},
        "api_kwargs": {"synthetic_option": "in-memory"},
    }


def _live_config(selection_source="ctp_query"):
    return {
        "mode": "live",
        "entry": {"tier": "live"},
        "inputs": {"history_decision_tape": None},
        "selection": {"source": selection_source, "daily_bundles": []},
    }


def _plan(path):
    return {
        "selection_path": Path(path),
        "selection_source": "synthetic_selection_source",
        "source_snapshot_id": "synthetic_snapshot",
        "manifest": SimpleNamespace(
            decision_at=datetime(2026, 10, 26, tzinfo=timezone.utc), trading_days=()
        ),
    }


def _live_result(plan):
    return {
        "_plan": plan,
        "status": "LIVE_RUN_COMPLETE",
        "selection_evidence": {"status": "SYNTHETIC"},
        "simnow_profile": {"verified": True},
        "shutdown_status": "PASS",
        "strategy_shutdown_ready": True,
        "strategy_shutdown_post_join_confirmed": True,
        "engine_winddown_status": "COMPLETE",
        "cleanup_complete": True,
        "decision_tape": {"status": "CLOSED"},
        "decision_tape_readback": {"status": "VERIFIED"},
        "strategy_order_events": {"events": []},
    }


def test_live_store_config_uses_in_memory_override_without_environment(monkeypatch):
    monkeypatch.delenv("BT_SIMNOW_CONFIG_JSON", raising=False)
    config, api_kwargs = RUNNER._live_env_config(
        {"live": {"store_config_env": "BT_SIMNOW_CONFIG_JSON"}},
        override=_override(),
    )

    assert config == _override()["config"]
    assert api_kwargs == _override()["api_kwargs"]


def test_live_store_config_keeps_legacy_environment_fallback(monkeypatch):
    payload = _override()
    monkeypatch.setenv("BT_SIMNOW_CONFIG_JSON", json.dumps(payload))

    config, api_kwargs = RUNNER._live_env_config(
        {"live": {"store_config_env": "BT_SIMNOW_CONFIG_JSON"}}
    )

    assert config == payload["config"]
    assert api_kwargs == payload["api_kwargs"]


@pytest.mark.parametrize(
    ("override", "expected_code"),
    (
        (
            {
                "config": {"password": "SYNTHETIC_SECRET_VALUE", "api": object()},
                "api_kwargs": {},
            },
            "LIVE_STORE_CONFIG_INJECTION_DENIED",
        ),
        (
            {
                "config": {"password": "SYNTHETIC_SECRET_VALUE"},
                "api_kwargs": {"api_cls": object()},
            },
            "LIVE_STORE_CONFIG_INJECTION_DENIED",
        ),
        (
            {
                "config": {"password": "SYNTHETIC_SECRET_VALUE"},
                "api_kwargs": {},
                "extra": "SYNTHETIC_EXTRA_VALUE",
            },
            "LIVE_STORE_CONFIG_FIELDS_INVALID",
        ),
    ),
)
def test_run_rejects_invalid_override_before_epoch_or_store_path(
    monkeypatch, capsys, override, expected_code
):
    monkeypatch.setattr(RUNNER, "load_config", lambda _path: _live_config())
    monkeypatch.setattr(
        RUNNER,
        "run_live_epochs",
        lambda *args, **kwargs: pytest.fail("invalid override reached live epoch path"),
    )

    assert RUNNER.run(["--mode", "live"], _live_store_config_override=override) == 2
    output = capsys.readouterr().out
    assert expected_code in output
    assert "SYNTHETIC_SECRET_VALUE" not in output
    assert "SYNTHETIC_EXTRA_VALUE" not in output


def test_run_rejects_override_outside_live_mode(monkeypatch, capsys):
    config = _live_config()
    config["mode"] = "dry"
    config["entry"] = {"tier": "dry"}
    monkeypatch.setattr(RUNNER, "load_config", lambda _path: config)
    monkeypatch.setattr(
        RUNNER,
        "run_live_epochs",
        lambda *args, **kwargs: pytest.fail("non-live override reached live epoch path"),
    )

    assert RUNNER.run(["--mode", "dry"], _live_store_config_override=_override()) == 2
    output = capsys.readouterr().out
    assert "LIVE_STORE_CONFIG_OVERRIDE_REQUIRES_LIVE_MODE" in output
    assert "SYNTHETIC_SECRET_VALUE" not in output


@pytest.mark.parametrize("selection_source", ("ctp_query", "bundle"))
def test_run_forwards_override_to_query_and_bundle_epoch_entry(
    monkeypatch, capsys, selection_source
):
    config = _live_config(selection_source)
    override = _override()
    seen = []
    monkeypatch.setattr(RUNNER, "load_config", lambda _path: config)
    monkeypatch.setattr(
        RUNNER, "_factor_parameters", lambda _config, _factor_mode: ("native", 1, 30, 5)
    )
    monkeypatch.setattr(RUNNER, "load_market_plan", lambda *args, **kwargs: object())

    def fake_run_live_epochs(*args, **kwargs):
        seen.append(kwargs["_live_store_config_override"])
        return {"status": "LIVE_RUN_COMPLETE"}

    monkeypatch.setattr(RUNNER, "run_live_epochs", fake_run_live_epochs)

    assert RUNNER.run(["--mode", "live"], _live_store_config_override=override) == 0
    output = capsys.readouterr().out
    assert seen == [override]
    assert seen[0] is override
    assert "SYNTHETIC_SECRET_VALUE" not in output


def test_query_epoch_sequence_forwards_same_override_to_each_live_run(monkeypatch):
    override = _override()
    config = {
        "selection": {"source": "ctp_query", "daily_bundles": [], "max_epochs": 2},
        "inputs": {"history_decision_tape": "synthetic-history.jsonl"},
        "cohort": {"epoch_id": 7},
        "output": {"decision_tape_path": "synthetic-output.jsonl"},
    }
    seen = []
    monkeypatch.setattr(
        RUNNER, "_risk_policy", lambda _config: SimpleNamespace(run_end_policy="CLOSE_ALL")
    )
    monkeypatch.setattr(
        RUNNER,
        "_daily_epoch_tape_path",
        lambda _config, _path, *, epoch_index: Path(f"epoch-{epoch_index}.jsonl"),
    )
    monkeypatch.setattr(RUNNER, "_route_summary", lambda _plan: [])
    monkeypatch.setattr(RUNNER, "_live_epoch_retired", lambda _result: True)
    monkeypatch.setattr(RUNNER, "_live_epoch_controlled_stopped", lambda _result: False)

    def fake_run_live(*args, **kwargs):
        seen.append(kwargs["_live_store_config_override"])
        return _live_result(_plan("query-selection.json"))

    monkeypatch.setattr(RUNNER, "run_live", fake_run_live)

    summary = RUNNER._run_ctp_query_live_epochs(
        config,
        Path("runner.yaml"),
        "native",
        1,
        decision=SimpleNamespace(effective_tier="live"),
        allow_write_flag=False,
        _live_store_config_override=override,
    )

    assert summary["query_epoch_attempts"] == [7, 8]
    assert len(seen) == 2
    assert all(value is override for value in seen)


def test_bundle_epoch_sequence_forwards_same_override_to_each_live_run(monkeypatch):
    override = _override()
    config = {
        "selection": {"source": "bundle", "daily_bundles": ["next.json"]},
        "inputs": {"history_decision_tape": None},
        "cohort": {"epoch_id": 11},
        "output": {"decision_tape_path": "synthetic-output.jsonl"},
    }
    first_plan = _plan("first.json")
    second_plan = _plan("next.json")
    seen = []
    monkeypatch.setattr(RUNNER, "_daily_bundle_paths", lambda *_args: (Path("next.json"),))
    monkeypatch.setattr(
        RUNNER, "_risk_policy", lambda _config: SimpleNamespace(run_end_policy="CLOSE_ALL")
    )
    monkeypatch.setattr(RUNNER, "load_market_plan", lambda *args, **kwargs: second_plan)
    monkeypatch.setattr(RUNNER, "_assert_daily_plan_transition", lambda *_args: None)
    monkeypatch.setattr(
        RUNNER,
        "_daily_epoch_tape_path",
        lambda _config, _path, *, epoch_index: Path(f"bundle-{epoch_index}.jsonl"),
    )
    monkeypatch.setattr(RUNNER, "_route_summary", lambda _plan: [])
    monkeypatch.setattr(RUNNER, "_live_epoch_retired", lambda _result: True)

    def fake_run_live(*args, **kwargs):
        seen.append(kwargs["_live_store_config_override"])
        return _live_result(args[2])

    monkeypatch.setattr(RUNNER, "run_live", fake_run_live)

    summary = RUNNER.run_live_epochs(
        config,
        Path("runner.yaml"),
        first_plan,
        "native",
        1,
        decision=SimpleNamespace(effective_tier="live"),
        allow_write_flag=False,
        _live_store_config_override=override,
    )

    assert summary["later_bundle_reads"] == ["next.json"]
    assert summary["assembly_attempts"] == [11, 12]
    assert len(seen) == 2
    assert all(value is override for value in seen)
