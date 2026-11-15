"""D67-15: sticky pause notices and the operator-only clear entry.

The notice goes through the existing opt-in notification layer; here a fake
callable proves the dedupe, the finite status and the non-blocking failure
semantics without any network, channel or credential.
"""

import json

import pytest

from backtrader.live_state import LiveStateError, WaitingOrderStore, read_audit
from backtrader.live_state import waiting as waiting_module
from backtrader.live_state import waiting_notify

from ._helpers import waiting_order

TARGET_DAY = "20261106"
TARGET_START = "2026-11-05T13:00:00+00:00"
TARGET_END = "2026-11-05T15:00:00+00:00"
CURRENT_REF = "ctp:calendar:2026.11.05.1"


class Recorder:
    """A fake pause notifier that records events and returns a finite status."""

    def __init__(self, status="accepted", raises=False):
        self.status = status
        self.raises = raises
        self.events = []

    def __call__(self, event):
        self.events.append(event)
        if self.raises:
            raise RuntimeError("channel exploded")
        return self.status


def paused_store(state, *, recorder=None):
    recorder = recorder or Recorder()
    store = WaitingOrderStore(state.strategy_dir, state.strategy_uuid, pause_notifier=recorder)
    waiting_id = store.add(waiting_order())
    assert store.record_calendar_disposition(
        waiting_id, "calendar_ref_changed", observed_calendar_ref="ctp:calendar:2026.11.06.1"
    )
    return store, waiting_id, recorder


def clear(store, waiting_id, **overrides):
    kwargs = {
        "operator": "op-1",
        "reason": "calendar report confirms the original target",
        "evidence": ["calendar report 2026-11-06"],
        "calendar_ref": CURRENT_REF,
        "trading_day": TARGET_DAY,
        "continuous_start_utc": TARGET_START,
        "session_end_utc": TARGET_END,
    }
    kwargs.update(overrides)
    return store.clear_calendar_pause(waiting_id, **kwargs)


def audit_events(state):
    return [record["event"] for record in read_audit(state.strategy_dir)]


def test_a_new_pause_emits_one_typed_bounded_notice(state):
    store, waiting_id, recorder = paused_store(state)
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert set(event) == {
        "kind",
        "strategy_uuid",
        "waiting_id",
        "local_seq",
        "bt_ref",
        "symbol",
        "exchange_name",
        "side",
        "size",
        "exectype",
        "status",
        "disposition",
        "observed_calendar_ref",
        "target_session",
        "version",
        "dedup_key",
    }
    assert event["kind"] == waiting_notify.PAUSE_EVENT_KIND
    assert event["waiting_id"] == waiting_id
    assert event["disposition"] == "calendar_ref_changed"
    assert event["version"] == "ctp:calendar:2026.11.06.1"
    assert event["target_session"]["calendar_ref"] == CURRENT_REF
    record = store.get(waiting_id)
    assert record["facts"]["pause_notification_status"] == "accepted"
    assert record["facts"]["pause_notification_at_utc"]
    assert record["status"] == "WAITING" and record["transitions"] == []


def test_notice_is_deduplicated_per_order_reason_and_version(state):
    store, waiting_id, recorder = paused_store(state)
    assert len(recorder.events) == 1
    # Same reason and version: no second notice, even though the call repeats.
    assert store.record_calendar_disposition(
        waiting_id, "calendar_ref_changed", observed_calendar_ref="ctp:calendar:2026.11.06.1"
    )
    assert len(recorder.events) == 1
    # A different calendar version is a different event.
    assert store.record_calendar_disposition(
        waiting_id, "calendar_ref_changed", observed_calendar_ref="ctp:calendar:2026.11.07.1"
    )
    assert len(recorder.events) == 2
    # A different reason is a different event.
    assert store.record_calendar_disposition(waiting_id, "calendar_unavailable")
    assert len(recorder.events) == 3
    # After an operator clear the same reason+version still must not re-notify:
    # the durable key list spans pause episodes on the same order.
    clear(store, waiting_id)
    assert store.record_calendar_disposition(
        waiting_id, "calendar_ref_changed", observed_calendar_ref="ctp:calendar:2026.11.06.1"
    )
    assert len(recorder.events) == 3


def test_notice_dedupe_spanning_a_clear_and_a_restart(state):
    store, waiting_id, recorder = paused_store(state)
    clear(store, waiting_id)
    restarted = Recorder()
    other = WaitingOrderStore(state.strategy_dir, state.strategy_uuid, pause_notifier=restarted)
    assert other.record_calendar_disposition(
        waiting_id, "calendar_ref_changed", observed_calendar_ref="ctp:calendar:2026.11.06.1"
    )
    assert restarted.events == []
    assert other.get(waiting_id)["facts"]["pause_notification_status"] == "accepted"


def test_notice_dedupe_survives_a_restart(state):
    store, waiting_id, recorder = paused_store(state)
    restarted = Recorder()
    other = WaitingOrderStore(state.strategy_dir, state.strategy_uuid, pause_notifier=restarted)
    assert other.record_calendar_disposition(
        waiting_id, "calendar_ref_changed", observed_calendar_ref="ctp:calendar:2026.11.06.1"
    )
    assert restarted.events == []
    assert other.get(waiting_id)["facts"]["pause_notification_status"] == "accepted"


def test_a_failed_notification_is_finite_and_changes_no_order_state(state):
    store, waiting_id, recorder = paused_store(state, recorder=Recorder(raises=True))
    assert len(recorder.events) == 1
    record = store.get(waiting_id)
    assert record["facts"]["pause_notification_status"] == "error"
    assert record["status"] == "WAITING"
    assert record["transitions"] == []
    assert record["target_session"]["calendar_ref"] == CURRENT_REF
    assert record["facts"]["calendar_disposition"] == "calendar_ref_changed"
    assert store.active()[0]["waiting_id"] == waiting_id
    assert state.pending.active() == []


def test_unknown_notifier_answer_is_recorded_as_error(state):
    store, waiting_id, _ = paused_store(state, recorder=Recorder(status="delivered"))
    assert store.get(waiting_id)["facts"]["pause_notification_status"] == "error"


def test_status_write_failure_leaves_a_visible_pending_status(state, monkeypatch):
    recorder = Recorder()
    store = WaitingOrderStore(state.strategy_dir, state.strategy_uuid, pause_notifier=recorder)
    waiting_id = store.add(waiting_order())
    original = waiting_module.atomic_write_json
    calls = {"count": 0}

    def flaky(path, obj):
        calls["count"] += 1
        if calls["count"] > 1:
            raise OSError("disk full")
        return original(path, obj)

    monkeypatch.setattr(waiting_module, "atomic_write_json", flaky)
    assert store.record_calendar_disposition(waiting_id, "calendar_unavailable")
    monkeypatch.undo()
    facts = store.get(waiting_id)["facts"]
    assert facts["calendar_disposition"] == "calendar_unavailable"
    assert facts["pause_notification_status"] == "pending"
    assert recorder.events  # the send did happen; only the status write failed


def test_default_notifier_maps_the_existing_send_result(monkeypatch):
    import backtrader.notifications as notifications

    captured = {}

    def fake_send(text, **kwargs):
        captured.update(text=text, **kwargs)
        return notifications.SendResult(accepted=False, mode="async", reason="not_configured")

    monkeypatch.setattr(notifications, "send_message", fake_send)
    event = waiting_notify.build_pause_event(
        {
            "waiting_id": "0b7f3c1e-2d4a-4f6b-8c1d-9e2f3a4b5c6d",
            "local_seq": 1,
            "bt_ref": 2,
            "symbol": "rb2601",
            "exchange_name": "CTP___FUTURE",
            "side": "buy",
            "size": 1,
            "exectype": "Limit",
            "status": "WAITING",
            "target_session": {
                "trading_day": TARGET_DAY,
                "continuous_start_utc": TARGET_START,
                "session_end_utc": TARGET_END,
                "calendar_ref": CURRENT_REF,
            },
        },
        "0b7f3c1e-2d4a-4f6b-8c1d-9e2f3a4b5c6d",
        "calendar_unavailable",
        None,
    )
    assert waiting_notify.notify_pause_event(event) == "not_configured"
    assert captured["level"] == "warning"
    assert captured["dedup_key"] == event["dedup_key"]
    assert len(captured["text"]) <= waiting_notify.PAUSE_TEXT_LIMIT
    assert "not a trading authorization" in captured["text"]


def test_default_notifier_never_raises(monkeypatch):
    import backtrader.notifications as notifications

    def boom(text, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(notifications, "send_message", boom)
    event = waiting_notify.build_pause_event(
        {
            "waiting_id": "0b7f3c1e-2d4a-4f6b-8c1d-9e2f3a4b5c6d",
            "local_seq": 1,
            "bt_ref": None,
            "symbol": "rb2601",
            "exchange_name": "CTP___FUTURE",
            "side": "buy",
            "size": 1,
            "exectype": "Market",
            "status": "WAITING",
            "target_session": {
                "trading_day": TARGET_DAY,
                "continuous_start_utc": TARGET_START,
                "session_end_utc": TARGET_END,
            },
        },
        "0b7f3c1e-2d4a-4f6b-8c1d-9e2f3a4b5c6d",
        "legacy_unbound",
        None,
    )
    assert waiting_notify.notify_pause_event(event) == "error"


def test_pause_text_is_bounded():
    order = {
        "waiting_id": "0b7f3c1e-2d4a-4f6b-8c1d-9e2f3a4b5c6d",
        "local_seq": 1,
        "bt_ref": 2,
        "symbol": "s" * 128,
        "exchange_name": "e" * 128,
        "side": "buy",
        "size": 1,
        "exectype": "Limit",
        "status": "WAITING",
        "target_session": {
            "trading_day": TARGET_DAY,
            "continuous_start_utc": TARGET_START,
            "session_end_utc": TARGET_END,
            "calendar_ref": "r" * 256,
        },
    }
    event = waiting_notify.build_pause_event(order, "u", "calendar_ref_changed", "o" * 256)
    text = waiting_notify.compose_pause_text(event)
    assert len(text) <= waiting_notify.PAUSE_TEXT_LIMIT
    assert text.endswith("[truncated]")


def test_clear_with_matching_evidence_changes_no_status_and_resends_nothing(state):
    store, waiting_id, recorder = paused_store(state)
    before = store.get(waiting_id)
    notices = len(recorder.events)
    result = clear(store, waiting_id)
    assert result["cleared"] is True
    assert result["previous_disposition"] == "calendar_ref_changed"
    after = store.get(waiting_id)
    assert after["status"] == "WAITING"
    assert after["target_session"] == before["target_session"]
    assert after["local_seq"] == before["local_seq"]
    assert after["waiting_id"] == waiting_id
    assert after["transitions"] == before["transitions"] == []
    assert "calendar_disposition" not in after["facts"]
    cleared = after["facts"]["calendar_pause_cleared"]
    assert cleared["operator"] == "op-1"
    assert cleared["evidence"] == ["calendar report 2026-11-06"]
    assert cleared["previous_disposition"] == "calendar_ref_changed"
    assert cleared["observed_calendar_ref"] == CURRENT_REF
    assert len(recorder.events) == notices  # clearing never notifies or sends
    assert state.pending.active() == []
    assert "waiting_pause_cleared" in audit_events(state)


def test_clear_accepts_an_equivalent_timezone_representation(state):
    store, waiting_id, _ = paused_store(state)
    result = clear(
        store,
        waiting_id,
        continuous_start_utc="2026-11-05T21:00:00+08:00",
        session_end_utc="2026-11-05T23:00:00+08:00",
    )
    assert result["cleared"] is True


@pytest.mark.parametrize(
    "overrides, code, detail",
    [
        ({"trading_day": "20261107"}, "calendar_disposition_invalid", "target_session_mismatch"),
        (
            {"continuous_start_utc": "2026-11-05T13:01:00+00:00"},
            "calendar_disposition_invalid",
            "target_session_mismatch",
        ),
        (
            {"session_end_utc": "2026-11-05T14:59:00+00:00"},
            "calendar_disposition_invalid",
            "target_session_mismatch",
        ),
        (
            {"continuous_start_utc": "2026-11-05T16:00:00+00:00"},
            "calendar_disposition_invalid",
            "target_session",
        ),
        ({"calendar_ref": ""}, "calendar_disposition_invalid", "calendar_ref"),
        ({"evidence": []}, "evidence_required", ""),
        ({"operator": ""}, "operator_required", ""),
        ({"reason": "   "}, "reason_required", ""),
        ({"calendar_ref": "r" * 257}, "calendar_disposition_invalid", "calendar_ref"),
    ],
)
def test_clear_without_proof_is_refused_and_stays_paused(state, overrides, code, detail):
    store, waiting_id, _ = paused_store(state)
    before = store.get(waiting_id)
    with pytest.raises(LiveStateError) as info:
        clear(store, waiting_id, **overrides)
    assert info.value.code == code
    assert info.value.detail == detail
    after = store.get(waiting_id)
    assert after["facts"]["calendar_disposition"] == "calendar_ref_changed"
    assert after["status"] == "WAITING"
    assert after["transitions"] == before["transitions"] == []


def test_clear_of_an_unknown_order_is_refused(state):
    store, _, _ = paused_store(state)
    with pytest.raises(LiveStateError) as info:
        clear(store, "missing")
    assert info.value.code == "waiting_invalid"
    assert info.value.detail == "waiting_id"


def test_clear_requires_an_actual_pause(state):
    store = WaitingOrderStore(state.strategy_dir, state.strategy_uuid, pause_notifier=Recorder())
    waiting_id = store.add(waiting_order())
    before = store.get(waiting_id)
    with pytest.raises(LiveStateError) as info:
        clear(store, waiting_id)
    assert info.value.code == "calendar_disposition_invalid"
    assert info.value.detail == "not_paused"
    assert store.get(waiting_id) == before


def test_a_legacy_unbound_record_can_never_be_proven_and_stays_paused(state):
    store = WaitingOrderStore(state.strategy_dir, state.strategy_uuid, pause_notifier=Recorder())
    waiting_id = store.add(waiting_order())
    raw = json.loads(open(store.path, "rb").read())
    raw["version"] = 1
    raw["orders"][waiting_id]["target_session"].pop("calendar_ref")
    with open(store.path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    assert store.record_calendar_disposition(waiting_id, "legacy_unbound")
    with pytest.raises(LiveStateError) as info:
        clear(store, waiting_id)
    assert info.value.code == "calendar_disposition_invalid"
    assert info.value.detail == "target_not_bound"
    record = store.get(waiting_id)
    assert record["facts"]["calendar_disposition"] == "legacy_unbound"
    assert record["status"] == "WAITING"
    assert "calendar_ref" not in record["target_session"]


def test_a_clear_is_durable_across_a_restart(state):
    store, waiting_id, _ = paused_store(state)
    clear(store, waiting_id)
    restarted = WaitingOrderStore(state.strategy_dir, state.strategy_uuid)
    record = restarted.get(waiting_id)
    assert "calendar_disposition" not in record["facts"]
    assert record["facts"]["calendar_pause_cleared"]["operator"] == "op-1"
    assert record["status"] == "WAITING"


def _cli(capsys, argv):
    from backtrader.live_state import cli

    code = cli.main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_cli_show_exposes_pause_and_migration_state(state, capsys):
    from .test_waiting_migration import install_fixture

    install_fixture(state)
    code, out = _cli(capsys, ["show", state.strategy_dir])
    assert code == 0 and out["ok"] is True
    assert out["waiting_migration"] is None
    assert out["waiting_orders"][0]["calendar_disposition"] is None

    assert state.waiting.migrate(operator="op", reason="7.07")["changed"] is True
    store, waiting_id, _ = paused_store(state)
    code, out = _cli(capsys, ["show", state.strategy_dir])
    assert code == 0
    assert out["waiting_migration"]["status"] == "complete"
    assert out["waiting_migration"]["source_version"] == 1
    view = next(item for item in out["waiting_orders"] if item["waiting_id"] == waiting_id)
    assert view["calendar_disposition"] == "calendar_ref_changed"
    assert view["pause_notification_status"] == "accepted"


def test_cli_waiting_clear_and_its_refusal(state, capsys):
    store, waiting_id, recorder = paused_store(state)
    code, out = _cli(
        capsys,
        [
            "waiting-clear",
            state.strategy_dir,
            waiting_id,
            "--operator",
            "op-1",
            "--reason",
            "report",
            "--evidence",
            "ref-1",
            "--calendar-ref",
            CURRENT_REF,
            "--trading-day",
            TARGET_DAY,
            "--window-start",
            TARGET_START,
            "--window-end",
            TARGET_END,
        ],
    )
    assert code == 0 and out["ok"] is True
    assert out["clear"]["cleared"] is True
    assert out["waiting"]["calendar_disposition"] is None
    assert out["waiting"]["pause_cleared_at_utc"]

    code, out = _cli(
        capsys,
        [
            "waiting-clear",
            state.strategy_dir,
            waiting_id,
            "--operator",
            "op-1",
            "--reason",
            "again",
            "--evidence",
            "ref-2",
            "--calendar-ref",
            CURRENT_REF,
            "--trading-day",
            TARGET_DAY,
            "--window-start",
            TARGET_START,
            "--window-end",
            TARGET_END,
        ],
    )
    assert code == 1 and out["ok"] is False
    assert out["error"] == "calendar_disposition_invalid"
    assert out["detail"] == "not_paused"
    assert len(recorder.events) == 1


def test_cli_waiting_migrate_recover_and_rollback(state, capsys):
    from .test_waiting_migration import install_fixture

    original = install_fixture(state)
    code, out = _cli(
        capsys,
        ["waiting-migrate", state.strategy_dir, "--operator", "op", "--reason", "67.07"],
    )
    assert code == 0 and out["status"] == "complete"
    code, out = _cli(
        capsys,
        ["waiting-migrate", state.strategy_dir, "--operator", "op", "--reason", "again"],
    )
    assert code == 0 and out["status"] == "already_current"
    code, out = _cli(
        capsys,
        ["waiting-rollback", state.strategy_dir, "--operator", "op", "--reason", "old program"],
    )
    assert code == 0 and out["status"] == "rolled_back" and out["changed"] is True
    assert open(state.waiting.path, "rb").read() == original
    code, out = _cli(
        capsys,
        ["waiting-recover", state.strategy_dir, "--operator", "op", "--reason", "check"],
    )
    assert code == 0 and out["status"] == "rolled_back" and out["recovery"] == "none"
