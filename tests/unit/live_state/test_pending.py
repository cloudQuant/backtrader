import dataclasses
import json
from typing import Any, Mapping

import pytest

from backtrader.live_state import (
    LiveStateError,
    PendingCommandStore,
    read_audit,
)
from backtrader.live_state import pending as pending_module

from ._helpers import place_record


def _on_disk(store):
    with open(store.path, encoding="utf-8") as handle:
        return json.load(handle)


def test_commit_persists_prepared_marker_before_returning_id(state):
    store = state.pending
    marker_id = store.commit(place_record(state.strategy_uuid), local_seq=1, bt_ref=9)
    assert isinstance(marker_id, str) and marker_id
    assert store.last_marker_id == marker_id
    stored = _on_disk(store)["active"][marker_id]
    assert stored["status"] == "PREPARED"
    assert stored["client_order_id"] == "000000000001"
    assert stored["native_identity"] == {"front_id": 1, "session_id": 7, "trading_day": "20261105"}
    assert stored["local_seq"] == 1
    assert stored["bt_ref"] == 9
    assert stored["host_scope"] == state.strategy_uuid


@dataclasses.dataclass(frozen=True)
class _StubRecord:
    """Mirror of the SDK ``PreDispatchRecord.to_dict()`` shape."""

    payload: Mapping[str, Any]

    def to_dict(self):
        return dict(self.payload)


def _sdk_shape(strategy_uuid, **overrides):
    payload = {
        "operation": "place",
        "host_scope": strategy_uuid,
        "exchange_name": "CTP___FUTURE",
        "symbol": "rb2601",
        "identity": {
            "exchange_name": "CTP___FUTURE",
            "client_order_id": "000000000042",
            "fields": {"front_id": 3, "session_id": 9},
            "session_generation": 2,
        },
        "target_identity": None,
        "request_summary": {"side": "buy", "volume": 1},
        "trading_day": "20261105",
        "session_generation": 2,
        "created_at_utc": "2026-11-05T01:00:00+00:00",
    }
    payload.update(overrides)
    return _StubRecord(payload)


def test_commit_accepts_to_dict_records(state):
    store = state.pending
    marker_id = store.commit(_sdk_shape(state.strategy_uuid), local_seq=2)
    marker = store.get(marker_id)
    assert marker["client_order_id"] == "000000000042"
    assert marker["native_identity"] == {"front_id": 3, "session_id": 9}
    assert marker["session_generation"] == 2
    assert marker["local_seq"] == 2


def test_commit_accepts_real_sdk_pre_dispatch_record(state):
    protocol = pytest.importorskip("bt_api_base.direct_write_protocol")
    identity = protocol.NativeOrderIdentity(
        exchange_name="CTP___FUTURE",
        client_order_id="000000000077",
        fields={"front_id": 1, "session_id": 5},
        session_generation=4,
    )
    record = protocol.PreDispatchRecord(
        operation=protocol.WriteOperation.PLACE,
        host_scope=state.strategy_uuid,
        exchange_name="CTP___FUTURE",
        symbol="rb2601",
        identity=identity,
        target_identity=None,
        request_summary={"side": "buy", "volume": 1},
        trading_day="20261105",
        session_generation=4,
        created_at_utc="2026-11-05T01:00:00+00:00",
    )
    assert isinstance(state.pending, protocol.PreDispatchCommitPort)
    port = state.pending.bind(local_seq=3, bt_ref=12)
    assert isinstance(port, protocol.PreDispatchCommitPort)
    marker_id = port.commit(record)
    assert marker_id and port.last_marker_id == marker_id
    marker = state.pending.get(marker_id)
    assert marker["operation"] == "place"
    assert marker["client_order_id"] == "000000000077"
    assert (marker["local_seq"], marker["bt_ref"]) == (3, 12)


def test_commit_returns_none_and_stores_nothing_on_io_error(state, monkeypatch):
    def broken(path, obj):
        raise OSError("disk full")

    monkeypatch.setattr(pending_module, "atomic_write_json", broken)
    assert state.pending.commit(place_record(state.strategy_uuid)) is None
    assert state.pending.last_marker_id is None
    monkeypatch.undo()
    assert state.pending.active() == []


def test_commit_returns_none_when_lock_is_held(state):
    from backtrader.live_state import FileLock

    store = PendingCommandStore(state.strategy_dir, state.strategy_uuid, lock_timeout=0.05)
    with FileLock(store.paths.pending_lock):
        assert store.commit(place_record(state.strategy_uuid)) is None
    assert store.active() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"host_scope": "1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b"},
        {"operation": "amend"},
        {"client_order_id": None, "native_identity": {}},
        {"symbol": None},
        {"exchange_name": ""},
        {"request_summary": {"password": "x"}},
        {"native_identity": {"investor_id": "123456"}},
        {"session_generation": -1},
        {"local_seq": 0},
        {"request_summary": {"px": float("nan")}},
    ],
)
def test_commit_rejects_invalid_records(state, overrides):
    assert state.pending.commit(place_record(state.strategy_uuid, **overrides)) is None
    assert state.pending.active() == []


def test_commit_rejects_conflicting_host_facts(state):
    record = place_record(state.strategy_uuid, local_seq=4)
    assert state.pending.commit(record, local_seq=5) is None
    assert state.pending.commit(record, local_seq=4) is not None


def test_cancel_requires_target_identity(state):
    cancel = place_record(state.strategy_uuid, operation="cancel")
    assert state.pending.commit(cancel) is None
    cancel["target_identity"] = {"exchange_id": "SHFE", "order_sys_id": "  123"}
    assert state.pending.commit(cancel) is not None


def test_settlement_confirm_needs_no_symbol(state):
    record = {
        "operation": "settlement_confirm",
        "host_scope": state.strategy_uuid,
        "exchange_name": "CTP___FUTURE",
        "trading_day": "20261105",
    }
    assert state.pending.commit(record) is not None


def test_duplicate_native_identity_and_inflight_local_seq_rejected(state):
    first = state.pending.commit(place_record(state.strategy_uuid), local_seq=1)
    assert first
    assert state.pending.commit(place_record(state.strategy_uuid), local_seq=2) is None
    other_identity = place_record(state.strategy_uuid, client_order_id="000000000002")
    assert state.pending.commit(other_identity, local_seq=1) is None
    assert state.pending.commit(other_identity, local_seq=2) is not None
    # still rejected after the first marker became terminal (kept in history)
    assert state.pending.mark(first, "TERMINAL", reason="filled")
    assert state.pending.commit(place_record(state.strategy_uuid), local_seq=3) is None


def test_mark_forward_transitions_and_history(state):
    store = state.pending
    marker_id = store.commit(place_record(state.strategy_uuid))
    assert store.mark(marker_id, "DISPATCHED")
    assert store.mark(marker_id, "DISPATCHED", note="replayed")  # same status merges facts
    assert store.mark(marker_id, "PREPARED") is False
    assert store.mark(marker_id, "ACCEPTED", order_sys_id="  123")
    assert store.mark(marker_id, "DISPATCHED") is False
    assert store.mark(marker_id, "TERMINAL", reason="filled")
    assert store.active() == []
    history = store.history()
    assert [m["marker_id"] for m in history] == [marker_id]
    assert [t["to"] for t in history[0]["transitions"]] == ["DISPATCHED", "ACCEPTED", "TERMINAL"]
    assert history[0]["facts"]["order_sys_id"] == "  123"
    assert store.mark(marker_id, "UNKNOWN") is False  # terminal markers are closed


def test_prepared_may_jump_to_accepted_or_terminal(state):
    store = state.pending
    first = store.commit(place_record(state.strategy_uuid))
    assert store.mark(first, "ACCEPTED")
    second = store.commit(place_record(state.strategy_uuid, client_order_id="000000000002"))
    assert store.mark(second, "TERMINAL", reason="not_sent")


def test_unknown_is_sticky(state):
    store = state.pending
    marker_id = store.commit(place_record(state.strategy_uuid))
    assert store.mark(marker_id, "DISPATCHED")
    assert store.mark(marker_id, "UNKNOWN", cause="timeout")
    for status in ("PREPARED", "DISPATCHED", "ACCEPTED", "TERMINAL"):
        assert store.mark(marker_id, status) is False
    assert [m["marker_id"] for m in store.unknown()] == [marker_id]
    assert store.mark(marker_id, "UNKNOWN", query="pending")  # facts may still be added


def test_mark_never_raises(state, monkeypatch):
    marker_id = state.pending.commit(place_record(state.strategy_uuid))
    assert state.pending.mark("no-such-marker", "DISPATCHED") is False
    assert state.pending.mark(marker_id, "BOGUS") is False
    assert state.pending.mark(marker_id, "DISPATCHED", token="x") is False
    assert state.pending.mark(marker_id, "DISPATCHED", obj=object()) is False

    def broken(path, obj):
        raise OSError("disk full")

    monkeypatch.setattr(pending_module, "atomic_write_json", broken)
    assert state.pending.mark(marker_id, "DISPATCHED") is False
    monkeypatch.undo()
    assert state.pending.get(marker_id)["status"] == "PREPARED"


def test_attach_merges_facts_but_not_conflicting_identity(state):
    store = state.pending
    marker_id = store.commit(place_record(state.strategy_uuid))
    assert store.attach(marker_id, exchange_order_id="X1", exchange_id="SHFE")
    assert store.attach(marker_id, exchange_order_id="X1", filled=0)
    assert store.attach(marker_id, exchange_order_id="X2") is False
    assert store.attach(marker_id, front_id=99) is False
    assert store.attach(marker_id, client_order_id="000000000009") is False
    marker = store.get(marker_id)
    assert marker["status"] == "PREPARED"
    assert marker["facts"] == {"exchange_order_id": "X1", "exchange_id": "SHFE", "filled": 0}


def test_find_by_identity(state):
    store = state.pending
    first = store.commit(place_record(state.strategy_uuid))
    second = store.commit(
        place_record(state.strategy_uuid, client_order_id="000000000002"), local_seq=2
    )
    store.attach(second, exchange_id="SHFE", order_sys_id="  77")
    found = store.find_by_identity({"front_id": 1, "session_id": 7})
    assert sorted(m["marker_id"] for m in found) == sorted([first, second])
    only = store.find_by_identity({"client_order_id": "000000000002", "front_id": 1})
    assert [m["marker_id"] for m in only] == [second]
    assert [
        m["marker_id"]
        for m in store.find_by_identity({"exchange_id": "SHFE", "order_sys_id": "  77"})
    ] == [second]
    assert store.find_by_identity({"front_id": "1"}) == []  # type-strict
    with pytest.raises(LiveStateError) as info:
        store.find_by_identity({})
    assert info.value.code == "identity_query_invalid"
    store.mark(first, "TERMINAL")
    assert [
        m["marker_id"] for m in store.find_by_identity({"client_order_id": "000000000001"})
    ] == []
    assert (
        len(store.find_by_identity({"client_order_id": "000000000001"}, include_history=True)) == 1
    )


def test_history_is_bounded(state):
    store = PendingCommandStore(state.strategy_dir, state.strategy_uuid, history_limit=3)
    ids = []
    for index in range(5):
        record = place_record(state.strategy_uuid, client_order_id=f"{index:012d}")
        marker_id = store.commit(record)
        assert store.mark(marker_id, "TERMINAL")
        ids.append(marker_id)
    assert [m["marker_id"] for m in store.history()] == ids[-3:]


def test_resolve_manually_only_for_unknown(state):
    store = state.pending
    marker_id = store.commit(place_record(state.strategy_uuid))
    with pytest.raises(LiveStateError) as info:
        store.resolve_manually(
            marker_id, operator="ops", conclusion="terminal_not_sent", evidence="ticket-1"
        )
    assert info.value.code == "marker_not_unknown"
    with pytest.raises(LiveStateError) as info:
        store.resolve_manually(
            "missing", operator="ops", conclusion="terminal_not_sent", evidence="ticket-1"
        )
    assert info.value.code == "marker_not_found"
    assert not any(
        r["event"] == "pending_manual_resolution" for r in read_audit(state.strategy_dir)
    )
    assert store.get(marker_id)["status"] == "PREPARED"


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"operator": "", "conclusion": "terminal_filled", "evidence": "t"}, "operator_required"),
        ({"operator": "ops", "conclusion": "force_unlock", "evidence": "t"}, "invalid_conclusion"),
        ({"operator": "ops", "conclusion": "terminal_filled", "evidence": []}, "evidence_required"),
        (
            {"operator": "ops", "conclusion": "terminal_filled", "evidence": " "},
            "evidence_required",
        ),
    ],
)
def test_resolve_manually_validates_arguments(state, kwargs, code):
    marker_id = state.pending.commit(place_record(state.strategy_uuid))
    state.pending.mark(marker_id, "UNKNOWN")
    with pytest.raises(LiveStateError) as info:
        state.pending.resolve_manually(marker_id, **kwargs)
    assert info.value.code == code
    assert state.pending.get(marker_id)["status"] == "UNKNOWN"


def test_resolve_manually_audits_and_moves_to_history(state):
    store = state.pending
    marker_id = store.commit(place_record(state.strategy_uuid), local_seq=5, bt_ref=8)
    assert store.mark(marker_id, "UNKNOWN")
    resolved = store.resolve_manually(
        marker_id,
        operator="ops-zhang",
        conclusion="terminal_cancelled",
        evidence=["ctp-query-20261105.json", "ticket-77"],
    )
    assert resolved["status"] == "TERMINAL"
    assert resolved["resolution"]["kind"] == "manual"
    assert resolved["resolution"]["conclusion"] == "terminal_cancelled"
    assert store.unknown() == [] and store.active() == []
    assert store.history()[-1]["marker_id"] == marker_id
    record = [
        r for r in read_audit(state.strategy_dir) if r["event"] == "pending_manual_resolution"
    ]
    assert len(record) == 1
    assert record[0]["operator"] == "ops-zhang"
    assert record[0]["evidence"] == ["ctp-query-20261105.json", "ticket-77"]
    assert record[0]["marker_id"] == marker_id
    assert record[0]["local_seq"] == 5
    assert "ts_utc" in record[0]


def test_resolve_manually_changes_nothing_if_audit_fails(state, monkeypatch):
    store = state.pending
    marker_id = store.commit(place_record(state.strategy_uuid))
    store.mark(marker_id, "UNKNOWN")

    def broken(*args, **kwargs):
        raise OSError("audit disk full")

    monkeypatch.setattr(pending_module, "append_audit", broken)
    with pytest.raises(OSError):
        store.resolve_manually(
            marker_id, operator="ops", conclusion="terminal_filled", evidence="t"
        )
    monkeypatch.undo()
    assert store.get(marker_id)["status"] == "UNKNOWN"


def test_store_rejects_pending_file_of_other_strategy(state):
    other = PendingCommandStore(state.strategy_dir, "1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b")
    assert other.commit(place_record("1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b")) is None
    from backtrader.live_state import LiveStateIdentityMismatch

    with pytest.raises(LiveStateIdentityMismatch):
        other.active()


def test_unknown_record_keys_are_preserved_not_dropped(state):
    marker_id = state.pending.commit(place_record(state.strategy_uuid, reservation_id="r-1"))
    assert state.pending.get(marker_id)["extra"] == {"reservation_id": "r-1"}


# -- settlement readback resolution (D62-29) ----------------------------------


def _settlement_marker(state, *, trading_day="20261106", status="UNKNOWN"):
    record = {
        "operation": "settlement_confirm",
        "host_scope": state.strategy_uuid,
        "exchange_name": "CTP___FUTURE",
        "trading_day": trading_day,
        "session_generation": 3,
    }
    marker_id = state.pending.commit(record)
    assert marker_id is not None
    if status != "PREPARED":
        assert state.pending.mark(marker_id, status, reason="settlement_outcome_unknown")
    return marker_id


def _readback(store, marker_id, **overrides):
    kwargs = {"exchange_name": "CTP___FUTURE", "trading_day": "20261106", "session_generation": 4}
    kwargs.update(overrides)
    return store.resolve_settlement_readback(marker_id, **kwargs)


def test_settlement_readback_closes_only_an_unknown_settlement_marker_of_its_day(state):
    store = state.pending
    unknown_place = store.commit(place_record(state.strategy_uuid))
    assert store.mark(unknown_place, "UNKNOWN")
    dispatched = _settlement_marker(state, status="DISPATCHED")
    marker_id = _settlement_marker(state)
    assert _readback(store, unknown_place, trading_day="20261105") is False  # an order
    assert _readback(store, dispatched) is False  # not UNKNOWN
    assert _readback(store, marker_id, trading_day="20261107") is False  # another day
    assert _readback(store, marker_id, exchange_name="OKX___SWAP") is False  # another route
    assert _readback(store, marker_id, session_generation=-1) is False
    assert _readback(store, "no-such-marker") is False
    assert store.get(unknown_place)["status"] == "UNKNOWN"
    assert store.get(dispatched)["status"] == "DISPATCHED"
    assert store.get(marker_id)["status"] == "UNKNOWN"
    assert not any(
        r["event"] == "pending_settlement_readback_resolution"
        for r in read_audit(state.strategy_dir)
    )

    assert _readback(store, marker_id) is True
    resolved = store.get(marker_id)
    assert resolved["status"] == "TERMINAL"
    assert resolved["facts"]["final_status"] == "confirmed"
    assert resolved["facts"]["resolution_evidence"] == "settlement_readback"
    assert resolved["facts"]["reason"] == "settlement_outcome_unknown"  # history kept
    assert resolved["resolution"]["kind"] == "settlement_readback"
    assert resolved["resolution"]["trading_day"] == "20261106"
    assert resolved["resolution"]["session_generation"] == 4
    assert [t["to"] for t in resolved["transitions"]][-2:] == ["UNKNOWN", "TERMINAL"]
    assert marker_id not in {m["marker_id"] for m in store.active()}
    (record,) = [
        r
        for r in read_audit(state.strategy_dir)
        if r["event"] == "pending_settlement_readback_resolution"
    ]
    assert record["marker_id"] == marker_id and record["evidence"] == "settlement_readback"
    assert _readback(store, marker_id) is False  # closed once


def test_settlement_readback_changes_nothing_if_audit_fails(state, monkeypatch):
    marker_id = _settlement_marker(state)

    def broken(*args, **kwargs):
        raise OSError("audit disk full")

    monkeypatch.setattr(pending_module, "append_audit", broken)
    assert _readback(state.pending, marker_id) is False
    monkeypatch.undo()
    assert state.pending.get(marker_id)["status"] == "UNKNOWN"


def test_settlement_readback_audits_a_failed_store(state, monkeypatch):
    marker_id = _settlement_marker(state)

    def broken(path, obj):
        raise OSError("disk full")

    monkeypatch.setattr(pending_module, "atomic_write_json", broken)
    assert _readback(state.pending, marker_id) is False
    monkeypatch.undo()
    assert state.pending.get(marker_id)["status"] == "UNKNOWN"
    events = [r["event"] for r in read_audit(state.strategy_dir)]
    assert events[-2:] == [
        "pending_settlement_readback_resolution",
        "pending_settlement_readback_resolution_failed",
    ]


def test_settlement_readback_records_a_definitive_unconfirmed_outcome(state):
    """A complete readback without a confirmation proves the earlier one absent."""
    store = state.pending
    marker_id = _settlement_marker(state)
    for invalid in ("unknown", "CONFIRMED", None, 1):
        assert _readback(store, marker_id, outcome=invalid) is False
    assert store.get(marker_id)["status"] == "UNKNOWN"
    assert _readback(store, marker_id, outcome="unconfirmed", trading_day="20261107") is False

    assert _readback(store, marker_id, outcome="unconfirmed") is True
    closed = store.get(marker_id)
    assert closed["status"] == "TERMINAL"
    assert closed["facts"]["final_status"] == "unconfirmed"
    assert closed["facts"]["resolution_evidence"] == "settlement_readback_unconfirmed"
    assert closed["resolution"]["kind"] == "settlement_readback_unconfirmed"
    assert closed["resolution"]["evidence"] == ["settlement_readback_unconfirmed"]
    (record,) = [
        r
        for r in read_audit(state.strategy_dir)
        if r["event"] == "pending_settlement_readback_resolution"
    ]
    assert record["outcome"] == "unconfirmed"
    assert record["evidence"] == "settlement_readback_unconfirmed"
    assert _readback(store, marker_id) is False  # closed once, whatever the outcome
