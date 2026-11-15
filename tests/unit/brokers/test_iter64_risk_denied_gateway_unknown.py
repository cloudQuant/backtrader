"""Risk denial alone cannot resolve a possibly existing Gateway command.

These tests exercise the BT projection with fake ports only; they do not
establish account identity, remote status authority, or a source cut.
"""

from types import SimpleNamespace

import pytest

from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamBrokerMixin
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import ready as ready
from tests.unit.live_state.test_gateway_pending import inputs as inputs


class _Broker(GatewayExecutionStreamBrokerMixin):
    def __init__(self):
        self.rejections = []

    def _gateway_finalize_rejection(self, binding, order, key, code, **kwargs):
        self.rejections.append((key, code, kwargs))
        order.status = order.Rejected


class _Host:
    def __init__(self):
        self._binding = SimpleNamespace(
            account_scope="account", strategy_scope="strategy", principal="strategy-principal"
        )
        self.intent = SimpleNamespace(digest="a" * 64)
        self.saved = []

    def load_delegated_command(self, key):
        return None

    def load_intent(self, key):
        return self.intent

    def save_delegated_command(self, key, **values):
        self.saved.append((key, values))


class _Api:
    def __init__(self, gateway_reply, risk_code):
        self.gateway_reply = gateway_reply
        self.risk_code = risk_code
        self.calls = []

    def delegated_command_status(self, route, key, **kwargs):
        self.calls.append("delegated_command_status")
        if isinstance(self.gateway_reply, Exception):
            raise self.gateway_reply
        return self.gateway_reply

    def risk_order_status(self, route, key, **kwargs):
        self.calls.append("risk_order_status")
        return SimpleNamespace(
            outcome="ANSWERED",
            answer=SimpleNamespace(outcome="DENIED", code=self.risk_code,
                                   gateway_code="STOP_NEW", reservation_id=None,
                                   permit_id=None, view_digest=None),
        )


def _case(gateway_reply, risk_code="risk_order_count_limit"):
    broker = _Broker()
    host = _Host()
    api = _Api(gateway_reply, risk_code)
    order = SimpleNamespace(status=1, Submitted=1, Rejected=8,
                            executed=SimpleNamespace(size=0))
    binding = SimpleNamespace(host=host, api=api, policy=SimpleNamespace(route="route"),
                              timeout=1, state="ACTIVE")
    return broker, binding, order, SimpleNamespace(orders={"key": order})


def _observation(**updates):
    fields = {"request_key": "key", "account_scope": "account", "strategy_scope": "strategy",
              "digest": "a" * 64, "actor_principal": "risk-principal", "reservation_id": "res",
              "state": "RESERVED", "version": 1}
    fields.update(updates)
    return SimpleNamespace(outcome="OBSERVED", observation=SimpleNamespace(**fields))


@pytest.mark.parametrize("risk_code", ["risk_order_count_limit", "risk_gateway_refused"])
@pytest.mark.parametrize("gateway_reply,expected_state", [
    (RuntimeError("unreachable"), "RISK_RECOVERY_PENDING"),
    (SimpleNamespace(outcome="UNKNOWN", observation=None), "RISK_RECOVERY_PENDING"),
    (SimpleNamespace(outcome="REQUEST_DENIED", observation=None, code="NOT_FOUND"),
     "RISK_RECOVERY_PENDING"),
    (_observation(digest="b" * 64), "RISK_BINDING_CONFLICT"),
])
def test_denied_risk_with_unproven_gateway_keeps_order_pending(gateway_reply, expected_state,
                                                              risk_code):
    broker, binding, order, notice = _case(gateway_reply, risk_code)
    assert broker._gateway_risk_step(binding, notice, "key") is False
    assert order.status == order.Submitted
    assert binding.state == expected_state
    assert broker.rejections == []
    assert binding.host.saved == []
    assert binding.api.calls == ["delegated_command_status", "risk_order_status"]


def test_observed_matching_gateway_command_conflicts_with_risk_denial():
    broker, binding, order, notice = _case(_observation())
    assert broker._gateway_risk_step(binding, notice, "key") is False
    assert order.status == order.Submitted
    assert broker.rejections == []
    assert binding.host.saved == []
    assert binding.state == "RISK_BINDING_CONFLICT"


def test_restart_denial_with_unavailable_gateway_keeps_order_and_instrument_blocked(
    state, ready, inputs, monkeypatch
):
    """Use a real BT broker and temporary pending host, with only fake ports."""
    from bt_api_base.risk_service_protocol import RiskOrderResult
    from bt_api_py.risk_service_client import RiskCallResult

    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import unknown_reserve_then_restart

    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch
    )
    venue.delegated_available = False
    monkeypatch.setattr(api, "risk_order_status", lambda route, k, **kw: RiskCallResult(
        "ANSWERED", RiskOrderResult(k, "DENIED", state="DENIED", code="risk_order_count_limit")
    ))
    broker.next()
    assert order.status == order.Submitted
    assert broker._gateway_stream_binding.state == "RISK_RECOVERY_PENDING"
    assert host.load_delegated_command(key) is None
    assert "reject:" + key not in host.local_order_notifications()
    assert not any(call == "release" or (isinstance(call, tuple) and call[0] == "dispatch")
                   for call in venue.calls)
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


@pytest.mark.parametrize("gateway_state,version", [
    ("RESERVED", 1), ("DISPATCHING", 2), ("SENT", 3), ("NOT_SENT", 3),
    ("UNKNOWN", 3), ("RELEASED", 2), ("EXPIRED", 2),
])
def test_denial_conflicts_with_every_gateway_state_across_restart(
    state, ready, inputs, monkeypatch, gateway_state, version
):
    from bt_api_base.risk_service_protocol import RiskOrderResult
    from bt_api_py.risk_service_client import RiskCallResult

    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import rebind, unknown_reserve_then_restart

    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch
    )
    venue.state, venue.version = gateway_state, version
    monkeypatch.setattr(api, "risk_order_status", lambda route, k, **kw: RiskCallResult(
        "ANSWERED", RiskOrderResult(k, "DENIED", state="DENIED", code="risk_order_count_limit")
    ))
    observed = []
    for _ in range(2):
        notice = broker._gateway_binding(strategy, required=True)
        broker._gateway_risk_step(broker._gateway_stream_binding, notice, key)
        observed.append((order.status, host.load_delegated_command(key)))
    assert observed == [(order.Submitted, None), (order.Submitted, None)]
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    order = next(o for o in broker.orders.values() if o.info.get("gateway_request_key") == key)
    notice = broker._gateway_binding(strategy, required=True)
    broker._gateway_risk_step(broker._gateway_stream_binding, notice, key)
    assert order.status == order.Submitted
    assert host.load_delegated_command(key) is None
    assert broker._gateway_stream_binding.state == "RISK_BINDING_CONFLICT"
    assert "reject:" + key not in host.local_order_notifications()
    assert not any(call == "release" or (isinstance(call, tuple) and call[0] == "dispatch")
                   for call in venue.calls)
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


@pytest.mark.parametrize("gateway_state,version", [
    ("RESERVED", 1), ("DISPATCHING", 2), ("SENT", 3), ("NOT_SENT", 3),
    ("UNKNOWN", 3), ("RELEASED", 2), ("EXPIRED", 2),
])
@pytest.mark.parametrize("later_risk", ["unavailable", "not_found", "reserved"])
def test_denial_then_changing_risk_status_cannot_clear_unknown_across_restart(
    state, ready, inputs, monkeypatch, gateway_state, version, later_risk
):
    from bt_api_base.risk_service_protocol import RiskOrderResult
    from bt_api_py.risk_service_client import RiskCallResult

    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import rebind, unknown_reserve_then_restart

    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch
    )
    venue.state, venue.version = gateway_state, version
    replies = [RiskCallResult(
        "ANSWERED", RiskOrderResult(key, "DENIED", state="DENIED", code="risk_order_count_limit")
    )]
    if later_risk == "unavailable":
        later = RiskCallResult("NOT_SENT", code="ROUTE_UNAVAILABLE")
    elif later_risk == "not_found":
        later = RiskCallResult("ANSWERED", RiskOrderResult(key, "NOT_FOUND"))
    else:
        later = RiskCallResult("ANSWERED", RiskOrderResult(
            key, "RESERVED", state="RESERVED", permit_id="permit-1",
            reservation_id="res-r", view_digest="d" * 64
        ))
    monkeypatch.setattr(api, "risk_order_status",
                        lambda route, k, **kw: replies.pop(0) if replies else later)
    observed = []
    for _ in range(2):
        notice = broker._gateway_binding(strategy, required=True)
        broker._gateway_risk_step(broker._gateway_stream_binding, notice, key)
        observed.append((order.status, host.load_delegated_command(key)))
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    restored = next(o for o in broker.orders.values() if o.info.get("gateway_request_key") == key)
    notice = broker._gateway_binding(strategy, required=True)
    broker._gateway_risk_step(broker._gateway_stream_binding, notice, key)
    observed.append((restored.status, host.load_delegated_command(key)))
    assert observed == [(order.Submitted, None)] * 3
    assert "reject:" + key not in host.local_order_notifications()
    assert not any(call == "release" or (isinstance(call, tuple) and call[0] == "dispatch")
                   for call in venue.calls)
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


def test_empty_stream_keeps_binding_conflict_visible(state, ready, inputs, monkeypatch):
    from dataclasses import replace

    from bt_api_base.risk_service_protocol import RiskOrderResult
    from bt_api_py.risk_service_client import RiskCallResult

    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import unknown_reserve_then_restart

    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch
    )
    original = venue.observation
    monkeypatch.setattr(venue, "observation", lambda k: replace(original(k), digest="b" * 64))
    monkeypatch.setattr(api, "risk_order_status", lambda route, k, **kw: RiskCallResult(
        "ANSWERED", RiskOrderResult(k, "DENIED", state="DENIED", code="risk_order_count_limit")
    ))
    broker.next()
    assert order.status == order.Submitted
    assert host.load_delegated_command(key) is None
    assert broker._gateway_stream_binding.state == "RISK_BINDING_CONFLICT"


@pytest.mark.parametrize("gateway_state", ["RELEASED", "EXPIRED"])
def test_unbound_gateway_terminal_without_risk_proof_does_not_finish_order(
    state, ready, inputs, monkeypatch, gateway_state
):
    from bt_api_base.risk_service_protocol import RiskOrderResult
    from bt_api_py.risk_service_client import RiskCallResult

    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import rebind, unknown_reserve_then_restart

    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch
    )
    venue.state, venue.version = gateway_state, 2
    monkeypatch.setattr(api, "risk_order_status", lambda route, k, **kw: RiskCallResult(
        "ANSWERED", RiskOrderResult(k, "NOT_FOUND")
    ))
    for _ in range(2):
        notice = broker._gateway_binding(strategy, required=True)
        broker._gateway_risk_step(broker._gateway_stream_binding, notice, key)
        assert order.status == order.Submitted
        assert host.load_delegated_command(key) is None
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    order = next(o for o in broker.orders.values() if o.info.get("gateway_request_key") == key)
    notice = broker._gateway_binding(strategy, required=True)
    broker._gateway_risk_step(broker._gateway_stream_binding, notice, key)
    assert order.status == order.Submitted
    assert host.load_delegated_command(key) is None
    assert broker._gateway_stream_binding.state == "RISK_RECOVERY_PENDING"
    assert not any(call == "release" or (isinstance(call, tuple) and call[0] == "dispatch")
                   for call in venue.calls)
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


def test_later_matching_status_does_not_resolve_conflict_or_mark_active(state, ready, inputs, monkeypatch):
    from bt_api_base.risk_service_protocol import RiskOrderResult
    from bt_api_py.risk_service_client import RiskCallResult

    import backtrader.brokers._btapi_gateway_stream as module
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import unknown_reserve_then_restart

    monkeypatch.setattr(module, "_IDLE_READ_INTERVAL_SECONDS", 0.0)
    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch
    )
    monkeypatch.setattr(api, "risk_order_status", lambda route, k, **kw: RiskCallResult(
        "ANSWERED", RiskOrderResult(k, "DENIED", state="DENIED", code="risk_order_count_limit")
    ))
    broker.next()
    assert broker._gateway_stream_binding.state == "RISK_BINDING_CONFLICT"
    monkeypatch.setattr(api, "risk_order_status", lambda route, k, **kw: RiskCallResult(
        "ANSWERED", RiskOrderResult(k, "RESERVED", state="RESERVED", permit_id="permit-1",
                                    reservation_id="res-r", view_digest="d" * 64)
    ))
    broker.next()
    assert broker._gateway_stream_binding.state == "RISK_RECOVERY_PENDING"
    assert host.load_delegated_command(key) is None
    assert order.status == order.Submitted


@pytest.mark.parametrize("per_order,expected", [
    (("RISK_RECOVERY_PENDING", "RISK_BINDING_CONFLICT"), "RISK_BINDING_CONFLICT"),
    (("RISK_BINDING_CONFLICT", "RISK_RECOVERY_PENDING"), "RISK_BINDING_CONFLICT"),
    (("RISK_RECOVERY_PENDING", None), "RISK_RECOVERY_PENDING"),
    ((None, None), "ACTIVE"),
])
def test_empty_stream_aggregates_risk_states_for_multiple_orders(per_order, expected):
    """Exercise the real stream loop with fake ports and two independent orders."""
    checkpoint = SimpleNamespace(applied_sequence=0, acknowledged_sequence=0,
                                 stored_sequence=0, epoch="epoch", revision=0)

    class Host:
        def load_execution_checkpoint(self):
            return checkpoint

        def local_order_notifications(self):
            return {}

        def read_execution_events(self, **kwargs):
            return ()

        def ingest_execution_result(self, result, **kwargs):
            return checkpoint

    class Stream:
        def read_after(self, *args, **kwargs):
            return SimpleNamespace(outcome="OBSERVED", page=None)

    class LoopBroker(GatewayExecutionStreamBrokerMixin):
        def _gateway_unreachable(self, **kwargs):
            return False

        def _gateway_session_stale(self, binding):
            return False

        def _gateway_stream_check(self, binding):
            pass

        def _gateway_binding(self, strategy, **kwargs):
            return notice

        def _gateway_risk_step(self, binding, notice, key):
            value = per_order[int(key)]
            if value is not None:
                binding.state = value
            return False

    order = SimpleNamespace(status=1, Completed=4, Canceled=5, Rejected=6, Expired=7, Margin=8,
                            info={"gateway_risk_routed": True})
    notice = SimpleNamespace(restored=None, fault=None, armed=None, receipt=None,
                             orders={"0": order, "1": order})
    broker = LoopBroker()
    broker._gateway_stream_binding = SimpleNamespace(
        next_idle_read=0, state="RISK_BINDING_CONFLICT", strategy=object(), host=Host(),
        stream=Stream(), limit=8, timeout=1, local_deferred=[]
    )
    broker._gateway_stream_next()
    assert broker._gateway_stream_binding.state == expected


def test_immediate_validated_refusal_still_rejects(state, ready, inputs, monkeypatch):
    """A direct validated refusal keeps its existing projection contract."""
    from bt_api_py.gateway_api import GatewayRiskRoutedResult

    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import bound

    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, "reserve_order", lambda *args, **kwargs: GatewayRiskRoutedResult(
        "REQUEST_DENIED", code="RISK_ORDER_COUNT_LIMIT", risk_code="risk_order_count_limit",
        risk_denied="risk_order_count_limit"
    ))
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    assert order.status == order.Rejected
    assert order.info.risk_denied == "risk_order_count_limit"
    assert host.local_order_notifications()["reject:" + key]["code"] == "RISK_ORDER_COUNT_LIMIT"
    assert not any(call == "release" or (isinstance(call, tuple) and call[0] == "dispatch")
                   for call in venue.calls)


@pytest.mark.parametrize("gateway_state,version", [
    ("RELEASED", 2), ("EXPIRED", 2), ("NOT_SENT", 3), ("UNKNOWN", 3),
])
def test_existing_permit_old_generation_never_releases_or_unblocks(
    state, ready, inputs, monkeypatch, gateway_state, version
):
    """A same-key read from another generation is not a not-sent proof."""
    from dataclasses import replace

    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import bound, rebind, submit

    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.dispatch = "UNKNOWN"
    order, key = submit(broker, strategy, data)
    original_record = host.load_delegated_command(key)
    assert original_record.gateway_state == "RESERVED"
    venue.calls.clear()
    original_observation = venue.observation
    monkeypatch.setattr(venue, "observation", lambda k: replace(
        original_observation(k), state=gateway_state, version=version,
        owner_generation="new-owner", reservation_generation="old-owner"
    ))
    observed = []
    for _ in range(2):
        notice = broker._gateway_binding(strategy, required=True)
        broker._gateway_risk_step(broker._gateway_stream_binding, notice, key)
        observed.append((order.status, host.load_delegated_command(key)))
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    restored = next(o for o in broker.orders.values() if o.info.get("gateway_request_key") == key)
    notice = broker._gateway_binding(strategy, required=True)
    broker._gateway_risk_step(broker._gateway_stream_binding, notice, key)
    observed.append((restored.status, host.load_delegated_command(key)))
    assert observed == [(order.Submitted, original_record)] * 3
    assert not any(call == "release" or (isinstance(call, tuple) and call[0] == "dispatch")
                   for call in venue.calls)
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


@pytest.mark.parametrize("gateway_state,version", [
    ("RELEASED", 2), ("EXPIRED", 2),
])
def test_unfinished_historical_terminal_record_does_not_finalize_on_rebind(
    state, ready, inputs, monkeypatch, gateway_state, version
):
    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import bound, rebind, submit

    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.dispatch = "UNKNOWN"
    order, key = submit(broker, strategy, data)
    record = host.load_delegated_command(key)
    host.save_delegated_command(key, reservation_id=record.reservation_id, digest=record.digest,
                                gateway_state=gateway_state, gateway_version=version)
    assert "cancel:" + key not in host.local_order_notifications()
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    restored = next(o for o in broker.orders.values() if o.info.get("gateway_request_key") == key)
    assert restored.status == restored.Submitted
    assert "cancel:" + key not in host.local_order_notifications()
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


@pytest.mark.parametrize("gateway_state,version", [
    ("RELEASED", 2), ("EXPIRED", 2),
])
def test_historical_terminal_notification_does_not_unblock_instrument(
    state, ready, inputs, monkeypatch, gateway_state, version
):
    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import bound, rebind, submit

    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.dispatch = "UNKNOWN"
    order, key = submit(broker, strategy, data)
    record = host.load_delegated_command(key)
    host.save_delegated_command(key, reservation_id=record.reservation_id, digest=record.digest,
                                gateway_state=gateway_state, gateway_version=version)
    broker._gateway_finalize_release(broker._gateway_stream_binding, order, key)
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


def test_historical_not_sent_record_does_not_unblock_instrument(state, ready, inputs, monkeypatch):
    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import bound, rebind, submit

    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.dispatch = "UNKNOWN"
    order, key = submit(broker, strategy, data)
    record = host.load_delegated_command(key)
    host.save_delegated_command(key, reservation_id=record.reservation_id, digest=record.digest,
                                gateway_state="NOT_SENT", gateway_version=3)
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


@pytest.mark.parametrize("gateway_state,version", [("DISPATCHING", 2), ("SENT", 3)])
@pytest.mark.parametrize("historical", [False, True])
def test_sent_or_dispatching_without_cross_generation_proof_still_blocks(
    state, ready, inputs, monkeypatch, gateway_state, version, historical
):
    from dataclasses import replace

    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import bound, rebind, submit

    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.dispatch = "UNKNOWN"
    order, key = submit(broker, strategy, data)
    record = host.load_delegated_command(key)
    if historical:
        host.save_delegated_command(key, reservation_id=record.reservation_id, digest=record.digest,
                                    gateway_state=gateway_state, gateway_version=version)
        data, broker, strategy = rebind(state, host, api, monkeypatch)
    else:
        original_observation = venue.observation
        monkeypatch.setattr(venue, "observation", lambda k: replace(
            original_observation(k), state=gateway_state, version=version,
            owner_generation="new-owner", reservation_generation="old-owner"
        ))
        notice = broker._gateway_binding(strategy, required=True)
        broker._gateway_risk_step(broker._gateway_stream_binding, notice, key)
    assert host.load_delegated_command(key).gateway_state == gateway_state
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


def test_historical_unbound_rejection_does_not_unblock_instrument(state, ready, inputs, monkeypatch):
    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
    from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import rebind, unknown_reserve_then_restart

    host, api, venue, data, broker, strategy, order, key = unknown_reserve_then_restart(
        state, ready, inputs, monkeypatch
    )
    # Recreate the historical projection without claiming the old order is safe.
    broker._gateway_finalize_rejection(broker._gateway_stream_binding, order, key, "OLD_DENIED")
    data, broker, strategy = rebind(state, host, api, monkeypatch)
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))


def test_terminal_status_gap_does_not_discard_matching_trade_event(state, ready, inputs, monkeypatch):
    from dataclasses import replace

    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import bound, fill, submit

    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.dispatch = "UNKNOWN"
    order, key = submit(broker, strategy, data)
    original_record = host.load_delegated_command(key)
    original_observation = venue.observation
    monkeypatch.setattr(venue, "observation", lambda k: replace(
        original_observation(k), state="RELEASED", version=2,
        owner_generation="new-owner", reservation_generation="old-owner"
    ))
    venue.events.append(fill(host, key))
    broker.next()
    assert order.status == order.Completed and order.executed.size == 1
    assert broker.positions["rb"].size == 1
    assert host.load_delegated_command(key) == original_record


def test_explicit_cancel_of_unproven_reserved_order_does_not_release(state, ready, inputs, monkeypatch):
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import bound, submit

    host, api, venue, data, broker, strategy = bound(state, ready, inputs, monkeypatch)
    venue.dispatch = "UNKNOWN"
    order, key = submit(broker, strategy, data)
    original_record = host.load_delegated_command(key)
    venue.calls.clear()
    broker._gateway_cancel_order(order)
    assert order.status == order.Submitted
    assert host.load_delegated_command(key) == original_record
    assert "release" not in venue.calls
    assert broker._gateway_stream_binding.state == "CANCEL_UNKNOWN"
