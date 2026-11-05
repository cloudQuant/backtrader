import itertools
import json
import multiprocessing
import os
import queue

import pytest

import backtrader as bt
from backtrader.live_state import (
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateNotInitialized,
    SequenceAllocator,
)
from backtrader.live_state import atomic as atomic_module
from backtrader.order import OrderBase

from ._mp_worker import allocate_many


def test_allocate_is_strictly_increasing_and_persisted(state):
    numbers = [state.sequence.allocate() for _ in range(5)]
    assert numbers == [1, 2, 3, 4, 5]
    fresh = SequenceAllocator(state.strategy_dir, state.strategy_uuid)
    assert fresh.allocate() == 6
    assert fresh.read()["local_seq"] == 6


def test_allocate_tracks_ref_high_water_without_lowering(state):
    state.sequence.allocate(ref=40)
    state.sequence.allocate(ref=7)
    state.sequence.allocate()
    assert state.sequence.ref_high_water == 40
    assert state.sequence.observe_ref(55) == 55
    assert state.sequence.observe_ref(3) == 55
    assert state.sequence.local_seq == 3


@pytest.mark.parametrize("ref", [0, -1, True, 1.0, "3"])
def test_allocate_rejects_invalid_ref(state, ref):
    with pytest.raises(LiveStateError) as info:
        state.sequence.allocate(ref=ref)
    assert info.value.code == "invalid_ref"
    assert state.sequence.local_seq == 0


def test_failed_write_does_not_return_a_number(state, monkeypatch):
    state.sequence.allocate()

    def broken(path, obj):
        raise OSError("disk full")

    from backtrader.live_state import sequence as sequence_module

    monkeypatch.setattr(sequence_module, "atomic_write_json", broken)
    with pytest.raises(OSError):
        state.sequence.allocate()
    monkeypatch.undo()
    assert state.sequence.allocate() == 2


def test_corrupt_sequence_file_fails_closed(state):
    with open(state.sequence.path, "w", encoding="utf-8") as handle:
        handle.write('{"local_seq": 3')
    with pytest.raises(LiveStateCorrupt):
        state.sequence.allocate()


def test_negative_or_extra_fields_are_corrupt(state):
    raw = state.sequence.read()
    raw["local_seq"] = -1
    atomic_module.atomic_write_json(state.sequence.path, raw)
    with pytest.raises(LiveStateCorrupt):
        state.sequence.read()
    raw["local_seq"] = 1
    raw["extra"] = 1
    atomic_module.atomic_write_json(state.sequence.path, raw)
    with pytest.raises(LiveStateCorrupt):
        state.sequence.read()


def test_missing_sequence_file_is_not_restarted_from_zero(state):
    state.sequence.allocate()
    os.remove(state.sequence.path)
    with pytest.raises(LiveStateNotInitialized):
        state.sequence.allocate()
    assert not os.path.exists(state.sequence.path)


def test_sequence_owned_by_other_strategy_is_rejected(state, tmp_path):
    with open(state.sequence.path, encoding="utf-8") as handle:
        raw = json.load(handle)
    raw["strategy_uuid"] = "1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b"
    atomic_module.atomic_write_json(state.sequence.path, raw)
    with pytest.raises(LiveStateIdentityMismatch) as info:
        state.sequence.allocate()
    assert info.value.code == "strategy_uuid_mismatch"


def test_two_spawned_processes_never_share_a_number(state, monkeypatch):
    monkeypatch.setenv("BACKTRADER_LIGHT_IMPORT", "1")
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    procs = [
        ctx.Process(
            target=allocate_many,
            args=(state.strategy_dir, state.strategy_uuid, 50, barrier, results),
        )
        for _ in range(2)
    ]
    for proc in procs:
        proc.start()
    collected = []
    try:
        for _ in procs:
            collected.append(results.get(timeout=90))
    except queue.Empty:  # pragma: no cover - diagnostic path
        pytest.fail("spawned allocator did not report")
    finally:
        for proc in procs:
            proc.join(timeout=30)
    assert all(proc.exitcode == 0 for proc in procs)
    every = []
    for _pid, numbers in collected:
        assert len(numbers) == 50
        assert all(a < b for a, b in zip(numbers, numbers[1:]))
        every.extend(numbers)
    assert len(set(every)) == 100
    assert sorted(every) == list(range(1, 101))
    final = state.sequence.read()
    assert final["local_seq"] == 100
    assert final["ref_high_water"] == 1049


@pytest.fixture
def restore_refbasis():
    original = OrderBase.refbasis
    yield
    OrderBase.refbasis = original


def _new_order():
    return bt.BuyOrder(
        owner=None, data=None, size=1, price=10.0, exectype=bt.Order.Limit, simulated=True
    )


def test_restore_ref_basis_moves_next_order_ref_past_high_water(state, restore_refbasis):
    OrderBase.refbasis = itertools.count(5)
    state.sequence.observe_ref(200)
    start = state.sequence.restore_ref_basis()
    assert start == 201
    assert _new_order().ref == 201
    assert _new_order().ref == 202


def test_restore_ref_basis_never_moves_refs_backwards(state, restore_refbasis):
    OrderBase.refbasis = itertools.count(500)
    state.sequence.observe_ref(10)
    assert state.sequence.restore_ref_basis() == 500
    assert _new_order().ref == 500


def test_restore_ref_basis_refuses_shadowed_counter(state, restore_refbasis):
    class Shadow(bt.BuyOrder):
        refbasis = itertools.count(1)

    try:
        with pytest.raises(LiveStateError) as info:
            state.sequence.restore_ref_basis()
        assert info.value.code == "ref_basis_shadowed"
    finally:
        del Shadow.refbasis
