"""Exercise the live runner's durable fee-pair scope fence before provider work."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from backtrader.stores.execution_decision_journal import ExecutionDecisionJournal


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
RUNNER_PATH = EXAMPLE / "run.py"
if str(EXAMPLE) not in sys.path:
    sys.path.insert(0, str(EXAMPLE))
_SPEC = importlib.util.spec_from_file_location("alpha003_fee_pair_scope_runner", RUNNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(RUNNER)


ACCOUNT_SCOPE = "fee-pair-startup-account"
STRATEGY_SCOPE = "fee-pair-startup-strategy"


class _StopBeforeProvider(Exception):
    pass


def _config(tmp_path: Path, *, write_enabled: bool):
    return {
        "live": {
            "allow_writes": write_enabled,
            "account_scope": ACCOUNT_SCOPE,
            "strategy_scope": STRATEGY_SCOPE,
            "logical_run_id": "fee-pair-startup-run",
            "journal_path": str(tmp_path / "decision-journal.sqlite"),
            "ready_timeout_seconds": 1.0,
            "refresh_timeout_seconds": 1.0,
            "refresh_overall_timeout_seconds": 1.0,
            "refresh_interval_seconds": 1.0,
            "shutdown_grace_seconds": 1.0,
            "quote_max_age_seconds": 30.0,
            "query_max_age_seconds": 30.0,
        },
        "cohort": {
            "max_live_bar_age_seconds": 30.0,
            "max_future_skew_seconds": 1.0,
            "epoch_id": 1,
        },
        "selection": {"source": "ctp_query", "daily_bundles": False},
        "inputs": {"history_decision_tape": None},
        "output": {
            "decision_tape_path": str(tmp_path / "decision-tape.jsonl"),
            "decision_tape_max_bytes": 1024 * 1024,
        },
    }


def _install_startup_stubs(monkeypatch, *, write_enabled: bool, boundary):
    """Keep the real run_live/Journaling path and stop at the provider boundary."""

    from backtrader.stores import registered_sim

    store_constructions = []

    class NoProviderStore:
        def __init__(self, **_kwargs):
            store_constructions.append(True)
            raise AssertionError("provider Store must not be constructed before the fence check")

    monkeypatch.setattr(registered_sim, "RegisteredSimStore", NoProviderStore)
    monkeypatch.setattr(RUNNER, "_validate_golden_targets_option", lambda *_a, **_k: None)
    monkeypatch.setattr(RUNNER, "_run_loss_guard_policy", lambda *_a, **_k: (None, None))
    monkeypatch.setattr(
        RUNNER,
        "_risk_policy",
        lambda _config: (
            SimpleNamespace(max_order_intents_per_grid=2, max_order_intents_per_run=10)
            if write_enabled
            else None
        ),
    )
    monkeypatch.setattr(RUNNER, "_live_env_config", lambda *_a, **_k: ({}, {}))
    monkeypatch.setattr(
        RUNNER,
        "validate_official_simnow_store_profile",
        lambda *_a, **_k: {"verified": True, "environment": "synthetic", "profile": "test"},
    )
    monkeypatch.setattr(RUNNER, "_attach_live_epoch_failure_evidence", lambda *_a, **_k: None)
    monkeypatch.setattr(RUNNER, "_reject_legacy_live_source_highwater", boundary)
    return store_constructions


def _run(config, *, allow_write_flag):
    return RUNNER.run_live(
        config,
        Path(config["live"]["journal_path"]).with_name("synthetic-runner.yaml"),
        None,
        "native",
        "long",
        decision=SimpleNamespace(effective_tier="live"),
        allow_write_flag=allow_write_flag,
        _live_store_config_override={"synthetic": True},
    )


def test_write_live_runner_registers_durable_scope_before_provider_and_reuses_it(
    tmp_path, monkeypatch
):
    journal_path = tmp_path / "decision-journal.sqlite"
    unrelated_scope = ("another-account", "another-strategy")
    journal = ExecutionDecisionJournal(journal_path)
    unrelated_before = journal.register_fee_pair_required_scope(*unrelated_scope)
    journal.close()

    boundary_reads = []

    def stop_after_registration(active_journal, _scopes):
        boundary_reads.append(active_journal.fee_pair_required_scope(ACCOUNT_SCOPE, STRATEGY_SCOPE))
        raise _StopBeforeProvider

    constructions = _install_startup_stubs(
        monkeypatch, write_enabled=True, boundary=stop_after_registration
    )
    register = ExecutionDecisionJournal.register_fee_pair_required_scope
    register_calls = []

    def register_and_record(active_journal, account_scope, strategy_scope):
        record = register(active_journal, account_scope, strategy_scope)
        register_calls.append(record)
        return record

    monkeypatch.setattr(
        ExecutionDecisionJournal,
        "register_fee_pair_required_scope",
        register_and_record,
    )

    for _ in range(2):
        with pytest.raises(_StopBeforeProvider):
            _run(_config(tmp_path, write_enabled=True), allow_write_flag=True)

    assert len(register_calls) == 2
    assert register_calls[0] == register_calls[1]
    assert register_calls[0].registered_at_ns == register_calls[1].registered_at_ns
    assert boundary_reads == [register_calls[0], register_calls[0]]
    assert constructions == []

    journal = ExecutionDecisionJournal(journal_path)
    try:
        assert journal.fee_pair_required_scope(ACCOUNT_SCOPE, STRATEGY_SCOPE) == register_calls[0]
        assert journal.fee_pair_required_scope(*unrelated_scope) == unrelated_before
    finally:
        journal.close()


def test_readonly_live_runner_does_not_register_a_fee_pair_scope(tmp_path, monkeypatch):
    boundary_reads = []

    def stop_before_provider(active_journal, _scopes):
        boundary_reads.append(active_journal.fee_pair_required_scope(ACCOUNT_SCOPE, STRATEGY_SCOPE))
        raise _StopBeforeProvider

    constructions = _install_startup_stubs(
        monkeypatch, write_enabled=False, boundary=stop_before_provider
    )
    register_calls = []
    register = ExecutionDecisionJournal.register_fee_pair_required_scope

    def observe_registration(active_journal, account_scope, strategy_scope):
        register_calls.append((account_scope, strategy_scope))
        return register(active_journal, account_scope, strategy_scope)

    monkeypatch.setattr(
        ExecutionDecisionJournal,
        "register_fee_pair_required_scope",
        observe_registration,
    )

    config = _config(tmp_path, write_enabled=True)
    with pytest.raises(_StopBeforeProvider):
        _run(config, allow_write_flag=False)

    assert register_calls == []
    assert boundary_reads == [None]
    assert constructions == []

    journal = ExecutionDecisionJournal(tmp_path / "decision-journal.sqlite")
    try:
        assert journal.fee_pair_required_scope(ACCOUNT_SCOPE, STRATEGY_SCOPE) is None
    finally:
        journal.close()


def test_fee_pair_registration_exception_fails_before_provider_or_startup_boundary(
    tmp_path, monkeypatch
):
    boundary_calls = []

    def unexpected_boundary(*_args, **_kwargs):
        boundary_calls.append(True)
        raise _StopBeforeProvider

    constructions = _install_startup_stubs(
        monkeypatch, write_enabled=True, boundary=unexpected_boundary
    )

    def fail_registration(*_args, **_kwargs):
        raise RuntimeError("synthetic journal failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            ExecutionDecisionJournal,
            "register_fee_pair_required_scope",
            fail_registration,
        )
        with pytest.raises(RUNNER.RunnerError) as caught:
            _run(_config(tmp_path, write_enabled=True), allow_write_flag=True)

    assert caught.value.code == "LIVE_FEE_PAIR_SCOPE_REGISTRATION_FAILED"
    assert boundary_calls == []
    assert constructions == []

    journal = ExecutionDecisionJournal(tmp_path / "decision-journal.sqlite")
    try:
        assert journal.fee_pair_required_scope(ACCOUNT_SCOPE, STRATEGY_SCOPE) is None
    finally:
        journal.close()


def test_fee_pair_readback_mismatch_fails_closed_and_keeps_durable_claim(tmp_path, monkeypatch):
    boundary_calls = []

    def unexpected_boundary(*_args, **_kwargs):
        boundary_calls.append(True)
        raise _StopBeforeProvider

    constructions = _install_startup_stubs(
        monkeypatch, write_enabled=True, boundary=unexpected_boundary
    )
    readback = ExecutionDecisionJournal.fee_pair_required_scope

    with monkeypatch.context() as patch:
        patch.setattr(
            ExecutionDecisionJournal,
            "fee_pair_required_scope",
            lambda *_args, **_kwargs: None,
        )
        with pytest.raises(RUNNER.RunnerError) as caught:
            _run(_config(tmp_path, write_enabled=True), allow_write_flag=True)

    assert caught.value.code == "LIVE_FEE_PAIR_SCOPE_REGISTRATION_UNPROVEN"
    assert boundary_calls == []
    assert constructions == []

    journal = ExecutionDecisionJournal(tmp_path / "decision-journal.sqlite")
    try:
        registration = readback(journal, ACCOUNT_SCOPE, STRATEGY_SCOPE)
        assert registration is not None
        assert registration.state == "REQUIRE_PAIR_FAIL_CLOSED"
    finally:
        journal.close()
