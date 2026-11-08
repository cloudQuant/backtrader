"""Read-only enumeration of synthetic Gateway cancellation plans."""

import json
import multiprocessing
import queue
import threading
from dataclasses import FrozenInstanceError, replace

import pytest

from backtrader.live_state import LiveStateCorrupt, LiveStateIdentityMismatch
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.live_state.test_gateway_pending import data
from tests.unit.live_state.test_gateway_pending import inputs as inputs
from tests.unit.live_state.test_gateway_pending_cancel import plan, prepare, upgrade


def test_v2_enumerates_empty_without_writing_or_upgrading(state, inputs, monkeypatch):
    binding, _, _ = inputs
    host = prepare(state, inputs)
    before = data(state)
    monkeypatch.setattr(host._store, "_store", lambda *_a, **_kw: pytest.fail("unexpected write"))
    assert host.list_cancel_plans() == ()
    assert data(state) == before and json.loads(before)["version"] == 2
    wrong = GatewayPendingHost(
        state.strategy_dir, state.strategy_uuid, replace(binding, principal="other")
    )
    with pytest.raises(ValueError, match="GATEWAY_BINDING_MISMATCH"):
        wrong.list_cancel_plans()
    wrong_strategy = GatewayPendingHost(
        state.strategy_dir, "1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b", binding
    )
    with pytest.raises(LiveStateIdentityMismatch):
        wrong_strategy.list_cancel_plans()
    assert data(state) == before


def test_v3_reopen_enumerates_all_in_stable_order_as_independent_values(state, inputs):
    binding, route, _ = inputs
    prepare(state, inputs, ("key-a", "key-b"))
    host = upgrade(state, binding)
    plans = (
        plan(host, route, key="key-b", op="z"),
        plan(host, route, op="a"),
        plan(host, route, op="m"),
    )
    for item in plans:
        host.save_cancel_plan(item)
    before = data(state)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    result = reopened.list_cancel_plans()
    again = reopened.list_cancel_plans()
    assert result == (plans[1], plans[2], plans[0])
    assert result == again and result is not again
    assert all(a is not b for a, b in zip(result, again, strict=True))
    with pytest.raises(FrozenInstanceError):
        result[0].operation_id = "changed"
    wrong = GatewayPendingHost(
        state.strategy_dir, state.strategy_uuid, replace(binding, principal="other")
    )
    with pytest.raises(ValueError, match="GATEWAY_BINDING_MISMATCH"):
        wrong.list_cancel_plans()
    assert data(state) == before


@pytest.mark.parametrize(
    "fault", ["bad_plan", "wrong_target", "wrong_operation", "capacity", "bad_record"]
)
def test_v3_rejects_entire_corrupt_snapshot_without_filtering(state, inputs, fault):
    binding, route, _ = inputs
    prepare(state, inputs)
    host = upgrade(state, binding)
    host.save_cancel_plan(plan(host, route, op="a"))
    host.save_cancel_plan(plan(host, route, op="z"))
    raw = json.loads(data(state))
    gateway = raw["gateway"]
    if fault == "bad_plan":
        gateway["cancel_attempts"]["z"]["plan"]["unexpected"] = 1
    elif fault == "wrong_target":
        gateway["cancel_attempts"]["z"]["plan"]["reservation_id"] = "wrong"
    elif fault == "wrong_operation":
        gateway["cancel_attempts"]["z"]["plan"]["operation_id"] = "other"
    elif fault == "capacity":
        gateway["max_cancel_entries"] = 1
    else:
        gateway["cancel_attempts"]["z"]["record"] = {"state": "SENT"}
    with open(state.pending.path, "w", encoding="utf-8") as file:
        json.dump(raw, file)
    before = data(state)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    with pytest.raises(LiveStateCorrupt):
        reopened.list_cancel_plans()
    assert data(state) == before


def _write_plan_blocked(root, strategy_uuid, binding, item, entered, release, replies):
    try:
        writer = GatewayPendingHost(root, strategy_uuid, binding)
        original = writer._store._store

        def paused(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test writer release timed out")
            return original(*args, **kwargs)

        writer._store._store = paused
        replies.put(("ok", writer.save_cancel_plan(item)))
    except BaseException as error:
        replies.put(("error", type(error).__name__))


def test_concurrent_host_save_and_enumeration_share_validated_snapshot(state, inputs):
    binding, route, _ = inputs
    prepare(state, inputs)
    host = upgrade(state, binding)
    first, second = plan(host, route, op="a"), plan(host, route, op="b")
    host.save_cancel_plan(first)
    assert host.list_cancel_plans() == (first,)
    context = multiprocessing.get_context("spawn")
    entered, release, replies = context.Event(), context.Event(), context.Queue()
    writer = context.Process(
        target=_write_plan_blocked,
        args=(state.strategy_dir, state.strategy_uuid, binding, second, entered, release, replies),
    )
    reader_started, reader_done = threading.Event(), threading.Event()
    observations = queue.Queue()

    def read():
        reader_started.set()
        try:
            observations.put(("ok", host.list_cancel_plans()))
        except BaseException as error:
            observations.put(("error", type(error).__name__))
        finally:
            reader_done.set()

    reader = threading.Thread(target=read)
    writer.start()
    try:
        assert entered.wait(10)
        reader.start()
        assert reader_started.wait(2)
        assert not reader_done.wait(0.1)
        release.set()
        assert replies.get(timeout=15) == ("ok", second)
        assert reader_done.wait(10)
        assert observations.get(timeout=2) == ("ok", (first, second))
    finally:
        release.set()
        if reader.ident is not None:
            reader.join(10)
            assert not reader.is_alive()
        writer.join(10)
        if writer.is_alive():
            writer.terminate()
            writer.join(5)
            pytest.fail("test writer required termination")
        assert writer.exitcode == 0
        replies.close()
