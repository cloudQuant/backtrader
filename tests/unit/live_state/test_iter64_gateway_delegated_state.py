"""Iteration 64: pending state v7 delegated command records (orders placed through Risk).

UNIT/FAKE: local state files only; no Gateway, Risk service or account.
"""
import json
from pathlib import Path

import pytest
from bt_api_base.direct_write_protocol import DirectExecutionEventKind
from bt_api_base.gateway_execution_stream_protocol import (
    GatewayExecutionObservation,
    GatewayExecutionStreamEvent,
    GatewayExecutionStreamPage,
    gateway_execution_consumer_ref,
)
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_py.gateway_delegated_cancel import (
    GatewayDelegatedCancelObservation,
    GatewayDelegatedCancelPlan,
)

from backtrader.live_state.atomic import LiveStateCorrupt
from backtrader.live_state.gateway_pending import GatewayPendingHost, has_unresolved_gateway_cancels
from backtrader.live_state.pending import validate_pending_state
from tests.unit.live_state.test_gateway_pending import inputs as inputs
from tests.unit.live_state.test_gateway_pending_cancel import prepare, upgrade

RISK = "risk-principal"
CONSUMER = gateway_execution_consumer_ref(principal_ref="principal-a", actor_ref="strategy-a",
    execution_domain_ref="paper:demo", account_scope="account-a", strategy_scope="strategy-a")


def v6(state, inputs):
    binding, _, _ = inputs
    prepare(state, inputs)  # an own order key-a, as an existing strategy has
    upgrade(state, binding)
    GatewayPendingHost.upgrade_for_execution(state.strategy_dir, state.strategy_uuid, binding,
                                             consumer_ref=CONSUMER)
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    host.upgrade_for_local_notifications()
    return host


@pytest.fixture
def risk_host(state, inputs):
    """A v7 host with one Risk-routed intent (no own record) beside the own key-a."""
    host = v6(state, inputs)
    host.upgrade_for_risk_routing()
    host.save_intent(inputs[2]("risk-key"), local_seq=2, bt_ref=2)
    return host


def prepared(host, **changes):
    intent = host.load_intent("risk-key")
    fields = {"reservation_id": "res-r", "digest": intent.digest, "permit_id": "permit-1",
              "view_digest": "d" * 64}
    fields.update(changes)
    return host.save_delegated_command("risk-key", **fields)


def raw(state):
    return json.loads(Path(state.pending.path).read_text(encoding="utf-8"))


# --- schema version and migration ----------------------------------------------------------


def test_v6_upgrades_to_v7_explicitly_and_keeps_everything(state, inputs):
    host = v6(state, inputs)
    before = raw(state)
    assert before["version"] == 6
    host.upgrade_for_risk_routing()
    after = raw(state)
    assert after["version"] == 7
    assert after["gateway"]["delegated_commands"] == {} == after["gateway"]["delegated_cancel_attempts"]
    for name in before["gateway"]:
        assert after["gateway"][name] == before["gateway"][name]
    assert after["active"] == before["active"] and after["history"] == before["history"]
    host.upgrade_for_risk_routing()  # idempotent
    assert raw(state) == after
    assert host.load_record("key-a") is not None  # the own order still opens


def test_older_files_need_the_earlier_upgrades_first(state, inputs):
    binding, _, _ = inputs
    prepare(state, inputs)
    upgrade(state, binding)
    host = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    with pytest.raises(ValueError, match="GATEWAY_RISK_ROUTING_UPGRADE_REQUIRED"):
        host.upgrade_for_risk_routing()
    assert raw(state)["version"] == 3


def test_a_version_newer_than_this_code_knows_is_refused(risk_host, state):
    data = raw(state)
    validate_pending_state(data, state.pending.path, data["strategy_uuid"])  # v7 opens
    data["version"] = 8
    with pytest.raises(LiveStateCorrupt, match="version_unsupported"):
        validate_pending_state(data, state.pending.path, data["strategy_uuid"])


def test_v7_keys_are_required_exactly(risk_host, state):
    data = raw(state)
    del data["gateway"]["delegated_cancel_attempts"]
    with pytest.raises(LiveStateCorrupt):
        validate_pending_state(data, state.pending.path, data["strategy_uuid"])


# --- delegated command record rules -----------------------------------------------------


def test_prepared_record_round_trips_and_the_principal_is_learned_once(risk_host):
    record = prepared(risk_host)
    assert (record.permit_id, record.actor_principal, record.dispatch_requested) == ("permit-1", None, False)
    learned = prepared(risk_host, actor_principal=RISK, gateway_state="RESERVED", gateway_version=1)
    assert learned.actor_principal == RISK
    with pytest.raises(ValueError, match="GATEWAY_DELEGATED_PRINCIPAL_CONFLICT"):
        prepared(risk_host, actor_principal="another-principal")
    assert risk_host.load_delegated_command("risk-key").actor_principal == RISK


def test_identity_permit_and_dispatch_request_never_change_back(risk_host):
    prepared(risk_host)
    with pytest.raises(ValueError, match="GATEWAY_DELEGATED_IDENTITY_CONFLICT"):
        prepared(risk_host, reservation_id="res-other")
    with pytest.raises(ValueError, match="GATEWAY_DELEGATED_PERMIT_CONFLICT"):
        prepared(risk_host, permit_id="permit-2")
    assert prepared(risk_host, dispatch_requested=True).dispatch_requested is True
    assert prepared(risk_host, dispatch_requested=False).dispatch_requested is True


def test_observed_state_only_moves_forward(risk_host):
    prepared(risk_host, gateway_state="RESERVED", gateway_version=1)
    assert prepared(risk_host, gateway_state="SENT", gateway_version=3).gateway_state == "SENT"
    # an older read never replaces a newer one
    assert prepared(risk_host, gateway_state="RESERVED", gateway_version=1).gateway_state == "SENT"
    with pytest.raises(ValueError, match="GATEWAY_DELEGATED_STATE_CONFLICT"):
        prepared(risk_host, gateway_state="UNKNOWN", gateway_version=3)


@pytest.mark.parametrize("changes", [
    {"digest": "0" * 64},                       # not this intent's payload
    {"actor_principal": "principal-a"},         # the strategy itself is never its delegate
    {"view_digest": "short"},
    {"gateway_state": "SENT", "gateway_version": 2},
    {"gateway_state": "MADE_UP", "gateway_version": 1},
])
def test_invalid_records_are_refused_before_any_write(risk_host, state, changes):
    before = raw(state)
    with pytest.raises(ValueError):
        prepared(risk_host, **changes)
    assert raw(state) == before


def test_a_key_with_an_own_record_cannot_also_be_delegated(risk_host, state):
    record = risk_host.load_record("key-a")
    intent = risk_host.load_intent("key-a")
    before = raw(state)
    with pytest.raises(ValueError):
        risk_host.save_delegated_command("key-a", reservation_id=record.reservation_id,
                                         digest=intent.digest)
    assert raw(state) == before


def test_records_need_a_known_intent_and_unique_reservations(risk_host, state, inputs):
    data = raw(state)
    data["gateway"]["delegated_commands"]["ghost"] = {
        "schema_version": 1, "request_key": "ghost", "reservation_id": "res-g", "digest": "a" * 64,
        "permit_id": None, "view_digest": None, "actor_principal": None,
        "dispatch_requested": False, "gateway_state": None, "gateway_version": None}
    with pytest.raises(LiveStateCorrupt):
        validate_pending_state(data, state.pending.path, data["strategy_uuid"])
    prepared(risk_host)
    risk_host.save_intent(inputs[2]("risk-key-2"), local_seq=3, bt_ref=3)
    intent = risk_host.load_intent("risk-key-2")
    with pytest.raises(ValueError):
        risk_host.save_delegated_command("risk-key-2", reservation_id="res-r", digest=intent.digest)


def test_released_proof_may_come_from_the_delegated_record_and_rejection_may_not(risk_host):
    from backtrader.live_state.gateway_order_state import _never_sent_final

    prepared(risk_host, gateway_state="RESERVED", gateway_version=1)
    with risk_host._store._lock():
        state = risk_host._store._load()
        assert not _never_sent_final(state["gateway"], state["gateway"]["intents"], "risk-key")
    prepared(risk_host, gateway_state="RELEASED", gateway_version=2)
    with risk_host._store._lock():
        state = risk_host._store._load()
        assert _never_sent_final(state["gateway"], state["gateway"]["intents"], "risk-key")
    # A reservation existed: a "never reserved" rejection notice is refused.
    with pytest.raises(ValueError, match="GATEWAY_REJECTION_NOT_PROVEN"):
        risk_host.save_rejected_order_notification("risk-key", bt_ref=2, snapshot={}, code="RISK_X")


# --- durable delegated cancel attempts (SDK delegated_cancel_host port) -----------------


def cancel_plan(host, route, **changes):
    binding = host._binding
    fields = dict(binding=binding, route=route, operation_id="cancel-1", request_key="risk-key",
                  reservation_id="res-r", digest=host.load_intent("risk-key").digest,
                  target_actor_principal=RISK)
    fields.update(changes)
    return GatewayDelegatedCancelPlan(**fields)


def cancel_observation(plan, state="REQUESTED", version=1):
    return GatewayDelegatedCancelObservation("account-a", "strategy-a", "principal-a", RISK,
        plan.request_key, plan.operation_id, "attempt-1", plan.reservation_id, plan.digest,
        state, version, "g1", "g1")


def test_delegated_cancel_plan_and_observation_persist_and_progress(risk_host, inputs, state):
    route = inputs[1]
    prepared(risk_host, actor_principal=RISK, gateway_state="SENT", gateway_version=3)
    plan = cancel_plan(risk_host, route)
    assert risk_host.save_delegated_cancel_plan(plan) == plan
    assert risk_host.load_delegated_cancel_plan("cancel-1") == plan
    # The first plan of an operation id wins; a conflicting one is never stored.
    assert risk_host.save_delegated_cancel_plan(cancel_plan(risk_host, route)) == plan
    assert has_unresolved_gateway_cancels(raw(state))
    requested = cancel_observation(plan)
    assert risk_host.save_delegated_cancel_observation("cancel-1", requested) == requested
    sent = cancel_observation(plan, "SENT", 3)
    assert risk_host.save_delegated_cancel_observation("cancel-1", sent) == sent
    assert risk_host.load_delegated_cancel_observation("cancel-1") == sent
    assert not has_unresolved_gateway_cancels(raw(state))
    with pytest.raises(ValueError, match="GATEWAY_DELEGATED_CANCEL_CONFLICT"):
        risk_host.save_delegated_cancel_observation("cancel-1", requested)  # never regresses


@pytest.mark.parametrize("changes", [{"target_actor_principal": "another-principal"},
                                     {"reservation_id": "res-other"}, {"request_key": "key-a"}])
def test_delegated_cancel_plan_must_name_the_recorded_delegated_command(risk_host, inputs, changes):
    prepared(risk_host, actor_principal=RISK)
    with pytest.raises(ValueError):
        risk_host.save_delegated_cancel_plan(cancel_plan(risk_host, inputs[1], **changes))
    assert risk_host.load_delegated_cancel_plan("cancel-1") is None


def test_cancel_plan_needs_a_learned_principal(risk_host, inputs):
    prepared(risk_host)  # principal not learned yet
    with pytest.raises(ValueError):
        risk_host.save_delegated_cancel_plan(cancel_plan(risk_host, inputs[1]))


# --- binding of returns in the strategy's own stream ---------------------------------------


def delegated_event(host, *, key="risk-key", principal=RISK, reservation="res-r", seq=5,
                    fact="a" * 64, account="account-a"):
    observation = GatewayExecutionObservation(
        account_scope=account, route="CTP___FUTURE",
        instrument=MarketInstrumentKey("ctp", "exchange", "paper", "future", "rb", "rb"),
        trading_day="20261108", kind=DirectExecutionEventKind.TRADE,
        native_identity_digest="c" * 64, identity_key_digests=("d" * 64, "e" * 64),
        binding_key_digests=("e" * 64,), venue_key_digest="d" * 64, trade_key_digest="b" * 64,
        side="buy", offset="open", order_quantity="1", filled_quantity="1", remaining_quantity="0",
        limit_price="10", trade_quantity="1", trade_price="10", trade_time="09:00:00")
    digest = host.load_intent(key).digest if host.load_intent(key) is not None else "f" * 64
    return GatewayExecutionStreamEvent(seq, key, reservation, digest, principal, fact, observation)


def ingest(host, events, *, binding=None):
    from bt_api_py.gateway_execution_stream_client import (
        GatewayExecutionReadContext,
        GatewayExecutionStreamClientResult,
    )

    binding = binding or host._binding
    checkpoint = host.load_execution_checkpoint()
    page = GatewayExecutionStreamPage(binding, CONSUMER, "e" * 64, 10, 0, False, tuple(events))
    result = GatewayExecutionStreamClientResult("OBSERVED", page=page,
        request_context=GatewayExecutionReadContext(binding, CONSUMER, checkpoint.stored_sequence,
                                                    checkpoint.epoch, 128))
    return host.ingest_execution_result(result, expected_revision=checkpoint.revision)


def test_return_of_a_risk_placed_order_binds_under_its_recorded_principal(risk_host):
    prepared(risk_host, actor_principal=RISK, dispatch_requested=True)
    checkpoint = ingest(risk_host, [delegated_event(risk_host)])
    assert checkpoint.stored_sequence == 5
    stored, = risk_host.read_execution_events(limit=8)
    assert (stored.request_key, stored.command_principal) == ("risk-key", RISK)


@pytest.mark.parametrize("case", ["wrong_principal", "strategy_principal", "unknown_key",
                                  "wrong_reservation", "principal_not_learned", "other_account",
                                  "other_strategy_page"])
def test_returns_that_do_not_match_the_delegated_record_never_bind(risk_host, state, case):
    prepared(risk_host, actor_principal=None if case == "principal_not_learned" else RISK)
    kwargs = {"wrong_principal": {"principal": "another-principal"},
              "strategy_principal": {"principal": "principal-a"},
              "unknown_key": {"key": "unknown-key"},
              "wrong_reservation": {"reservation": "res-other"},
              "other_account": {"account": "account-b"}}.get(case, {})
    event = delegated_event(risk_host, **kwargs)
    binding = None
    if case == "other_strategy_page":
        binding = GatewayCommandBinding("journal-a", "account-a", "strategy-b", "principal-a")
    before = raw(state)
    with pytest.raises(Exception):
        ingest(risk_host, [event], binding=binding)
    assert raw(state) == before
    assert risk_host.read_execution_events(limit=8) == ()


@pytest.mark.parametrize("case", ["other_account", "wrong_principal", "match"])
def test_the_delegated_binding_function_checks_each_field_itself(risk_host, case):
    """The binding check holds on its own, not only behind the page validation."""
    from backtrader.live_state.gateway_execution_state import _event

    prepared(risk_host, actor_principal=RISK)
    kwargs = {"other_account": {"account": "account-b"},
              "wrong_principal": {"principal": "another-principal"}, "match": {}}[case]
    event = delegated_event(risk_host, **kwargs)
    with risk_host._store._lock():
        state = risk_host._store._load()
    if case == "match":
        assert _event(event, state, risk_host._binding)["request_key"] == "risk-key"
        return
    with pytest.raises(ValueError, match="EXECUTION_EVENT_BINDING_MISMATCH"):
        _event(event, state, risk_host._binding)
