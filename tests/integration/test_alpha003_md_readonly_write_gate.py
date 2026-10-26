"""Fail-closed compatibility gate for the 028 read-only MD login option."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
RUNNER_PATH = EXAMPLE / "run.py"
_ENV_NAME = "BT_ALPHA003_MD_READONLY_WRITE_GATE_CONFIG_JSON"

if str(EXAMPLE) not in sys.path:
    sys.path.insert(0, str(EXAMPLE))
_SPEC = importlib.util.spec_from_file_location(
    "alpha003_simnow_runner_md_readonly_write_gate", RUNNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(RUNNER)


class _ReachedProfileValidation(RuntimeError):
    pass


_MISSING = object()


def _store_options(*, config_option=_MISSING, api_option=_MISSING):
    config = {
        "td_front": "tcp://127.0.0.1:1",
        "md_front": "tcp://127.0.0.1:1",
        "ctp_env_profile": "set1_group1",
        "broker_id": "SYNTHETIC_BROKER",
        "investor_id": "SYNTHETIC_USER",
        "password": "SYNTHETIC_PASSWORD",
    }
    api_kwargs = {}
    if config_option is not _MISSING:
        config["allow_zero_login_response"] = config_option
    if api_option is not _MISSING:
        api_kwargs["allow_zero_login_response"] = api_option
    return {"config": config, "api_kwargs": api_kwargs}


def _live_config(tmp_path, *, allow_writes):
    return {
        "selection": {"source": "ctp_query", "daily_bundles": []},
        "cohort": {
            "max_live_bar_age_seconds": 60.0,
            "max_future_skew_seconds": 0.0,
        },
        "inputs": {"history_decision_tape": None},
        "live": {
            "golden_targets": None,
            "allow_writes": allow_writes,
            "account_scope": "synthetic-account",
            "strategy_scope": "synthetic-strategy",
            "logical_run_id": "synthetic-run",
            "journal_path": str(tmp_path / "decision-journal.sqlite"),
            "ready_timeout_seconds": 1.0,
            "refresh_timeout_seconds": 1.0,
            "refresh_overall_timeout_seconds": 2.0,
            "refresh_interval_seconds": 0.1,
            "quote_max_age_seconds": 60.0,
            "query_max_age_seconds": 60.0,
            "shutdown_grace_seconds": 1.0,
            "store_config_env": _ENV_NAME,
        },
        "risk": {
            "policy_id": "synthetic-readonly-gate-v1",
            "max_hold_eligible_bars": 12,
            "preclose_grace_seconds": 60,
            "run_end_policy": "CLOSE_ALL",
            "quote_max_age_seconds": 5,
            "max_state_age_seconds": 30,
            "max_notional_per_position": 2000,
            "max_total_notional": 3000,
            "max_margin_per_position": 250,
            "max_total_margin": 500,
            "max_loss_per_position": 20,
            "max_total_loss": 40,
            "round_trip_fee_upper_bound_per_contract": 1,
            "stop_loss_ticks": 2,
            "max_order_intents_per_grid": 2,
            "max_order_intents_per_run": 20,
        },
        "output": {
            "decision_tape_path": str(tmp_path / "decision-tape.jsonl"),
            "decision_tape_max_bytes": 1_000_000,
        },
    }


def _install_pre_store_traps(monkeypatch):
    import backtrader.stores.registered_sim as registered_sim

    store_calls = []
    profile_calls = []

    def store_init(_self, **kwargs):
        store_calls.append(kwargs)
        raise AssertionError("read-only write gate reached Store construction")

    def profile_sentinel(config, api_kwargs):
        profile_calls.append((dict(config), dict(api_kwargs)))
        raise _ReachedProfileValidation

    monkeypatch.setattr(registered_sim.RegisteredSimStore, "__init__", store_init)
    monkeypatch.setattr(RUNNER, "validate_official_simnow_store_profile", profile_sentinel)
    return store_calls, profile_calls


def _call_live(tmp_path, config, *, allow_write, override=None):
    return RUNNER.run_live(
        config,
        tmp_path / "synthetic-runner.yaml",
        None,
        "native",
        1,
        decision=SimpleNamespace(effective_tier="live"),
        allow_write_flag=allow_write,
        _live_store_config_override=override,
    )


@pytest.mark.parametrize(
    ("source", "location", "value"),
    [
        ("environment", "api_kwargs", True),
        ("environment", "config", True),
        ("override", "api_kwargs", True),
        ("override", "config", True),
        # The CTP wrapper applies bool(value); this misleading string is enabled.
        ("environment", "api_kwargs", "false"),
    ],
    ids=(
        "environment-api-true",
        "environment-config-true",
        "protected-override-api-true",
        "protected-override-config-true",
        "truthy-malformed-value",
    ),
)
def test_write_enabled_rejects_effective_zero_login_before_store_or_profile(
    tmp_path, monkeypatch, source, location, value
):
    store_calls, profile_calls = _install_pre_store_traps(monkeypatch)
    config = _live_config(tmp_path, allow_writes=True)
    options = _store_options(
        config_option=value if location == "config" else _MISSING,
        api_option=value if location == "api_kwargs" else _MISSING,
    )
    if source == "environment":
        monkeypatch.setenv(_ENV_NAME, json.dumps(options))
        override = None
    else:
        monkeypatch.delenv(_ENV_NAME, raising=False)
        override = options

    with pytest.raises(RUNNER.RunnerError) as error:
        _call_live(tmp_path, config, allow_write=True, override=override)

    assert error.value.code == "LIVE_ZERO_LOGIN_RESPONSE_READ_ONLY"
    assert store_calls == []
    assert profile_calls == []
    assert not (tmp_path / "decision-journal.sqlite").exists()
    assert not (tmp_path / "decision-tape.jsonl").exists()


def test_read_only_zero_login_option_reaches_normal_profile_validation(tmp_path, monkeypatch):
    store_calls, profile_calls = _install_pre_store_traps(monkeypatch)
    config = _live_config(tmp_path, allow_writes=False)
    monkeypatch.setenv(
        _ENV_NAME,
        json.dumps(_store_options(api_option=True)),
    )

    with pytest.raises(_ReachedProfileValidation):
        _call_live(tmp_path, config, allow_write=False)

    assert store_calls == []
    assert len(profile_calls) == 1
    assert profile_calls[0][1]["allow_zero_login_response"] is True
    assert not (tmp_path / "decision-journal.sqlite").exists()
    assert not (tmp_path / "decision-tape.jsonl").exists()


def test_api_kwargs_false_overrides_config_true_for_write_enabled_run(tmp_path, monkeypatch):
    store_calls, profile_calls = _install_pre_store_traps(monkeypatch)
    config = _live_config(tmp_path, allow_writes=True)
    override = _store_options(config_option=True, api_option=False)
    monkeypatch.delenv(_ENV_NAME, raising=False)

    with pytest.raises(_ReachedProfileValidation):
        _call_live(tmp_path, config, allow_write=True, override=override)

    assert store_calls == []
    assert len(profile_calls) == 1
    assert profile_calls[0][0]["allow_zero_login_response"] is True
    assert profile_calls[0][1]["allow_zero_login_response"] is False
