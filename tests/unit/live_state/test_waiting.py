import json

import pytest

from backtrader.live_state import LiveStateError, WaitingOrderStore

from ._helpers import waiting_order


def test_add_get_and_fifo_order(state):
    store = state.waiting
    late = store.add(waiting_order(local_seq=5))
    early = store.add(waiting_order(local_seq=2, offset="open"))
    assert [o["waiting_id"] for o in store.waiting()] == [early, late]
    stored = store.get(late)
    assert stored["status"] == "WAITING"
    assert stored["offset"] == "close_today"  # never rewritten
    assert stored["valid_intent"] == {"kind": "day", "value": None}
    with open(store.path, encoding="utf-8") as handle:
        assert set(json.load(handle)["orders"]) == {early, late}


def test_transition_is_compare_and_set(state):
    store = state.waiting
    waiting_id = store.add(waiting_order())
    assert store.transition(waiting_id, "WAITING", "DISPATCHING", attempt=1)
    assert store.transition(waiting_id, "WAITING", "DISPATCHING") is False
    assert store.get(waiting_id)["status"] == "DISPATCHING"
    assert store.transition(waiting_id, "DISPATCHING", "WAITING", reason="not_sent")
    assert store.transition(waiting_id, "WAITING", "DISPATCHING")
    assert store.transition(waiting_id, "DISPATCHING", "DISPATCHED", marker_id="m-1")
    assert store.active() == []
    final = store.get(waiting_id)
    assert final["status"] == "DISPATCHED"
    assert final["facts"] == {"attempt": 1, "reason": "not_sent", "marker_id": "m-1"}
    assert store.transition(waiting_id, "DISPATCHING", "DISPATCHED") is False
    assert store.transition("missing", "WAITING", "CANCELLED") is False


def test_competing_stores_only_one_wins(state):
    waiting_id = state.waiting.add(waiting_order())
    other = WaitingOrderStore(state.strategy_dir, state.strategy_uuid)
    assert state.waiting.transition(waiting_id, "WAITING", "DISPATCHING")
    assert other.transition(waiting_id, "WAITING", "CANCELLED") is False
    assert other.get(waiting_id)["status"] == "DISPATCHING"


@pytest.mark.parametrize(
    "pair",
    [
        ("WAITING", "DISPATCHED"),
        ("WAITING", "WAITING"),
        ("DISPATCHING", "CANCELLED"),
        ("DISPATCHED", "WAITING"),
        ("CANCELLED", "WAITING"),
        ("WAITING", "BOGUS"),
    ],
)
def test_illegal_pairs_raise(state, pair):
    waiting_id = state.waiting.add(waiting_order())
    with pytest.raises(LiveStateError) as info:
        state.waiting.transition(waiting_id, *pair)
    assert info.value.code == "waiting_transition_illegal"
    assert state.waiting.get(waiting_id)["status"] == "WAITING"


@pytest.mark.parametrize(
    "overrides",
    [
        {"side": "long"},
        {"size": 0},
        {"size": True},
        {"exectype": "Historical"},
        {"price": None},
        {"exectype": "StopLimit", "pricelimit": None},
        {"offset": "close_yday"},
        {"position_side": "LONG"},
        {"valid_intent": {"kind": "day", "value": "2026-11-06"}},
        {"valid_intent": {"kind": "absolute", "value": "2026-11-06T15:00:00"}},
        {"valid_intent": {"kind": "timedelta", "value": -5}},
        {"target_session": {"trading_day": "20261106"}},
        {
            "target_session": {
                "trading_day": "20261106",
                "continuous_start_utc": "2026-11-05T15:00:00+00:00",
                "session_end_utc": "2026-11-05T13:00:00+00:00",
            }
        },
        {"status": "DISPATCHING"},
        {"local_seq": 0},
        {"unexpected": 1},
        {"extra": {"api_key": "x"}},
    ],
)
def test_add_rejects_invalid_orders(state, overrides):
    with pytest.raises(LiveStateError) as info:
        state.waiting.add(waiting_order(**overrides))
    assert info.value.code in ("waiting_invalid", "secret_field_rejected")
    assert state.waiting.active() == []


def test_absolute_and_timedelta_validity_intents(state):
    absolute = waiting_order(valid_intent={"kind": "absolute", "value": "2026-11-06T07:00:00Z"})
    assert state.waiting.add(absolute)
    delta = waiting_order(local_seq=2, valid_intent={"kind": "timedelta", "value": 3600})
    assert state.waiting.add(delta)


def test_duplicate_local_seq_and_waiting_id_rejected(state):
    waiting_id = state.waiting.add(waiting_order())
    with pytest.raises(LiveStateError) as info:
        state.waiting.add(waiting_order())
    assert info.value.code == "waiting_duplicate"
    with pytest.raises(LiveStateError) as info:
        state.waiting.add(waiting_order(local_seq=9, waiting_id=waiting_id))
    assert info.value.code == "waiting_duplicate"
    assert state.waiting.transition(waiting_id, "WAITING", "CANCELLED")
    with pytest.raises(LiveStateError):
        state.waiting.add(waiting_order(local_seq=9, waiting_id=waiting_id))


def test_history_is_bounded(state):
    store = WaitingOrderStore(state.strategy_dir, state.strategy_uuid, history_limit=2)
    ids = []
    for seq in range(1, 5):
        waiting_id = store.add(waiting_order(local_seq=seq))
        assert store.transition(waiting_id, "WAITING", "EXPIRED")
        ids.append(waiting_id)
    assert [o["waiting_id"] for o in store.history()] == ids[-2:]
