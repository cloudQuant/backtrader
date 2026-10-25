"""Pre-Store integration contracts for the 028 live profile gate."""

from __future__ import annotations

from types import SimpleNamespace
import json

import pytest

from test_alpha003_simnow_runner import RUNNER, _base_config


SDK_SELECTOR = pytest.importorskip("bt_api_ctp.ctp_env_selector")


class _ReachedStore(RuntimeError):
    pass


def _live_call_inputs(tmp_path, monkeypatch, env_config):
    config = _base_config(tmp_path, "live")
    config["entry"]["tier"] = "live"
    config["cohort"].update(max_live_bar_age_seconds=60.0, max_future_skew_seconds=0.0)
    config["live"].update(
        allow_writes=False,
        account_scope="fixture-account",
        strategy_scope="fixture-strategy",
        logical_run_id="fixture-run",
        journal_path=str(tmp_path / "decisions.sqlite"),
        ready_timeout_seconds=1.0,
        refresh_timeout_seconds=1.0,
        refresh_overall_timeout_seconds=2.0,
        refresh_interval_seconds=0.1,
        quote_max_age_seconds=60.0,
        query_max_age_seconds=60.0,
        shutdown_grace_seconds=1.0,
        store_config_env="BT_ALPHA003_PROFILE_INTEGRATION_CONFIG_JSON",
    )
    config["output"].update(
        decision_tape_path=str(tmp_path / "decisions.jsonl"),
        decision_tape_max_bytes=1_000_000,
    )
    config_path = tmp_path / "profile-integration.yaml"
    monkeypatch.setenv(config["live"]["store_config_env"], json.dumps(env_config))
    plan = {
        "targets": (),
        "routes": {},
        "product_by_target": {},
        "selection_path": "fixture-selection.json",
        "selection_source": "saved_bundle_legacy",
        "source_snapshot_id": None,
    }
    return config, config_path, plan


def _run_live(config, config_path, plan):
    return RUNNER.run_live(
        config,
        config_path,
        plan,
        "native",
        1,
        decision=SimpleNamespace(effective_tier="live"),
        allow_write_flag=False,
    )


def _profile_rejection_code(error):
    return getattr(error, "reason", getattr(error, "code", None))


def _trap_registered_store_init(monkeypatch):
    import backtrader.stores.registered_sim as store_module

    store_type = store_module.RegisteredSimStore
    calls = []

    def trapped_init(_self, **kwargs):
        calls.append(kwargs)
        raise _ReachedStore("stop after observing Store constructor arguments")

    # Preserve the class identity captured by factor_execution_facts while
    # still proving whether run_live reached the Store constructor.
    monkeypatch.setattr(store_type, "__init__", trapped_init)
    return calls


@pytest.mark.parametrize(
    ("env_config", "expected_reason"),
    [
        ({"config": {}, "api_kwargs": {}}, "CTP_FRONT_MISSING"),
    ],
    ids=("missing-fronts",),
)
def test_missing_profile_is_rejected_before_store_construction(
    tmp_path, monkeypatch, env_config, expected_reason
):
    calls = _trap_registered_store_init(monkeypatch)
    config, config_path, plan = _live_call_inputs(tmp_path, monkeypatch, env_config)

    with pytest.raises(Exception) as error:
        _run_live(config, config_path, plan)

    assert calls == []
    assert _profile_rejection_code(error.value) == expected_reason


def _non_simnow_config():
    td_front, md_front = SDK_SELECTOR.registered_broker_sim_fronts("hongyuan_sim_telecom")
    return {
        "config": {
            "td_front": td_front,
            "md_front": md_front,
            "ctp_env_profile": "hongyuan_sim_telecom",
        },
        "api_kwargs": {},
    }


def _mismatched_official_config():
    profile = "set1_group1"
    td_front, _md_front = SDK_SELECTOR.official_simnow_fronts(profile)
    _other_td, md_front = SDK_SELECTOR.official_simnow_fronts("set1_group2")
    return {
        "config": {
            "td_front": td_front,
            "md_front": md_front,
            "ctp_env_profile": profile,
        },
        "api_kwargs": {},
    }


@pytest.mark.parametrize(
    ("config_factory", "expected_reason"),
    [
        (_non_simnow_config, "CTP_PROFILE_NOT_OFFICIAL_SIMNOW"),
        (_mismatched_official_config, "CTP_PROFILE_FRONT_MISMATCH"),
    ],
    ids=("non-simnow-broker", "mismatched-official-pair"),
)
def test_non_simnow_or_mismatched_pair_is_rejected_before_store_construction(
    tmp_path, monkeypatch, config_factory, expected_reason
):
    calls = _trap_registered_store_init(monkeypatch)
    config, config_path, plan = _live_call_inputs(tmp_path, monkeypatch, config_factory())

    with pytest.raises(Exception) as error:
        _run_live(config, config_path, plan)

    assert calls == []
    assert _profile_rejection_code(error.value) == expected_reason


def test_official_pair_with_api_kwargs_override_reaches_store_unchanged(tmp_path, monkeypatch):
    base_profile = "set1_group1"
    base_td, base_md = SDK_SELECTOR.official_simnow_fronts(base_profile)
    effective_profile = "set2_7x24"
    effective_td, effective_md = SDK_SELECTOR.official_simnow_fronts(effective_profile)
    env_config = {
        "config": {
            "td_front": base_td,
            "md_front": base_md,
            "ctp_env_profile": base_profile,
        },
        "api_kwargs": {
            "td_address": effective_td,
            "md_address": effective_md,
            "ctp_env_profile": effective_profile,
        },
    }
    calls = _trap_registered_store_init(monkeypatch)
    config, config_path, plan = _live_call_inputs(tmp_path, monkeypatch, env_config)

    with pytest.raises(_ReachedStore):
        _run_live(config, config_path, plan)

    assert len(calls) == 1
    assert calls[0]["config"] == env_config["config"]
    assert calls[0]["api_kwargs"] == env_config["api_kwargs"]
