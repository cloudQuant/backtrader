"""Focused fake tests for the single-route SDK batch coordinator."""

from copy import deepcopy
from dataclasses import dataclass

import pytest

from backtrader.service.store_event_batch import (
    StoreEventBatchCoordinator,
    StoreEventBatchError,
)


@dataclass
class _FakeBatch:
    batch_sequence: int
    payload: tuple[dict, ...]
    blocked_error_code: str | None = None
    exchange_name: str = "OKX___SWAP"
    event_epoch: str = "epoch-1"
    batch_id: str = "batch-1"
    events_reads: int = 0

    @property
    def events(self):
        self.events_reads += 1
        return deepcopy(self.payload)


class _FakeApi:
    def __init__(self, *poll_results, ack_result=False):
        self.token = object()
        self.poll_results = list(poll_results)
        self.ack_result = ack_result
        self.claim_calls = []
        self.poll_calls = []
        self.ack_calls = []
        self.ack_error = None
        self.claim_error = None

    def register_event_consumer(self, venue):
        self.claim_calls.append(venue)
        if self.claim_error is not None:
            raise self.claim_error
        return self.token

    def poll_event_batch(self, venue, token, **kwargs):
        self.poll_calls.append((venue, token, kwargs))
        result = self.poll_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def ack_event_batch(self, venue, token, batch):
        self.ack_calls.append((venue, token, batch))
        if self.ack_error is not None:
            raise self.ack_error
        return self.ack_result


class _SdkError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _coordinator(api):
    return StoreEventBatchCoordinator(
        api,
        "OKX___SWAP",
        max_raw_items=7,
        max_events=5,
        max_scan_items=11,
        coalesce_market_snapshots=("orderbook",),
    )


def test_claim_and_ack_use_exact_route_token_batch_and_configured_bounds():
    batch = _FakeBatch(1, ({"kind": "account", "n": 1}, {"kind": "order", "n": 2}))
    api = _FakeApi(batch, ack_result=True)
    coordinator = _coordinator(api)
    token = coordinator.claim()
    seen = []

    result = coordinator.drain_once(lambda venue, event: seen.append((venue, event["n"])))

    assert token is api.token
    assert api.claim_calls == ["OKX___SWAP"]
    assert seen == [("OKX___SWAP", 1), ("OKX___SWAP", 2)]
    assert batch.events_reads == 1
    assert len(api.poll_calls) == 1
    venue, poll_token, kwargs = api.poll_calls[0]
    assert venue == "OKX___SWAP"
    assert poll_token is token
    assert kwargs == {
        "max_raw_items": 7,
        "max_events": 5,
        "max_scan_items": 11,
        "coalesce_market_snapshots": ("orderbook",),
    }
    assert len(api.ack_calls) == 1
    assert api.ack_calls[0] == ("OKX___SWAP", token, batch)
    assert api.ack_calls[0][2] is batch
    assert result.status == "acked"
    assert result.dispatched == 2
    assert result.batch_sequence == 1
    assert result.continuation_required is True
    assert result.backlog_visible is True
    assert coordinator.state == "claimed"
    assert coordinator.outstanding_batch is None


@pytest.mark.parametrize(
    "name,value",
    (
        ("max_events", 0),
        ("max_events", -1),
        ("max_events", True),
        ("max_events", 1025),
        ("max_scan_items", 0),
        ("max_scan_items", -1),
        ("max_scan_items", False),
        ("max_scan_items", 1025),
    ),
)
def test_zero_or_invalid_event_scan_budget_is_rejected_before_claim(name, value):
    api = _FakeApi(None)

    with pytest.raises(ValueError):
        StoreEventBatchCoordinator(api, "OKX___SWAP", **{name: value})

    assert api.claim_calls == []
    assert api.poll_calls == []


@pytest.mark.parametrize(
    "value",
    (-1, True, False, 1025),
)
def test_raw_budget_rejects_negative_bool_and_over_cap(value):
    with pytest.raises(ValueError):
        StoreEventBatchCoordinator(_FakeApi(None), "OKX___SWAP", max_raw_items=value)


@pytest.mark.parametrize("value", (None, 0, 1, 1024))
def test_raw_budget_accepts_sdk_modes_while_scan_budget_stays_positive(value):
    coordinator = StoreEventBatchCoordinator(
        _FakeApi(None), "OKX___SWAP", max_raw_items=value
    )

    assert coordinator.max_raw_items == value
    assert coordinator.max_events > 0
    assert coordinator.max_scan_items > 0


def test_budget_properties_cannot_be_changed_after_validation():
    coordinator = StoreEventBatchCoordinator(_FakeApi(None), "OKX___SWAP")

    with pytest.raises(AttributeError):
        coordinator.max_events = 0


def test_zero_raw_budget_can_drain_normalized_batch():
    batch = _FakeBatch(1, ({"kind": "account", "n": 1},))
    api = _FakeApi(batch)
    coordinator = StoreEventBatchCoordinator(api, "OKX___SWAP", max_raw_items=0)
    coordinator.claim()
    seen = []

    result = coordinator.drain_once(lambda _venue, event: seen.append(event["n"]))

    assert seen == [1]
    assert result.status == "acked"
    assert api.poll_calls[0][2]["max_raw_items"] == 0


def test_successive_batches_must_advance_sequence_in_the_same_epoch():
    first = _FakeBatch(1, ({"kind": "account", "n": 1},))
    second = _FakeBatch(
        2,
        ({"kind": "account", "n": 2},),
        event_epoch=first.event_epoch,
        batch_id="batch-2",
    )
    api = _FakeApi(first, second)
    coordinator = _coordinator(api)
    coordinator.claim()
    seen = []

    result1 = coordinator.drain_once(lambda _venue, event: seen.append(event["n"]))
    result2 = coordinator.drain_once(lambda _venue, event: seen.append(event["n"]))

    assert result1.batch_sequence == 1
    assert result2.batch_sequence == 2
    assert seen == [1, 2]
    assert len(api.ack_calls) == 2


def test_successive_batch_with_changed_epoch_is_rejected_before_dispatch():
    first = _FakeBatch(1, ({"kind": "account", "n": 1},))
    second = _FakeBatch(
        2,
        ({"kind": "account", "n": 2},),
        event_epoch="epoch-replaced",
        batch_id="batch-2",
    )
    api = _FakeApi(first, second)
    coordinator = _coordinator(api)
    coordinator.claim()
    seen = []

    coordinator.drain_once(lambda _venue, event: seen.append(event["n"]))
    with pytest.raises(StoreEventBatchError) as caught:
        coordinator.drain_once(lambda _venue, event: seen.append(event["n"]))

    assert caught.value.code == "event_batch_binding_invalid"
    assert coordinator.state == "batch_binding_blocked"
    assert coordinator.outstanding_batch is second
    assert second.events_reads == 0
    assert seen == [1]
    assert len(api.ack_calls) == 1


def test_preflight_mutation_cannot_change_the_detached_dispatch_payload():
    batch = _FakeBatch(1, ({"kind": "account", "nested": {"value": 7}},))
    api = _FakeApi(batch)
    coordinator = _coordinator(api)
    coordinator.claim()
    dispatched = []

    def mutating_preflight(_venue, events):
        events[0]["kind"] = "corrupted"
        events[0]["nested"]["value"] = 99

    coordinator.drain_once(
        lambda _venue, event: dispatched.append(deepcopy(event)),
        preflight_events=mutating_preflight,
    )

    assert dispatched == [{"kind": "account", "nested": {"value": 7}}]
    assert batch.payload == ({"kind": "account", "nested": {"value": 7}},)


def test_zero_raw_budget_backlog_blocks_without_an_automatic_spin():
    api = _FakeApi(_SdkError("event_batch_raw_budget_exhausted"))
    coordinator = StoreEventBatchCoordinator(api, "OKX___SWAP", max_raw_items=0)
    coordinator.claim()

    result = coordinator.drain_once(lambda _venue, _event: pytest.fail("no batch expected"))

    assert result.status == "raw_budget_blocked"
    assert result.backlog_visible is True
    assert result.continuation_required is False
    assert coordinator.state == "raw_budget_blocked"
    with pytest.raises(StoreEventBatchError):
        coordinator.drain_once(lambda _venue, _event: pytest.fail("poll must not repeat"))
    assert len(api.poll_calls) == 1


def test_mutated_zero_event_budget_is_rejected_before_sdk_poll():
    api = _FakeApi(None)
    coordinator = _coordinator(api)
    coordinator.claim()
    coordinator._max_scan_items = 0

    with pytest.raises(StoreEventBatchError) as caught:
        coordinator.drain_once(lambda _venue, _event: pytest.fail("no poll expected"))

    assert caught.value.code == "event_batch_budget_invalid"
    assert api.poll_calls == []
    assert coordinator.state == "poll_blocked"


def test_idle_none_is_only_a_snapshot_not_a_quiescence_claim():
    api = _FakeApi(None)
    coordinator = _coordinator(api)
    coordinator.claim()

    result = coordinator.drain_once(lambda _venue, _event: pytest.fail("no event expected"))

    assert result.status == "idle_snapshot"
    assert result.backlog_visible is False
    assert result.continuation_required is False
    assert coordinator.state == "claimed"


def test_keyboard_interrupt_during_claim_is_preserved_with_unknown_claim_state():
    api = _FakeApi(None)
    api.claim_error = KeyboardInterrupt()
    coordinator = _coordinator(api)

    with pytest.raises(KeyboardInterrupt):
        coordinator.claim()

    assert coordinator.state == "claim_unknown"
    assert api.claim_calls == ["OKX___SWAP"]
    with pytest.raises(StoreEventBatchError):
        coordinator.claim()
    assert api.claim_calls == ["OKX___SWAP"]


def test_keyboard_interrupt_during_poll_is_preserved_and_not_repolled():
    api = _FakeApi(KeyboardInterrupt())
    coordinator = _coordinator(api)
    coordinator.claim()

    with pytest.raises(KeyboardInterrupt):
        coordinator.drain_once(lambda _venue, _event: pytest.fail("no batch expected"))

    assert coordinator.state == "poll_blocked"
    assert len(api.poll_calls) == 1
    assert api.ack_calls == []
    with pytest.raises(StoreEventBatchError):
        coordinator.drain_once(lambda _venue, _event: pytest.fail("no repoll expected"))
    assert len(api.poll_calls) == 1


@pytest.mark.parametrize(
    "code",
    (
        "event_batch_scan_budget_exhausted",
        "event_batch_raw_budget_exhausted",
        "event_batch_backlog_pending",
    ),
)
def test_budget_signals_request_bounded_continuation_without_poll_loop(code):
    api = _FakeApi(_SdkError(code))
    coordinator = _coordinator(api)
    coordinator.claim()

    result = coordinator.drain_once(lambda _venue, _event: pytest.fail("no event expected"))

    assert result.status == "continuation_required"
    assert result.continuation_required is True
    assert result.backlog_visible is True
    assert result.blocked_error_code == code
    assert len(api.poll_calls) == 1
    assert api.ack_calls == []
    assert coordinator.state == "claimed"


def test_normalization_error_is_not_mistaken_for_a_budget_signal():
    api = _FakeApi(_SdkError("event_payload_invalid"))
    coordinator = _coordinator(api)
    coordinator.claim()

    with pytest.raises(StoreEventBatchError) as caught:
        coordinator.drain_once(lambda _venue, _event: pytest.fail("no event expected"))

    assert caught.value.code == "event_payload_invalid"
    assert caught.value.phase == "poll"
    assert coordinator.state == "poll_blocked"
    assert api.ack_calls == []


def test_completed_prefix_cursor_and_current_partial_effect_fail_closed():
    batch = _FakeBatch(
        1,
        (
            {"kind": "account", "n": 1},
            {"kind": "position", "n": 2},
            {"kind": "order", "n": 3},
        ),
    )
    api = _FakeApi(batch)
    coordinator = _coordinator(api)
    coordinator.claim()
    seen = []

    def dispatch(_venue, event):
        seen.append(event["n"])
        if event["n"] == 2:
            # The callback may have projected one effect before this fails.
            raise _SdkError("projection_failed")

    with pytest.raises(StoreEventBatchError) as caught:
        coordinator.drain_once(dispatch)

    assert caught.value.code == "projection_failed"
    assert caught.value.phase == "dispatch_unknown"
    assert caught.value.event_index == 1
    assert seen == [1, 2]
    assert coordinator.next_event_index == 1
    assert coordinator.outstanding_batch is batch
    assert batch.events_reads == 1
    assert api.ack_calls == []

    with pytest.raises(StoreEventBatchError) as blocked:
        coordinator.drain_once(lambda _venue, event: seen.append(event["n"]))

    assert blocked.value.code == "store_event_batch_fail_closed"
    assert coordinator.state == "dispatch_unknown"
    assert len(api.poll_calls) == 1
    assert seen == [1, 2]


def test_ack_exception_is_unknown_and_never_replays_effects_or_ack():
    batch = _FakeBatch(1, ({"kind": "trade", "n": 1},))
    api = _FakeApi(batch)
    api.ack_error = _SdkError("ack_transport_uncertain")
    coordinator = _coordinator(api)
    coordinator.claim()
    seen = []

    with pytest.raises(StoreEventBatchError) as caught:
        coordinator.drain_once(lambda _venue, event: seen.append(event["n"]))

    assert caught.value.code == "ack_transport_uncertain"
    assert caught.value.phase == "ack_unknown"
    assert caught.value.event_index == 1
    assert coordinator.state == "ack_unknown"
    assert coordinator.outstanding_batch is batch
    assert seen == [1]
    assert len(api.poll_calls) == 1
    assert len(api.ack_calls) == 1

    with pytest.raises(StoreEventBatchError) as blocked:
        coordinator.drain_once(lambda _venue, event: seen.append(event["n"]))

    assert blocked.value.code == "store_event_batch_fail_closed"
    assert len(api.poll_calls) == 1
    assert len(api.ack_calls) == 1
    assert seen == [1]


@pytest.mark.parametrize(
    "batch",
    (
        _FakeBatch(1, ({"kind": "account"},), exchange_name="BINANCE___SPOT"),
        _FakeBatch(0, ({"kind": "account"},)),
        _FakeBatch(2, ({"kind": "account"},)),
        _FakeBatch(True, ({"kind": "account"},)),
    ),
)
def test_wrong_route_or_invalid_sequence_is_rejected_before_side_effects(batch):
    api = _FakeApi(batch)
    coordinator = _coordinator(api)
    coordinator.claim()
    dispatched = []

    with pytest.raises(StoreEventBatchError) as caught:
        coordinator.drain_once(lambda _venue, event: dispatched.append(event))

    assert caught.value.code == "event_batch_binding_invalid"
    assert caught.value.phase == "batch_binding"
    assert coordinator.state == "batch_binding_blocked"
    assert coordinator.outstanding_batch is batch
    assert batch.events_reads == 0
    assert dispatched == []
    assert api.ack_calls == []


def test_keyboard_interrupt_during_dispatch_is_preserved_after_unknown_state():
    batch = _FakeBatch(1, ({"kind": "account"},))
    api = _FakeApi(batch)
    coordinator = _coordinator(api)
    coordinator.claim()
    seen = []

    def interrupt_after_possible_effect(_venue, _event):
        seen.append("effect may have happened")
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        coordinator.drain_once(interrupt_after_possible_effect)

    assert coordinator.state == "dispatch_unknown"
    assert coordinator.outstanding_batch is batch
    assert coordinator.next_event_index == 0
    assert len(api.poll_calls) == 1
    assert api.ack_calls == []
    with pytest.raises(StoreEventBatchError):
        coordinator.drain_once(lambda _venue, _event: seen.append("replayed"))
    assert seen == ["effect may have happened"]


def test_system_exit_during_ack_is_preserved_after_ack_unknown_state():
    batch = _FakeBatch(1, ({"kind": "order"},))
    api = _FakeApi(batch)
    coordinator = _coordinator(api)
    coordinator.claim()
    api.ack_error = SystemExit(3)
    seen = []

    with pytest.raises(SystemExit):
        coordinator.drain_once(lambda _venue, _event: seen.append("projected"))

    assert coordinator.state == "ack_unknown"
    assert coordinator.outstanding_batch is batch
    assert len(api.poll_calls) == 1
    assert len(api.ack_calls) == 1
    with pytest.raises(StoreEventBatchError):
        coordinator.drain_once(lambda _venue, _event: seen.append("replayed"))
    assert seen == ["projected"]


def test_valid_prefix_with_blocked_normalization_is_acked_and_scheduled():
    batch = _FakeBatch(
        1,
        ({"kind": "account", "n": 1},),
        blocked_error_code="event_payload_invalid",
    )
    api = _FakeApi(batch, ack_result=False)
    coordinator = _coordinator(api)
    coordinator.claim()
    seen = []

    result = coordinator.drain_once(lambda _venue, event: seen.append(event["n"]))

    assert seen == [1]
    assert api.ack_calls[0][2] is batch
    assert result.status == "prefix_acked_blocked"
    assert result.blocked_error_code == "event_payload_invalid"
    assert result.backlog_visible is False
    # Retry of the retained normalization failure is a later, bounded turn.
    assert result.continuation_required is True
    assert coordinator.state == "claimed"


def test_preflight_failure_holds_exact_batch_without_dispatch_or_ack():
    batch = _FakeBatch(1, ({"kind": "account"},))
    api = _FakeApi(batch)
    coordinator = _coordinator(api)
    coordinator.claim()
    dispatched = []

    with pytest.raises(StoreEventBatchError) as caught:
        coordinator.drain_once(
            lambda _venue, event: dispatched.append(event),
            preflight_events=lambda _venue, _events: (_ for _ in ()).throw(
                _SdkError("route_contract_missing")
            ),
        )

    assert caught.value.code == "route_contract_missing"
    assert caught.value.phase == "preflight"
    assert coordinator.state == "preflight_blocked"
    assert coordinator.outstanding_batch is batch
    assert batch.events_reads == 1
    assert dispatched == []
    assert api.ack_calls == []
