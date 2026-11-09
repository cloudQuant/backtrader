"""E020: one coordination lock across state archiving (iteration 63, approved).

``rebind_identity(mode="new_instance")`` checks that no pending/waiting work
exists and then archives ``state/``. A store writer that does not hold the
run lock could write between that check and the rename; its record would be
archived silently while the caller believed it durable. These tests drive
both interleavings deterministically.
"""

import json
import os
import threading

import pytest

from backtrader.live_state import (
    LiveStateError,
    LiveStateIdentityMismatch,
    PendingCommandStore,
    StrategyStateDir,
    WaitingOrderStore,
    rebind_identity,
)
from backtrader.live_state import identity as identity_module

from ._helpers import place_record, waiting_order


def _archived_pending(root):
    found = {}
    for name in os.listdir(root):
        if name.startswith("state.archived-"):
            with open(os.path.join(root, name, "pending.json"), encoding="utf-8") as handle:
                found.update(json.load(handle)["active"])
    return found


def _active_pending(root):
    with open(os.path.join(root, "state", "pending.json"), encoding="utf-8") as handle:
        return json.load(handle)["active"]


def _in_rebind_window(monkeypatch, action):
    """Run ``action`` in another thread between the active-state check and the rename."""
    original = identity_module.append_audit
    outcome = {}

    def audit(root, record):
        if record.get("event") == "identity_rebind" and "archived_state_dir" in record:
            worker = threading.Thread(target=lambda: outcome.setdefault("result", action()))
            worker.start()
            worker.join(0.5)  # a coordinated writer must still be waiting here
            outcome["thread"] = worker
            outcome["finished_inside_window"] = not worker.is_alive()
        return original(root, record)

    monkeypatch.setattr(identity_module, "append_audit", audit)
    return outcome


def test_pending_write_inside_rebind_window_is_never_archived_silently(state, monkeypatch):
    root, old_uuid = state.strategy_dir, state.strategy_uuid
    writer = PendingCommandStore(root, old_uuid, lock_timeout=5)
    outcome = _in_rebind_window(monkeypatch, lambda: writer.commit(place_record(old_uuid)))
    fresh = rebind_identity(root, mode="new_instance", operator="ops", reason="e020")
    outcome["thread"].join(10)
    marker = outcome.get("result")
    archived = _archived_pending(root)
    # Before E020 the writer finished inside the window and its marker was
    # archived although commit() returned its id.
    assert outcome["finished_inside_window"] is False
    assert marker is None, "a write for the archived identity must be refused"
    assert not archived and not _active_pending(root)
    assert fresh.strategy_uuid != old_uuid


def test_write_holding_the_lock_blocks_rebind_until_it_is_visible(state, monkeypatch):
    root, old_uuid = state.strategy_dir, state.strategy_uuid
    entered, release = threading.Event(), threading.Event()
    original_store = PendingCommandStore._store

    def slow_store(self, data, **kwargs):
        entered.set()
        release.wait(5)
        return original_store(self, data, **kwargs)

    monkeypatch.setattr(PendingCommandStore, "_store", slow_store)
    writer = PendingCommandStore(root, old_uuid, lock_timeout=5)
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("id", writer.commit(place_record(old_uuid))))
    worker.start()
    assert entered.wait(5)
    errors = {}

    def rebind():
        try:
            rebind_identity(root, mode="new_instance", operator="ops", reason="e020")
        except LiveStateError as error:
            errors["code"] = error.code

    rebinder = threading.Thread(target=rebind)
    rebinder.start()
    rebinder.join(0.3)
    assert rebinder.is_alive()  # waits for the in-progress write
    release.set()
    worker.join(5)
    rebinder.join(10)
    assert result["id"] and errors.get("code") == "rebind_blocked_active_state"
    assert result["id"] in _active_pending(root)


def test_waiting_write_inside_rebind_window_is_refused(state, monkeypatch):
    root, old_uuid = state.strategy_dir, state.strategy_uuid
    waiting = WaitingOrderStore(root, old_uuid, lock_timeout=5)

    def add():
        try:
            return waiting.add(waiting_order())
        except LiveStateError as error:
            return error.code

    outcome = _in_rebind_window(monkeypatch, add)
    rebind_identity(root, mode="new_instance", operator="ops", reason="e020")
    outcome["thread"].join(10)
    assert outcome["finished_inside_window"] is False
    assert outcome["result"] == "strategy_uuid_mismatch"


def test_run_lock_of_a_rebound_instance_is_refused(state):
    root = state.strategy_dir
    stale = StrategyStateDir(root)
    rebind_identity(root, mode="new_instance", operator="ops", reason="e020")
    with pytest.raises(LiveStateIdentityMismatch):
        stale.acquire_run_lock()
    current = StrategyStateDir(root)
    with current.acquire_run_lock() as held:
        assert held.held


@pytest.mark.parametrize("crash", [False, True])
def test_coordination_excludes_another_process_and_survives_its_crash(state, crash):
    import multiprocessing

    from ._mp_worker import hold_coordination

    context = multiprocessing.get_context("spawn")
    held, release = context.Event(), context.Event()
    child = context.Process(target=hold_coordination,
                            args=(state.strategy_dir, held, release, crash))
    child.start()
    try:
        assert held.wait(30)
        quick = PendingCommandStore(state.strategy_dir, state.strategy_uuid, lock_timeout=0.2)
        assert quick.commit(place_record(state.strategy_uuid)) is None  # lock timeout, nothing stored
        with pytest.raises(LiveStateError):
            rebind_identity_with_timeout(state.strategy_dir)
        release.set()
        child.join(30)
        assert child.exitcode == (3 if crash else 0)
        assert quick.commit(place_record(state.strategy_uuid)) is not None
    finally:
        release.set()
        child.join(5)


def rebind_identity_with_timeout(root):
    """A rebind cannot start while another process holds coordination."""
    from backtrader.live_state import identity as identity_mod
    from backtrader.live_state._common import StatePaths
    from backtrader.live_state.coordination import coordinated

    with coordinated(StatePaths(root), timeout=0.2):
        return identity_mod.rebind_identity(root, mode="new_instance", operator="ops", reason="x")


def test_path_alias_shares_one_coordination_lock(state, monkeypatch, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(state.strategy_dir)
    old_uuid = state.strategy_uuid
    writer = PendingCommandStore(str(alias), old_uuid, lock_timeout=5)
    outcome = _in_rebind_window(monkeypatch, lambda: writer.commit(place_record(old_uuid)))
    rebind_identity(state.strategy_dir, mode="new_instance", operator="ops", reason="e020")
    outcome["thread"].join(10)
    assert outcome["finished_inside_window"] is False and outcome["result"] is None
    assert not _archived_pending(state.strategy_dir)
