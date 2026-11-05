import json
import os
import shutil
import uuid

import pytest

from backtrader.live_state import (
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateLocked,
    LiveStateNotInitialized,
    PendingCommandStore,
    StrategyStateDir,
    WaitingOrderStore,
    bind_account,
    hash_account_id,
    initialize_identity,
    load_identity,
    read_audit,
    rebind_identity,
)
from backtrader.live_state import _common

from ._helpers import ACCOUNT_HASH, OTHER_HASH, place_record, waiting_order


def _state_file(root, name):
    return os.path.join(str(root), "state", name)


def test_initialize_creates_identity_and_pristine_state(strategy_dir):
    identity = initialize_identity(strategy_dir)
    assert uuid.UUID(identity.strategy_uuid).version == 4
    assert identity.strategy_uuid == identity.strategy_uuid.lower()
    assert identity.strategy_dir == os.path.realpath(str(strategy_dir))
    assert identity.account_binding is None
    with open(_state_file(strategy_dir, "identity.json"), encoding="utf-8") as handle:
        stored = json.load(handle)
    assert stored["strategy_uuid"] == identity.strategy_uuid
    with open(_state_file(strategy_dir, "sequence.json"), encoding="utf-8") as handle:
        assert json.load(handle)["local_seq"] == 0
    for name in ("pending.json", "waiting_orders.json"):
        assert os.path.exists(_state_file(strategy_dir, name))
    assert read_audit(strategy_dir)[-1]["event"] == "identity_initialized"
    assert load_identity(strategy_dir) == identity


def test_initialize_is_exclusive(strategy_dir):
    first = initialize_identity(strategy_dir)
    with pytest.raises(LiveStateError) as info:
        initialize_identity(strategy_dir)
    assert info.value.code == "identity_already_initialized"
    assert load_identity(strategy_dir).strategy_uuid == first.strategy_uuid
    # the refused second init must not have rewritten the companion files
    state = StrategyStateDir(strategy_dir)
    assert state.sequence.allocate() == 1
    assert state.pending.active() == []


def test_initialize_requires_existing_directory(tmp_path):
    with pytest.raises(LiveStateError) as info:
        initialize_identity(tmp_path / "missing")
    assert info.value.code == "strategy_dir_missing"


def test_initialize_refuses_leftover_state_without_identity(state):
    root = state.strategy_dir
    state.sequence.allocate()
    os.remove(_state_file(root, "identity.json"))
    with pytest.raises(LiveStateError) as info:
        initialize_identity(root)
    assert info.value.code == "state_dir_not_empty"


@pytest.mark.parametrize("name", ["sequence.json", "pending.json", "waiting_orders.json"])
def test_initialize_refuses_used_companion_even_without_audit_log(state, name):
    root = state.strategy_dir
    state.sequence.allocate()
    state.pending.commit(place_record(state.strategy_uuid))
    state.waiting.add(waiting_order())
    for other in ("sequence.json", "pending.json", "waiting_orders.json"):
        if other != name:
            os.remove(_state_file(root, other))
    os.remove(_state_file(root, "identity.json"))
    os.remove(_state_file(root, "audit.log"))
    with open(_state_file(root, name), "rb") as handle:
        before = handle.read()
    with pytest.raises(LiveStateError) as info:
        initialize_identity(root)
    assert info.value.code == "state_dir_not_empty"
    with open(_state_file(root, name), "rb") as handle:
        assert handle.read() == before
    assert not os.path.exists(_state_file(root, "identity.json"))


def test_initialize_recovers_from_crash_with_only_pristine_files(strategy_dir, monkeypatch):
    from backtrader.live_state import identity as identity_module

    def crash(path, text):
        raise OSError("crash before identity commit")

    monkeypatch.setattr(identity_module, "_create_exclusive", crash)
    with pytest.raises(OSError):
        initialize_identity(strategy_dir)
    monkeypatch.undo()
    assert not os.path.exists(_state_file(strategy_dir, "identity.json"))
    identity = initialize_identity(strategy_dir)
    state = StrategyStateDir(strategy_dir)
    assert state.strategy_uuid == identity.strategy_uuid
    assert state.sequence.allocate() == 1


def test_load_missing_and_corrupt(strategy_dir):
    with pytest.raises(LiveStateNotInitialized):
        load_identity(strategy_dir)
    initialize_identity(strategy_dir)
    path = _state_file(strategy_dir, "identity.json")
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    raw["strategy_uuid"] = "not-a-uuid"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    with pytest.raises(LiveStateCorrupt):
        load_identity(strategy_dir)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{")
    with pytest.raises(LiveStateCorrupt):
        load_identity(strategy_dir)


def test_load_detects_hostname_change(strategy_dir, monkeypatch):
    initialize_identity(strategy_dir)
    monkeypatch.setattr(_common.socket, "gethostname", lambda: "other-host")
    with pytest.raises(LiveStateIdentityMismatch) as info:
        load_identity(strategy_dir)
    assert info.value.code == "hostname_mismatch"
    assert load_identity(strategy_dir, check_host_path=False).hostname != "other-host"


def test_load_detects_copied_directory(strategy_dir, tmp_path):
    original = initialize_identity(strategy_dir)
    copy_dir = tmp_path / "copy"
    shutil.copytree(str(strategy_dir), str(copy_dir))
    with pytest.raises(LiveStateIdentityMismatch) as info:
        load_identity(copy_dir)
    assert info.value.code == "strategy_dir_mismatch"
    with pytest.raises(LiveStateIdentityMismatch):
        StrategyStateDir(copy_dir)
    assert load_identity(strategy_dir).strategy_uuid == original.strategy_uuid


def test_rebind_move_keeps_uuid_and_audits(strategy_dir, tmp_path):
    original = initialize_identity(strategy_dir)
    moved = tmp_path / "moved"
    shutil.move(str(strategy_dir), str(moved))
    with pytest.raises(LiveStateIdentityMismatch):
        load_identity(moved)
    rebound = rebind_identity(moved, mode="move", operator="ops", reason="moved disk")
    assert rebound.strategy_uuid == original.strategy_uuid
    assert load_identity(moved).strategy_dir == os.path.realpath(str(moved))
    record = read_audit(moved)[-1]
    assert record["event"] == "identity_rebind"
    assert record["mode"] == "move"
    assert record["operator"] == "ops"
    with pytest.raises(LiveStateError) as info:
        rebind_identity(moved, mode="move", operator="ops", reason="again")
    assert info.value.code == "rebind_not_required"


def test_rebind_new_instance_archives_state(strategy_dir, tmp_path):
    original = initialize_identity(strategy_dir)
    copy_dir = tmp_path / "copy"
    shutil.copytree(str(strategy_dir), str(copy_dir))
    fresh = rebind_identity(copy_dir, mode="new_instance", operator="ops", reason="second account")
    assert fresh.strategy_uuid != original.strategy_uuid
    archives = [name for name in os.listdir(str(copy_dir)) if name.startswith("state.archived-")]
    assert len(archives) == 1
    with open(os.path.join(str(copy_dir), archives[0], "identity.json"), encoding="utf-8") as fh:
        assert json.load(fh)["strategy_uuid"] == original.strategy_uuid
    assert read_audit(copy_dir)[-1]["previous_strategy_uuid"] == original.strategy_uuid
    with open(os.path.join(str(copy_dir), archives[0], "audit.log"), encoding="utf-8") as fh:
        assert json.loads(fh.read().splitlines()[-1])["mode"] == "new_instance"
    assert StrategyStateDir(copy_dir).sequence.allocate() == 1


def test_rebind_new_instance_refused_with_active_marker(state, tmp_path):
    marker_id = state.pending.commit(place_record(state.strategy_uuid))
    assert marker_id
    with pytest.raises(LiveStateError) as info:
        rebind_identity(state.strategy_dir, mode="new_instance", operator="ops", reason="x")
    assert info.value.code == "rebind_blocked_active_state"
    assert load_identity(state.strategy_dir).strategy_uuid == state.strategy_uuid
    assert PendingCommandStore(state.strategy_dir, state.strategy_uuid).get(marker_id)


def test_rebind_new_instance_refused_with_waiting_order(state):
    WaitingOrderStore(state.strategy_dir, state.strategy_uuid).add(waiting_order())
    with pytest.raises(LiveStateError) as info:
        rebind_identity(state.strategy_dir, mode="new_instance", operator="ops", reason="x")
    assert info.value.code == "rebind_blocked_active_state"


def test_rebind_refused_while_live_run_holds_lock(state):
    with state.acquire_run_lock():
        with pytest.raises(LiveStateLocked):
            rebind_identity(state.strategy_dir, mode="new_instance", operator="ops", reason="x")


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"mode": "copy", "operator": "ops", "reason": "x"}, "rebind_invalid_mode"),
        ({"mode": "move", "operator": "", "reason": "x"}, "operator_required"),
        ({"mode": "move", "operator": "ops", "reason": " "}, "reason_required"),
    ],
)
def test_rebind_validates_arguments(state, kwargs, code):
    with pytest.raises(LiveStateError) as info:
        rebind_identity(state.strategy_dir, **kwargs)
    assert info.value.code == code


def test_bind_account_once(state):
    binding = {"exchange": "CTP___FUTURE", "account_hash": ACCOUNT_HASH}
    bound = bind_account(state.strategy_dir, binding)
    assert bound.account_binding == binding
    assert bind_account(state.strategy_dir, dict(binding)).account_binding == binding
    with pytest.raises(LiveStateIdentityMismatch) as info:
        bind_account(state.strategy_dir, {"exchange": "CTP___FUTURE", "account_hash": OTHER_HASH})
    assert info.value.code == "account_binding_mismatch"
    assert load_identity(state.strategy_dir).account_binding == binding
    assert read_audit(state.strategy_dir)[-1]["event"] == "account_bound"


@pytest.mark.parametrize(
    "binding",
    [
        {"exchange": "CTP___FUTURE", "account_hash": "123456"},
        {"exchange": "CTP___FUTURE", "account_hash": ACCOUNT_HASH, "account_id": "123456"},
        {"exchange": "CTP___FUTURE"},
        {"exchange": "", "account_hash": ACCOUNT_HASH},
    ],
)
def test_account_binding_rejects_raw_ids_and_bad_hashes(strategy_dir, binding):
    with pytest.raises(LiveStateError) as info:
        initialize_identity(strategy_dir, account_binding=binding)
    assert info.value.code == "account_binding_invalid"
    assert not os.path.exists(_state_file(strategy_dir, "identity.json"))


def test_hash_account_id_is_sha256_hex():
    digest = hash_account_id("123456")
    assert digest == "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92"
    assert "123456" not in digest
