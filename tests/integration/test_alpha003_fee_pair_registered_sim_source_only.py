"""Synthetic registered-Sim fee-pair SOURCE_ONLY strategy/tape integration."""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path
import socket

from tests.integration import test_alpha003_registered_sim_order_chain as chain_fixture


def _run_guarded_chain_fixture(tmp_path, monkeypatch, **fixture_kwargs):
    """Run the public synthetic chain with config/environment/network guards."""
    allowed_root = tmp_path.resolve(strict=True)
    audit = {"private_input_denials": 0, "network_denials": 0, "synthetic_root_opens": 0}

    def checked_path(value):
        if isinstance(value, int):
            return None
        try:
            return Path(os.fspath(value)).resolve(strict=False)
        except (TypeError, ValueError, OSError):
            return None

    def is_inside_root(path):
        if path is None:
            return False
        try:
            path.relative_to(allowed_root)
        except ValueError:
            return False
        return True

    def check_file_access(value):
        path = checked_path(value)
        inside = is_inside_root(path)
        if inside:
            audit["synthetic_root_opens"] += 1
            return
        name = "" if path is None else path.name.casefold()
        if name == "config.yaml" or name == "runner.yaml" or name == ".env" or name.startswith(".env."):
            audit["private_input_denials"] += 1
            raise AssertionError("PRIVATE_CONFIG_OR_ENV_AUDIT_BLOCKED:" + name)

    original_builtin_open = builtins.open
    original_io_open = io.open
    original_path_open = Path.open
    original_os_open = os.open

    def guarded_builtin_open(file, *args, **kwargs):
        check_file_access(file)
        return original_builtin_open(file, *args, **kwargs)

    def guarded_io_open(file, *args, **kwargs):
        check_file_access(file)
        return original_io_open(file, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        check_file_access(path)
        return original_path_open(path, *args, **kwargs)

    def guarded_os_open(path, *args, **kwargs):
        check_file_access(path)
        return original_os_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_builtin_open)
    monkeypatch.setattr(io, "open", guarded_io_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(os, "open", guarded_os_open)

    def deny_network(*_args, **_kwargs):
        audit["network_denials"] += 1
        raise AssertionError("NETWORK_AUDIT_BLOCKED")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)

    result = chain_fixture._run_alpha003_live_strategy_order_chain_fixture(
        tmp_path,
        monkeypatch,
        _diagnostic_path=tmp_path / "alpha003-source-only-diagnostic.json",
        **fixture_kwargs,
    )
    return result, audit


def test_alpha003_registered_fee_pair_scope_is_source_only_and_fails_closed_before_open(
    tmp_path, monkeypatch
):
    """Exercise the production Strategy/Writer/Journal with synthetic SDK leaves."""
    result, audit = _run_guarded_chain_fixture(
        tmp_path, monkeypatch, _fee_pair_source_only=True
    )
    assert result["evidence_level"] == "SOURCE_FAKE_REGISTERED_SIM_FEE_PAIR_SOURCE_ONLY"
    assert result["live_source_only_rows"] > 0
    assert result["highwater_matches_last_live_row"] is True
    assert result["native_insert_count"] == 0
    assert result["store_submit_count"] == 0
    assert result["complete_live_grid_coverage"] is False
    assert result["observed_live_rows_all_source_only"] is True
    assert result["grid_acceptance"] == "SOURCE_ONLY_ONLY_NO_COMPLETE_GRID_ACCEPTANCE"
    assert (
        result["open_fill_close_cancel_chain"]
        == "NOT_COVERED_BY_THIS_REGISTERED_SCOPE_FIXTURE"
    )
    assert audit["private_input_denials"] == 0
    assert audit["network_denials"] == 0
    assert audit["synthetic_root_opens"] > 0


def test_alpha003_missing_pair_blocks_later_source_rows_after_warmup(tmp_path, monkeypatch):
    """A missing first pair keeps later slots off the tape and Journal chain."""
    result, audit = _run_guarded_chain_fixture(
        tmp_path,
        monkeypatch,
        _fee_pair_source_only=True,
        _fee_pair_missing_pair_then_block=True,
    )
    assert (
        result["evidence_level"]
        == "SOURCE_FAKE_REGISTERED_SIM_MISSING_PAIR_SEQUENCE_BLOCK_ONLY"
    )
    assert result["first_terminal_reason"] == "FEE_PAIR_LIVE_SOURCE_CANDIDATE_UNAVAILABLE"
    assert result["subsequent_terminal_reason"] == "FEE_PAIR_SOURCE_SEQUENCE_BLOCKED"
    assert result["writer_attempt_count"] == 1
    assert result["live_source_only_rows"] == 0
    assert result["complete_live_grid_coverage"] is False
    assert result["grid_acceptance"] == "SOURCE_ONLY_ONLY_NO_COMPLETE_GRID_ACCEPTANCE"
    assert result["open_fill_close_cancel_chain"] == "NOT_COVERED_BY_THIS_REGISTERED_SCOPE_FIXTURE"
    assert result["tape_closed"] is True
    assert audit["private_input_denials"] == 0
    assert audit["network_denials"] == 0
    assert audit["synthetic_root_opens"] > 0
    assert result["reservation_attempt_count"] == 0


def test_alpha003_source_only_anchor_survives_stale_grid_check_without_fallback(
    tmp_path, monkeypatch
):
    """A stale snapshot after append cannot trigger an ordinary second anchor."""
    result, audit = _run_guarded_chain_fixture(
        tmp_path,
        monkeypatch,
        _fee_pair_source_only=True,
        _fee_pair_stale_snapshot_after_append=True,
    )
    assert (
        result["evidence_level"]
        == "SOURCE_FAKE_REGISTERED_SIM_SOURCE_ONLY_STALE_GRID_BLOCK_ONLY"
    )
    assert result["stale_grid_reason"] == "FACTOR_SNAPSHOT_CHANGED_BEFORE_DECISION"
    assert result["input_open_action_count"] == 0
    assert result["input_reduction_action_count"] == 0
    assert result["open_filter_action_coverage"] == "NOT_EXERCISED_NO_PLANNED_OPEN_ACTION"
    assert result["owned_position_reduction_coverage"] == "NOT_EXERCISED_NO_POSITION_ACTION"
    assert result["open_action_after_stale_grid"] is False
    assert result["ordinary_live_source_fallback_count"] == 0
    assert result["risk_path_reached_stale_batch"] is True
    assert result["owned_position_reduction_observed"] is False
    assert result["complete_live_grid_coverage"] is False
    assert result["tape_closed"] is True and result["tape_failed"] is False
    assert result["highwater_matches_last_live_row"] is True
    assert audit["private_input_denials"] == 0
    assert audit["network_denials"] == 0
    assert audit["synthetic_root_opens"] > 0
