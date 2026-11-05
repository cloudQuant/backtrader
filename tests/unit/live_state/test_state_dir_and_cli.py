import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backtrader.live_state import (
    LiveStateLocked,
    LiveStateNotInitialized,
    StrategyStateDir,
    append_audit,
    load_identity,
    read_audit,
)
from backtrader.live_state import LiveStateError
from backtrader.live_state.cli import main

from ._helpers import ACCOUNT_HASH, place_record, waiting_order

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_state_dir_requires_explicit_initialization(strategy_dir):
    with pytest.raises(LiveStateNotInitialized):
        StrategyStateDir(strategy_dir)
    assert not os.path.exists(os.path.join(str(strategy_dir), "state", "identity.json"))


def test_state_dir_bundles_one_identity(state):
    uuid = state.strategy_uuid
    for component in (state.sequence, state.pending, state.waiting):
        assert component.strategy_uuid == uuid
    assert state.snapshot.path.startswith(state.strategy_dir)
    reopened = StrategyStateDir(state.strategy_dir)
    assert reopened.strategy_uuid == uuid


def test_run_lock_is_exclusive_and_released(state):
    other = StrategyStateDir(state.strategy_dir)
    with state.acquire_run_lock() as held:
        assert held.held
        with pytest.raises(LiveStateLocked):
            other.acquire_run_lock()
    lock = other.acquire_run_lock()
    lock.release()
    assert not lock.held


def test_audit_rejects_secret_keys(state):
    with pytest.raises(LiveStateError) as info:
        append_audit(state.strategy_dir, {"event": "x", "nested": {"api_secret": "s"}})
    assert info.value.code == "secret_field_rejected"
    with pytest.raises(LiveStateError):
        append_audit(state.strategy_dir, {"no_event": 1})
    assert [r["event"] for r in read_audit(state.strategy_dir)] == ["identity_initialized"]


def _run_main(capsys, argv):
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_cli_init_show_and_resolve_in_process(strategy_dir, capsys):
    root = str(strategy_dir)
    code, out = _run_main(
        capsys, ["init", root, "--exchange", "CTP___FUTURE", "--account-hash", ACCOUNT_HASH]
    )
    assert code == 0 and out["ok"] is True
    assert out["identity"]["account_binding"]["account_hash_prefix"] == ACCOUNT_HASH[:12]
    state = StrategyStateDir(root)
    marker_id = state.pending.commit(place_record(state.strategy_uuid))
    state.pending.mark(marker_id, "UNKNOWN")
    state.waiting.add(waiting_order())

    code, out = _run_main(capsys, ["show", root])
    assert code == 0
    assert out["identity"]["strategy_uuid"] == state.strategy_uuid
    assert out["pending"]["unknown_count"] == 1
    assert len(out["waiting_orders"]) == 1
    assert ACCOUNT_HASH not in json.dumps(out)

    code, out = _run_main(
        capsys,
        [
            "resolve",
            root,
            marker_id,
            "--conclusion",
            "terminal_not_sent",
            "--operator",
            "ops",
            "--evidence",
            "ticket-1",
            "--evidence",
            "query-2",
        ],
    )
    assert code == 0 and out["resolution"]["evidence"] == ["ticket-1", "query-2"]
    assert state.pending.unknown() == []

    code, out = _run_main(
        capsys,
        [
            "resolve",
            root,
            marker_id,
            "--conclusion",
            "terminal_not_sent",
            "--operator",
            "ops",
            "--evidence",
            "t",
        ],
    )
    assert code == 1 and out["error"] == "marker_not_found"


def test_cli_init_rejects_partial_binding_and_rebind(strategy_dir, capsys):
    root = str(strategy_dir)
    code, out = _run_main(capsys, ["init", root, "--exchange", "CTP___FUTURE"])
    assert code == 1 and out["error"] == "account_binding_invalid"
    assert not os.path.exists(os.path.join(root, "state", "identity.json"))
    code, out = _run_main(capsys, ["init", root])
    assert code == 0
    code, out = _run_main(
        capsys, ["rebind", root, "--mode", "move", "--operator", "ops", "--reason", "noop"]
    )
    assert code == 1 and out["error"] == "rebind_not_required"
    code, out = _run_main(
        capsys,
        ["rebind", root, "--mode", "new_instance", "--operator", "ops", "--reason", "fresh"],
    )
    assert code == 0
    assert out["identity"]["strategy_uuid"] == load_identity(root).strategy_uuid


def test_cli_show_subprocess_smoke(state):
    env = dict(os.environ)
    env["BACKTRADER_LIGHT_IMPORT"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "backtrader.live_state", "show", state.strategy_dir],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    out = json.loads(completed.stdout)
    assert out["ok"] is True
    assert out["identity"]["strategy_uuid"] == state.strategy_uuid
    assert out["identity_check"] == {"ok": True, "code": None}
    assert out["sequence"]["local_seq"] == 0


def test_cli_show_uninitialized_exits_1(tmp_path, capsys):
    code, out = _run_main(capsys, ["show", str(tmp_path)])
    assert code == 1 and out["error"] == "state_not_initialized"


def test_cli_usage_error_exits_2(capsys):
    assert main(["bogus"]) == 2
