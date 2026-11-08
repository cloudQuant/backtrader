"""Synthetic persistent execution checkpoint tests; no native or account access."""

import json
from dataclasses import FrozenInstanceError, replace

import pytest
from bt_api_base.direct_write_protocol import DirectExecutionEventKind
from bt_api_base.gateway_execution_stream_protocol import (
    GatewayExecutionObservation,
    GatewayExecutionStreamEvent,
    GatewayExecutionStreamPage,
    GatewayExecutionStreamProgress,
    GatewayPlaceErrorAttribution,
    gateway_execution_consumer_ref,
)
from bt_api_base.market_protocol import MarketInstrumentKey

from backtrader.live_state import LiveStateError, rebind_identity
from backtrader.live_state import pending as pending_module
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.live_state.test_gateway_pending import data, host, observe
from tests.unit.live_state.test_gateway_pending import inputs as inputs
from tests.unit.live_state.test_gateway_pending_cancel import prepare, upgrade


@pytest.fixture
def ready(state, inputs):
    binding, _, _ = inputs
    prepare(state, inputs)
    upgrade(state, binding)
    consumer = gateway_execution_consumer_ref(
        principal_ref="principal-a",
        actor_ref="strategy-a",
        execution_domain_ref="paper:demo",
        account_scope="account-a",
        strategy_scope="strategy-a",
    )
    current = GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref=consumer
    )
    return current, binding, consumer


def make_event(host, seq=3, *, fact="a" * 64, trade="b" * 64, price="12"):
    record = host.load_record("key-a")
    binding_key = (record.strong_identity_key_digests or ("1" * 64,))[0]
    observation = GatewayExecutionObservation(
        account_scope="account-a",
        route="CTP___FUTURE",
        instrument=MarketInstrumentKey("ctp", "exchange", "paper", "future", "rb", "rb"),
        trading_day="20261108",
        kind=DirectExecutionEventKind.TRADE,
        native_identity_digest="c" * 64,
        identity_key_digests=tuple(sorted({binding_key, "d" * 64})),
        binding_key_digests=(binding_key,),
        venue_key_digest="d" * 64,
        trade_key_digest=trade,
        side="buy",
        offset="open",
        order_quantity="2",
        filled_quantity="1",
        remaining_quantity="1",
        limit_price="12",
        trade_quantity="1",
        trade_price=price,
        trade_time="09:00:00",
    )
    return GatewayExecutionStreamEvent(
        seq, "key-a", record.reservation_id, record.digest, "principal-a", fact, observation
    )


def page(binding, consumer, events=(), *, offered=10, ack=0, epoch="e" * 64):
    return GatewayExecutionStreamPage(binding, consumer, epoch, offered, ack, False, tuple(events))


def test_explicit_upgrade_preserves_v3_and_old_operations(state, inputs):
    from tests.unit.live_state.test_gateway_pending_cancel import plan, record

    binding, route, make = inputs
    existing = prepare(state, inputs, ("key-a", "key-b"))
    upgrade(state, binding)
    cancel_plan = plan(existing, route)
    cancel_record = record(cancel_plan)
    existing.save_cancel_plan(cancel_plan)
    existing.save_cancel_record(cancel_plan.operation_id, cancel_record)
    history_marker = existing.load_context("key-b").marker_id
    assert state.pending.mark(history_marker, "TERMINAL")
    original_intent = existing.load_intent("key-a")
    original_record = existing.load_record("key-a")
    original_context = existing.load_context("key-a")
    before = json.loads(data(state))
    assert (
        before["gateway"]["cancel_attempts"][cancel_plan.operation_id]["record"]["attempt_id"]
        == cancel_record.attempt_id
    )
    assert before["history"] and original_record.native_identity is not None
    consumer = "gexec:" + "a" * 64
    current = GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref=consumer
    )
    after = json.loads(data(state))
    assert after["version"] == 4
    assert {k: v for k, v in after["gateway"].items() if k != "execution"} == before["gateway"]
    assert after["active"] == before["active"] and after["history"] == before["history"]
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert reopened.load_cancel_plan(cancel_plan.operation_id) == cancel_plan
    assert reopened.load_cancel_record(cancel_plan.operation_id) == cancel_record
    assert reopened.load_intent("key-a") == original_intent
    assert reopened.load_record("key-a") == original_record
    assert reopened.load_context("key-a") == original_context
    current.save_intent(make("key-c"))
    assert current.load_intent("key-c").request_key == "key-c"
    checkpoint = current.load_execution_checkpoint()
    assert (checkpoint.epoch, checkpoint.revision, checkpoint.stored_events) == (None, 0, 0)
    with pytest.raises(FrozenInstanceError):
        checkpoint.revision = 4
    GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_cancellation(
        state.strategy_dir, state.strategy_uuid, binding, max_cancel_entries=10
    )
    assert json.loads(data(state))["version"] == 4


def test_sparse_ingest_projection_ack_and_reopen(state, ready):
    current, binding, consumer = ready
    events = (make_event(current, 3), make_event(current, 8, fact="f" * 64, trade="a" * 64))
    empty = page(binding, consumer, offered=12)
    c = current.ingest_execution_page(empty, expected_revision=0, after_sequence=0)
    assert (c.epoch, c.stored_sequence, c.revision) == ("e" * 64, 0, 1)
    c = current.ingest_execution_page(
        page(binding, consumer, events, offered=12), expected_revision=1, after_sequence=0
    )
    assert (c.stored_sequence, c.applied_sequence, c.acknowledged_sequence, c.stored_events) == (
        8,
        0,
        0,
        2,
    )
    assert [x.sequence for x in current.read_execution_events()] == [3, 8]
    snap = {"schema_version": 1, "state": {"orders": ["o"]}}
    c = current.commit_execution_projection(
        3, snap, expected_revision=2, expected_applied_sequence=0
    )
    snap["state"]["orders"].append("mutated")
    assert c.projection["state"]["orders"] == ["o"]
    c.projection["state"]["orders"].append("local")
    assert current.load_execution_checkpoint().projection["state"]["orders"] == ["o"]
    assert [x.sequence for x in current.read_execution_events()] == [8]
    progress = GatewayExecutionStreamProgress(binding, consumer, "e" * 64, 8, 3)
    c = current.record_execution_ack(progress)
    assert (c.stored_sequence, c.applied_sequence, c.acknowledged_sequence) == (8, 3, 3)
    assert current.record_execution_ack(progress) == c
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert reopened.load_execution_checkpoint() == c


def test_epoch_identity_ack_orphan_and_conflicts_are_atomic(state, ready):
    current, binding, consumer = ready
    event = make_event(current)
    before = data(state)
    invalids = [
        replace(event, command_principal="wrong"),
        replace(event, request_key="missing"),
        replace(event, command_digest="1" * 64),
        replace(event, reservation_id="wrong"),
        replace(event, observation=replace(event.observation, route="wrong")),
        replace(
            event,
            observation=replace(
                event.observation,
                instrument=replace(event.observation.instrument, native_symbol="wrong"),
            ),
        ),
    ]
    for invalid in invalids:
        with pytest.raises(ValueError):
            current.ingest_execution_page(
                page(binding, consumer, [invalid]), expected_revision=0, after_sequence=0
            )
        assert data(state) == before
    c = current.ingest_execution_page(
        page(binding, consumer, [event]), expected_revision=0, after_sequence=0
    )
    assert c.stored_sequence == 3
    before = data(state)
    with pytest.raises(ValueError, match="EPOCH"):
        current.ingest_execution_page(
            page(binding, consumer, epoch="f" * 64), expected_revision=1, after_sequence=3
        )
    with pytest.raises(ValueError, match="ACK_AHEAD"):
        current.ingest_execution_page(
            page(binding, consumer, ack=1), expected_revision=1, after_sequence=3
        )
    with pytest.raises(ValueError, match="FACT_CONFLICT"):
        current.ingest_execution_page(
            page(binding, consumer, [make_event(current, 6, price="13")]),
            expected_revision=1,
            after_sequence=3,
        )
    with pytest.raises(ValueError, match="TRADE_CONFLICT"):
        current.ingest_execution_page(
            page(binding, consumer, [make_event(current, 6, fact="f" * 64, price="13")]),
            expected_revision=1,
            after_sequence=3,
        )
    assert data(state) == before


def test_same_page_retry_and_cas_after_replacement_exception(state, ready, monkeypatch):
    current, binding, consumer = ready
    p = page(binding, consumer, [make_event(current)])
    original = pending_module.atomic_write_json

    def after_replace(*args):
        original(*args)
        raise OSError("after replace")

    monkeypatch.setattr(pending_module, "atomic_write_json", after_replace)
    with pytest.raises(OSError):
        current.ingest_execution_page(p, expected_revision=0, after_sequence=0)
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert (
        reopened.ingest_execution_page(p, expected_revision=0, after_sequence=0).stored_sequence
        == 3
    )
    assert reopened.load_execution_checkpoint().revision == 1
    with pytest.raises(ValueError, match="REVISION"):
        current.commit_execution_projection(
            3, {"schema_version": 1, "state": {}}, expected_revision=0, expected_applied_sequence=0
        )


def test_reserved_record_requires_original_identity_before_page_ingest(state, inputs):
    binding, _, make = inputs
    original = host(state, binding)
    intent = make()
    original.save_intent(intent)
    original.save_record(intent.request_key, observe(intent))
    upgrade(state, binding)
    consumer = "gexec:" + "a" * 64
    current = GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref=consumer
    )
    event = make_event(current)
    before = data(state)
    with pytest.raises(ValueError, match="GATEWAY_EXECUTION_IDENTITY_REQUIRED"):
        current.ingest_execution_page(
            page(binding, consumer, [event]), expected_revision=0, after_sequence=0
        )
    assert data(state) == before


def test_projection_validation_limits_cas_and_idempotence(state, ready, monkeypatch):
    current, binding, consumer = ready
    current.ingest_execution_page(
        page(binding, consumer, [make_event(current)]), expected_revision=0, after_sequence=0
    )
    before = data(state)
    shared = []
    invalid = [
        {"schema_version": True, "state": {}},
        {"schema_version": 1, "state": {"n": float("nan")}},
        {"schema_version": 1, "state": {"api_key": "private"}},
        {"schema_version": 1, "state": {"a": shared, "b": shared}},
        {"schema_version": 1, "state": {"x": (1, 2)}},
    ]
    for value in invalid:
        with pytest.raises((ValueError, LiveStateError)):
            current.commit_execution_projection(
                3, value, expected_revision=1, expected_applied_sequence=0
            )
        assert data(state) == before
    original = pending_module.atomic_write_json
    monkeypatch.setattr(
        pending_module, "atomic_write_json", lambda *_: (_ for _ in ()).throw(OSError("before"))
    )
    with pytest.raises(OSError):
        current.commit_execution_projection(
            3,
            {"schema_version": 1, "state": {"n": 1}},
            expected_revision=1,
            expected_applied_sequence=0,
        )
    assert data(state) == before
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    checkpoint = current.commit_execution_projection(
        3,
        {"schema_version": 1, "state": {"n": 1}},
        expected_revision=1,
        expected_applied_sequence=0,
    )
    assert (
        current.commit_execution_projection(
            3,
            {"schema_version": 1, "state": {"n": 1}},
            expected_revision=1,
            expected_applied_sequence=0,
        )
        == checkpoint
    )
    with pytest.raises(ValueError):
        current.commit_execution_projection(
            3,
            {"schema_version": 1, "state": {"n": True}},
            expected_revision=checkpoint.revision,
            expected_applied_sequence=3,
        )


def test_rebind_blocked_by_v4_markerless_intent(state, inputs):
    binding, _, make = inputs
    current = host(state, binding)
    current.save_intent(make())
    upgrade(state, binding)
    GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref="gexec:" + "a" * 64
    )
    with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
        rebind_identity(
            state.strategy_dir, mode="new_instance", operator="synthetic", reason="test"
        )


def test_rebind_blocked_by_v4_progress_until_applied_and_acked(state, inputs):
    from bt_api_base.direct_write_protocol import NativeOrderIdentity

    binding, _, make = inputs
    current = host(state, binding)
    intent = make()
    current.save_intent(intent)
    native = NativeOrderIdentity(
        "CTP___FUTURE", "ref-a", {"front_id": 1, "trading_day": "20261108"}, 7
    )
    current.save_record(
        intent.request_key,
        observe(intent, state="NOT_SENT", version=3, native=native, strong=("1" * 64,)),
    )
    upgrade(state, binding)
    consumer = "gexec:" + "a" * 64
    current = GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref=consumer
    )
    current.ingest_execution_page(
        page(binding, consumer, [make_event(current)]), expected_revision=0, after_sequence=0
    )
    with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
        rebind_identity(
            state.strategy_dir, mode="new_instance", operator="synthetic", reason="test"
        )
    current.commit_execution_projection(
        3, {"schema_version": 1, "state": {}}, expected_revision=1, expected_applied_sequence=0
    )
    with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
        rebind_identity(
            state.strategy_dir, mode="new_instance", operator="synthetic", reason="test"
        )
    current.record_execution_ack(GatewayExecutionStreamProgress(binding, consumer, "e" * 64, 3, 3))
    rebound = rebind_identity(
        state.strategy_dir, mode="new_instance", operator="synthetic", reason="test"
    )
    assert rebound.strategy_uuid != state.strategy_uuid


def test_duplicate_economic_trade_and_capacity_are_atomic(state, inputs):
    binding, _, _ = inputs
    prepare(state, inputs)
    upgrade(state, binding)
    consumer = "gexec:" + "a" * 64
    current = GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir,
        state.strategy_uuid,
        binding,
        consumer_ref=consumer,
        max_events=2,
        max_event_bytes=16 * 1024,
        max_projection_bytes=128,
    )
    first = make_event(current)
    duplicate = make_event(current, 7, fact="f" * 64)
    c = current.ingest_execution_page(
        page(binding, consumer, [first, duplicate]), expected_revision=0, after_sequence=0
    )
    assert c.stored_events == 2 and c.stored_sequence == 7
    before = data(state)
    with pytest.raises(ValueError, match="CAPACITY"):
        current.ingest_execution_page(
            page(binding, consumer, [make_event(current, 8, fact="2" * 64, trade="3" * 64)]),
            expected_revision=1,
            after_sequence=7,
        )
    with pytest.raises(ValueError, match="CAPACITY"):
        current.commit_execution_projection(
            3,
            {"schema_version": 1, "state": {"x": "x" * 200}},
            expected_revision=1,
            expected_applied_sequence=0,
        )
    assert data(state) == before


def test_cancel_attribution_plan_and_record_binding(state, inputs):
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind
    from bt_api_base.gateway_execution_stream_protocol import GatewayCancelErrorAttribution
    from tests.unit.live_state.test_gateway_pending_cancel import plan, record

    binding, route, _ = inputs
    current = prepare(state, inputs)
    upgrade(state, binding)
    cancel_plan = plan(current, route)
    current.save_cancel_plan(cancel_plan)
    consumer = "gexec:" + "a" * 64
    current = GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref=consumer
    )
    trade = make_event(current)
    # Base validates kind and fields; attribution digest remains an opaque label.
    observation = GatewayExecutionObservation(
        account_scope="account-a",
        route="CTP___FUTURE",
        instrument=trade.observation.instrument,
        trading_day="20261108",
        kind=DirectExecutionEventKind.CANCEL_ERROR,
        error_code="UNKNOWN",
    )
    attribution = GatewayCancelErrorAttribution(cancel_plan.operation_id, "attempt-a", "a" * 64)
    event = replace(trade, observation=observation, cancel_attribution=attribution)
    assert (
        current.ingest_execution_page(
            page(binding, consumer, [event]), expected_revision=0, after_sequence=0
        ).stored_sequence
        == 3
    )
    assert current.load_cancel_record(cancel_plan.operation_id) is None
    current.save_cancel_record(cancel_plan.operation_id, record(cancel_plan))
    conflict = replace(
        event,
        sequence=5,
        fact_digest="e" * 64,
        cancel_attribution=replace(attribution, attempt_id="other"),
    )
    before = data(state)
    with pytest.raises(ValueError, match="ATTRIBUTION"):
        current.ingest_execution_page(
            page(binding, consumer, [conflict]), expected_revision=1, after_sequence=3
        )
    assert data(state) == before


def test_ack_retry_and_projection_retry_after_replace(state, ready, monkeypatch):
    current, binding, consumer = ready
    current.ingest_execution_page(
        page(binding, consumer, [make_event(current)]), expected_revision=0, after_sequence=0
    )
    original = pending_module.atomic_write_json

    def after_replace(*args):
        original(*args)
        raise OSError("after replace")

    monkeypatch.setattr(pending_module, "atomic_write_json", after_replace)
    projection = {"schema_version": 1, "state": {}}
    with pytest.raises(OSError):
        current.commit_execution_projection(
            3, projection, expected_revision=1, expected_applied_sequence=0
        )
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    assert (
        current.commit_execution_projection(
            3, projection, expected_revision=1, expected_applied_sequence=0
        ).applied_sequence
        == 3
    )
    progress = GatewayExecutionStreamProgress(binding, consumer, "e" * 64, 3, 3)
    monkeypatch.setattr(pending_module, "atomic_write_json", after_replace)
    with pytest.raises(OSError):
        current.record_execution_ack(progress)
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    assert current.record_execution_ack(progress).acknowledged_sequence == 3


def test_v4_rebind_blocks_unresolved_cancel_even_without_marker(state, inputs):
    from bt_api_base.direct_write_protocol import NativeOrderIdentity
    from tests.unit.live_state.test_gateway_pending_cancel import plan

    binding, route, make = inputs
    current = host(state, binding)
    intent = make()
    current.save_intent(intent)
    native = NativeOrderIdentity(
        "CTP___FUTURE", "ref-a", {"front_id": 1, "trading_day": "20261108"}, 7
    )
    current.save_record(
        intent.request_key,
        observe(intent, state="NOT_SENT", version=3, native=native, strong=("1" * 64,)),
    )
    upgrade(state, binding)
    current.save_cancel_plan(plan(current, route))
    GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref="gexec:" + "a" * 64
    )
    with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
        rebind_identity(
            state.strategy_dir, mode="new_instance", operator="synthetic", reason="test"
        )


def test_two_hosts_cas_and_identical_retry_after_new_page(state, ready):
    current, binding, consumer = ready
    other = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    first = page(binding, consumer, [make_event(current)])
    second = page(binding, consumer, [make_event(current, 8, fact="f" * 64, trade="a" * 64)])
    current.ingest_execution_page(first, expected_revision=0, after_sequence=0)
    before = data(state)
    with pytest.raises(ValueError, match="REVISION"):
        other.ingest_execution_page(second, expected_revision=0, after_sequence=3)
    assert data(state) == before
    other.ingest_execution_page(second, expected_revision=1, after_sequence=3)
    assert (
        current.ingest_execution_page(first, expected_revision=0, after_sequence=0).stored_sequence
        == 8
    )
    changed = page(binding, consumer, [make_event(current)], offered=11)
    with pytest.raises(ValueError, match="REVISION"):
        current.ingest_execution_page(changed, expected_revision=0, after_sequence=0)


@pytest.mark.parametrize(
    "name,value",
    [
        ("max_events", True),
        ("max_events", 0),
        ("max_event_bytes", False),
        ("max_projection_bytes", -1),
    ],
)
def test_invalid_capacity_never_upgrades(state, inputs, name, value):
    binding, _, _ = inputs
    prepare(state, inputs)
    upgrade(state, binding)
    before = data(state)
    with pytest.raises(ValueError, match="CAPACITY"):
        GatewayPendingHost.upgrade_for_execution(
            state.strategy_dir,
            state.strategy_uuid,
            binding,
            consumer_ref="gexec:" + "a" * 64,
            **{name: value},
        )
    assert data(state) == before


def test_page_consumer_binding_and_ack_progress_conflicts(state, ready):
    current, binding, consumer = ready
    before = data(state)
    wrong_binding = replace(binding, journal_id="other")
    wrong_consumer = "gexec:" + "f" * 64
    with pytest.raises(ValueError):
        current.ingest_execution_page(
            page(wrong_binding, consumer), expected_revision=0, after_sequence=0
        )
    with pytest.raises(ValueError):
        current.ingest_execution_page(
            page(binding, wrong_consumer), expected_revision=0, after_sequence=0
        )
    with pytest.raises(ValueError):
        current.ingest_execution_page(
            page(binding, consumer, ack=1), expected_revision=0, after_sequence=0
        )
    assert data(state) == before
    current.ingest_execution_page(
        page(binding, consumer, [make_event(current)]), expected_revision=0, after_sequence=0
    )
    with pytest.raises(ValueError, match="ACK_AHEAD"):
        current.record_execution_ack(
            GatewayExecutionStreamProgress(binding, consumer, "e" * 64, 3, 3)
        )


def test_receipt_corruption_is_rejected_before_any_write(state, ready):
    from backtrader.live_state import LiveStateCorrupt

    current, binding, consumer = ready
    current.ingest_execution_page(
        page(binding, consumer, [make_event(current)]), expected_revision=0, after_sequence=0
    )
    raw = json.loads(data(state))
    raw["gateway"]["execution"]["receipts"][0]["digest"] = "1" * 64
    with open(state.pending.path, "w", encoding="utf-8") as stream:
        json.dump(raw, stream)
    before = data(state)
    with pytest.raises(LiveStateCorrupt):
        current.load_execution_checkpoint()
    assert data(state) == before


def test_place_error_attribution_is_preserved_as_an_unverified_label(state, ready):
    current, binding, consumer = ready
    trade = make_event(current)
    observation = GatewayExecutionObservation(
        account_scope="account-a",
        route="CTP___FUTURE",
        instrument=trade.observation.instrument,
        trading_day="20261108",
        kind=DirectExecutionEventKind.ORDER_ERROR,
        error_code="UNKNOWN",
    )
    event = replace(
        trade, observation=observation, place_attribution=GatewayPlaceErrorAttribution("1" * 64)
    )
    current.ingest_execution_page(
        page(binding, consumer, [event]), expected_revision=0, after_sequence=0
    )
    assert current.read_execution_events()[0].place_attribution.prepared_digest == "1" * 64


@pytest.mark.parametrize("stored,alias", [(1, True), (0, False), (1, 1.0)])
def test_projection_same_cursor_rejects_python_equal_different_json_types(ready, stored, alias):
    current, binding, consumer = ready
    current.ingest_execution_page(
        page(binding, consumer, [make_event(current)]), expected_revision=0, after_sequence=0
    )
    original = {"schema_version": 1, "state": {"value": stored}}
    checkpoint = current.commit_execution_projection(
        3, original, expected_revision=1, expected_applied_sequence=0
    )
    with pytest.raises(ValueError):
        current.commit_execution_projection(
            3,
            {"schema_version": 1, "state": {"value": alias}},
            expected_revision=checkpoint.revision,
            expected_applied_sequence=3,
        )
    assert current.load_execution_checkpoint().projection == original


def test_ingest_result_rejects_unbound_and_wrong_request_context_without_writes(state, ready):
    from bt_api_py.gateway_execution_stream_client import (
        GatewayExecutionReadContext,
        GatewayExecutionStreamClientResult,
    )

    current, binding, consumer = ready
    event = make_event(current)
    observed = page(binding, consumer, [event])
    valid = GatewayExecutionReadContext(binding, consumer, 0, None, 1)
    result = GatewayExecutionStreamClientResult("OBSERVED", page=observed, request_context=valid)
    before = data(state)
    wrong_contexts = [
        replace(valid, binding=replace(binding, journal_id="other")),
        replace(valid, consumer_ref="gexec:" + "f" * 64),
        replace(valid, expected_epoch="f" * 64),
        GatewayExecutionReadContext(binding, consumer, 1, "e" * 64, 1),
    ]
    wrong_results = [
        GatewayExecutionStreamClientResult("OBSERVED", page=observed),
        replace(result, outcome="UNKNOWN"),
        replace(result, code="not-empty"),
        replace(result, progress=GatewayExecutionStreamProgress(binding, consumer, "e" * 64, 0, 0)),
        *(replace(result, request_context=context) for context in wrong_contexts),
    ]
    for wrong in wrong_results:
        with pytest.raises(ValueError):
            current.ingest_execution_result(wrong, expected_revision=0)
        assert data(state) == before
    # A genuine-looking page from after=100 cannot be stored at local cursor 0.
    late = page(binding, consumer, [make_event(current, 101)], offered=101)
    context = GatewayExecutionReadContext(binding, consumer, 100, "e" * 64, 1)
    with pytest.raises(ValueError, match="SEQUENCE_CONFLICT"):
        current.ingest_execution_result(
            GatewayExecutionStreamClientResult("OBSERVED", page=late, request_context=context),
            expected_revision=0,
        )
    assert data(state) == before
    assert current.ingest_execution_result(result, expected_revision=0).stored_sequence == 3


def test_ingest_result_rejects_page_exceeding_actual_requested_limit(state, ready):
    from bt_api_py.gateway_execution_stream_client import (
        GatewayExecutionReadContext,
        GatewayExecutionStreamClientResult,
    )

    current, binding, consumer = ready
    first = make_event(current)
    second = make_event(current, 8, fact="f" * 64, trade="a" * 64)
    result = GatewayExecutionStreamClientResult(
        "OBSERVED",
        page=page(binding, consumer, [first, second]),
        request_context=GatewayExecutionReadContext(binding, consumer, 0, None, 1),
    )
    before = data(state)
    with pytest.raises(ValueError, match="CONTEXT_MISMATCH"):
        current.ingest_execution_result(result, expected_revision=0)
    assert data(state) == before


def test_strong_binding_subset_and_learned_alias(state, ready):
    current, binding, consumer = ready
    event = make_event(current)
    # Observation identity may contain new venue aliases and a richer native digest.
    assert event.observation.native_identity_digest == "c" * 64
    assert "d" * 64 in event.observation.identity_key_digests
    assert event.observation.binding_key_digests == ("1" * 64,)
    bad = replace(
        event,
        observation=replace(
            event.observation, identity_key_digests=("d" * 64,), binding_key_digests=("d" * 64,)
        ),
    )
    before = data(state)
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        current.ingest_execution_page(
            page(binding, consumer, [bad]), expected_revision=0, after_sequence=0
        )
    assert data(state) == before
    assert (
        current.ingest_execution_page(
            page(binding, consumer, [event]), expected_revision=0, after_sequence=0
        ).stored_sequence
        == 3
    )


def test_same_trade_key_cannot_be_attributed_to_another_command(state, inputs):
    binding, _, _ = inputs
    original = prepare(state, inputs, ("key-a", "key-b"))
    upgrade(state, binding)
    consumer = "gexec:" + "a" * 64
    current = GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref=consumer
    )
    first = make_event(current)
    other_record = current.load_record("key-b")
    second = replace(
        first,
        sequence=8,
        request_key="key-b",
        reservation_id=other_record.reservation_id,
        command_digest=other_record.digest,
        fact_digest="f" * 64,
        observation=replace(
            first.observation,
            identity_key_digests=tuple(
                sorted({other_record.strong_identity_key_digests[0], "d" * 64})
            ),
            binding_key_digests=(other_record.strong_identity_key_digests[0],),
        ),
    )
    before = data(state)
    with pytest.raises(ValueError, match="TRADE_BINDING_CONFLICT"):
        current.ingest_execution_page(
            page(binding, consumer, [first, second]), expected_revision=0, after_sequence=0
        )
    assert data(state) == before
    assert original.load_record("key-b") == other_record


@pytest.mark.parametrize("field", ["trade_quantity", "trade_price"])
def test_trade_key_missing_economics_is_finitely_rejected(state, ready, field):
    current, binding, consumer = ready
    event = make_event(current)
    before = data(state)
    with pytest.raises(ValueError):
        observation = replace(event.observation, **{field: None})
        current.ingest_execution_page(
            page(binding, consumer, [replace(event, observation=observation)]),
            expected_revision=0,
            after_sequence=0,
        )
    assert data(state) == before


def test_request_symbol_matches_native_symbol_not_canonical_instrument_id(state, ready):
    current, binding, consumer = ready
    first = make_event(current)
    instrument = replace(first.observation.instrument, instrument_id="canonical-rb")
    allowed = replace(first, observation=replace(first.observation, instrument=instrument))
    wrong = replace(
        allowed,
        observation=replace(
            allowed.observation, instrument=replace(instrument, native_symbol="different")
        ),
    )
    before = data(state)
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        current.ingest_execution_page(
            page(binding, consumer, [wrong]), expected_revision=0, after_sequence=0
        )
    assert data(state) == before
    stored = current.ingest_execution_page(
        page(binding, consumer, [allowed]), expected_revision=0, after_sequence=0
    )
    assert stored.stored_sequence == 3
    assert current.read_execution_events()[0].observation.instrument.instrument_id == "canonical-rb"
