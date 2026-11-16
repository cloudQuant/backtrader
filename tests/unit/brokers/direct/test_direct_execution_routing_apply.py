"""Iteration 65.07: apply the Execution parent projection to routed BT orders.

UNIT/FAKE. The fake facade mirrors the SDK ``make_order`` wrap (real
``ExecutionOrderRouter`` over a temporary SQLite file) and adds an injected
read-only parent facts port. Nothing here starts a service, opens a socket,
contacts a provider or an account. The write-side reply is unverified. Injected
read-side facts exercise projection behavior only; they prove no source, Gateway
acceptance, Risk approval or venue fill.
"""

from __future__ import annotations

import collections
import sqlite3
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py", reason="iteration 65 routing needs the bt_api_py SDK")

import backtrader as bt
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py.bt_api import ExecutionRoutingSelection
from bt_api_py.execution_routing import (
    ExecutionOrderRouter,
    install_execution_routing_tables,
    parse_execution_routing,
)
from bt_api_py.gateway_direct_client import GatewayClientRoute

from backtrader.brokers._execution_parent_projection import apply_position_delta
from backtrader.brokers._execution_routing_apply import ExecutionRoutingApplication
from backtrader.brokers.btapibroker import BtApiBroker

from ._fakes import (
    SYMBOL,
    VENUE,
    FakeApi,
    FakeStore,
    crash,
    drain,
    make_feed,
)

ACCOUNT = "account"
STRATEGY = "strategy-ref"
RUN_ID = "run-1"
KEY = MarketInstrumentKey("ctp", VENUE, "demo", "future", SYMBOL, SYMBOL)


# ---------------------------------------------------------------------------
# routing environment (same SDK wrap as the 65.06 routing tests)
# ---------------------------------------------------------------------------
def routing_option(**overrides):
    value = {
        "schema_version": 2,
        "algorithm_build_id": "synthetic-build-1",
        "component": "exec-instance",
        "account_ref": ACCOUNT,
        "strategy_ref": STRATEGY,
        "execution_domain_ref": "paper",
        "grant_revision": "grant-v1",
        "delegation": {"delegation_id": "delegation-1", "principal_ref": "principal-a"},
        "instruments": [KEY.to_dict()],
        "rules": [
            {
                "id": "rule-1",
                "match": {
                    "instrument": KEY.to_dict(),
                    "side": "buy",
                    "offset": "open",
                    "order_types": ["limit"],
                    "minimum_quantity": "1",
                    "quantity_unit": "base",
                },
                "schedule_binding": {"quantity_step": "1", "price_step": "1", "retry_limit": 2},
                "scheme": {"name": "pass-v1", "version": 1},
                "algorithm": {"class": "PASS", "version": 1, "params": {}},
                "deadline": {"kind": "absolute", "at": "2099-12-31T08:00:00+08:00"},
                "time_in_force": "DAY",
                "trading_day": "20261109",
            }
        ],
    }
    value.update(overrides)
    return value


def binding():
    return GatewayCommandBinding("journal", ACCOUNT, STRATEGY, "principal-a")


def route(run_id=RUN_ID):
    return GatewayClientRoute(
        "broker.direct_write",
        "gw-service",
        "gw-instance",
        "gw-scope",
        WireScope("paper", account_ref=ACCOUNT, strategy_ref=STRATEGY, run_id=run_id),
        WireIdentity(WireRole.STRATEGY_CLIENT, "principal-a", STRATEGY),
    )


class FakeExecutionParentPort:
    """The injected write-side ``service.execution_parent`` port (fake)."""

    def __init__(self, *, reply=None, cancel_reply=None):
        self.submit_reply = (
            {"status": "ACCEPTED", "parent_ref": "parent-1"} if reply is None else reply
        )
        self.cancel_reply = {"status": "ACCEPTED"} if cancel_reply is None else cancel_reply
        self.submit_calls = []
        self.cancel_calls = []

    def submit(self, request):
        self.submit_calls.append(request)
        if isinstance(self.submit_reply, BaseException):
            raise self.submit_reply
        return self.submit_reply

    def cancel(self, payload):
        self.cancel_calls.append(payload)
        if isinstance(self.cancel_reply, BaseException):
            raise self.cancel_reply
        return self.cancel_reply


class FakeExecutionFacts:
    """Injected read-only parent facts; every reply is a test double."""

    def __init__(self):
        self.status_value = None
        self.fills_value = []
        self.cancel_value = None
        self.completion_value = None
        self.status_error = None
        self.fills_error = None
        self.reads = collections.Counter()

    def status(self, request_id):
        self.reads["status"] += 1
        if self.status_error is not None:
            raise self.status_error
        value = self.status_value
        return value(request_id) if callable(value) else value

    def fills(self, request_id):
        self.reads["fills"] += 1
        if self.fills_error is not None:
            raise self.fills_error
        value = self.fills_value
        return value(request_id) if callable(value) else value

    def cancel(self, request_id):
        self.reads["cancel"] += 1
        return self.cancel_value

    def completion(self, request_id):
        self.reads["completion"] += 1
        return self.completion_value


def make_selection(strategy_dir, port, *, run_id=RUN_ID, config=None):
    state_dir = strategy_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(state_dir / "execution_routing.sqlite", isolation_level=None)
    connection.execute("BEGIN IMMEDIATE")
    install_execution_routing_tables(connection)
    connection.commit()
    router = ExecutionOrderRouter(
        db=connection,
        config=parse_execution_routing(routing_option()) if config is None else config,
        execution_port=port,
        risk_selected=False,
    )
    return ExecutionRoutingSelection(
        router=router, binding=binding(), route=route(run_id), ttl_seconds=10.0
    )


class RoutingApi(FakeApi):
    """Fake facade whose place mirrors the SDK routing wrap exactly."""

    def __init__(self, selection=None):
        super().__init__()
        self.selection = selection
        self.direct_places = 0
        self.direct_cancels = 0

    def make_order(
        self, exchange_name, request, *, pre_dispatch_commit, host_scope, request_summary=None
    ):
        if self.selection is None:
            return FakeApi.make_order(
                self,
                exchange_name,
                request,
                pre_dispatch_commit=pre_dispatch_commit,
                host_scope=host_scope,
                request_summary=request_summary,
            )
        from bt_api_py.execution_routing import route_order
        from bt_api_py.gateway_direct_client import build_gateway_order_intent

        intent = build_gateway_order_intent(
            self.selection.binding,
            self.selection.route,
            request,
            ttl_seconds=self.selection.ttl_seconds,
        )

        def direct():
            self.direct_places += 1
            return FakeApi.make_order(
                self,
                exchange_name,
                request,
                pre_dispatch_commit=pre_dispatch_commit,
                host_scope=host_scope,
                request_summary=request_summary,
            )

        return route_order(self.selection.router, intent, direct)

    def cancel_order(self, *args, **kwargs):
        self.direct_cancels += 1
        return FakeApi.cancel_order(self, *args, **kwargs)


class RoutingStore(FakeStore):
    def __init__(self, api, feeds, selection):
        super().__init__(api, feeds)
        self.execution_routing_selection = selection
        self.contract_metadata = {
            SYMBOL: {
                "instrument_key": KEY,
                "quantity_unit": "base",
                "price_tick": 1.0,
                "exchange": VENUE,
            }
        }


class ApplyEnv:
    """One strategy directory, one routing fake facade, one facts port."""

    def __init__(self, tmp_path):
        self.strategy_dir = tmp_path / "strategy"
        self.strategy_dir.mkdir(parents=True, exist_ok=True)
        self.parent_port = FakeExecutionParentPort()
        self.facts = FakeExecutionFacts()
        self.selection = make_selection(self.strategy_dir, self.parent_port)
        self.api = RoutingApi(self.selection)
        self.feed = make_feed(SYMBOL)
        self.store = RoutingStore(self.api, [self.feed], self.selection)
        self.brokers = []
        self.strategy = SimpleNamespace(name="direct-strategy")

    def broker(self, **params):
        values = {"strategy_dir": str(self.strategy_dir), "stop_cancel_timeout": 0.2}
        values.update(params)
        broker = BtApiBroker(store=self.store, **values)
        self.brokers.append(broker)
        return broker

    def start(self, **params):
        params.setdefault("direct_execution_projection_interval", 0.0)
        broker = self.broker(**params)
        broker.start()
        return broker

    def close(self):
        for broker in self.brokers:
            if broker._direct_active():
                try:
                    broker.stop()
                except Exception:
                    pass
            crash(broker)


@pytest.fixture
def env(tmp_path):
    environment = ApplyEnv(tmp_path)
    try:
        yield environment
    finally:
        environment.close()


def place(env, broker, *, side="buy", size=1, **kwargs):
    kwargs.setdefault("price", 3500.0)
    kwargs.setdefault("exectype", bt.Order.Limit)
    kwargs.setdefault("offset", "open")
    method = broker.buy if side == "buy" else broker.sell
    return method(env.strategy, env.feed, size, **kwargs)


def statuses(notifications):
    return [bt.Order.Status[item.status] for item in notifications]


def child(
    child_id="c1", state="SENT", quantity="1", *, attempts=1, reservation_id=None, last_error=None
):
    return {
        "child_id": child_id,
        "state": state,
        "quantity": quantity,
        "reservation_id": reservation_id,
        "attempts": attempts,
        "last_error": last_error,
    }


def fill(fill_id, *, quantity="1", price="3500", child_id="c1", side=None, offset=None):
    payload = {
        "fill_id": fill_id,
        "child_id": child_id,
        "quantity": quantity,
        "price": price,
        "source": "VENUE",
    }
    if side is not None:
        payload["side"] = side
    if offset is not None:
        payload["offset"] = offset
    return payload


def status_of(
    order,
    *,
    state="ACCEPTED",
    parent_ref="parent-1",
    frozen=False,
    children=(),
    last_error=None,
    attempts=1,
    request_sha256=None,
):
    return {
        "request_id": order.info["execution_request_id"],
        "parent_ref": parent_ref,
        "state": state,
        "request_sha256": (
            order.info["execution_request_sha256"] if request_sha256 is None else request_sha256
        ),
        "frozen": frozen,
        "last_error": last_error,
        "remote_attempts": attempts,
        "children": list(children),
        "unknown_children": [item["child_id"] for item in children if item["state"] == "UNKNOWN"],
    }


# ---------------------------------------------------------------------------
# acceptance
# ---------------------------------------------------------------------------
def test_an_accepted_parent_advances_the_order_once(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    assert statuses(drain(broker)) == ["Submitted"]
    env.facts.status_value = status_of(order)

    broker.next()

    assert order.status == bt.Order.Accepted
    assert order.executed.size == 0
    assert order.info["execution_parent_state"] == "ACCEPTED"
    assert order.info["execution_projection"]["status"] == "Accepted"
    assert statuses(drain(broker)) == ["Accepted"]
    # The parent has no venue identity: nothing pretends a venue order exists.
    assert broker._direct_meta[order.ref]["identity"] is None
    assert env.api.place_calls == [] and env.api.direct_places == 0
    assert env.parent_port.submit_calls and len(env.parent_port.submit_calls) == 1

    broker.next()  # the same accepted fact again

    assert drain(broker) == []
    assert order.status == bt.Order.Accepted


def test_no_facts_port_means_no_application(env):
    broker = env.start(first_init=True)
    order = place(env, broker)
    assert statuses(drain(broker)) == ["Submitted"]

    assert broker._direct_execution_application() is None
    assert broker.get_execution_projection_status() is None
    broker.next()
    broker.next()
    assert order.status == bt.Order.Submitted
    assert drain(broker) == []  # no application, no additional notification


# ---------------------------------------------------------------------------
# fills
# ---------------------------------------------------------------------------
def test_partial_and_complete_fills_apply_once(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker, size=2)
    drain(broker)
    env.facts.status_value = status_of(order, children=[child(quantity="2")])
    env.facts.fills_value = [fill("f1", child_id="c1")]

    broker.next()

    assert order.status == bt.Order.Partial
    assert order.executed.size == 1 and order.executed.remsize == 1
    assert broker.long_positions[SYMBOL].size == 1
    assert broker.positions[SYMBOL].size == 1
    assert order.info["execution_parent_filled"] == "1"
    assert statuses(drain(broker)) == ["Partial"]

    broker.next()  # identical facts

    assert drain(broker) == []
    assert order.executed.size == 1
    assert broker.long_positions[SYMBOL].size == 1

    env.facts.fills_value = [fill("f1", child_id="c1"), fill("f2", child_id="c1")]
    broker.next()

    assert order.status == bt.Order.Completed
    assert order.executed.size == 2 and order.executed.remsize == 0
    assert broker.long_positions[SYMBOL].size == 2
    assert statuses(drain(broker)) == ["Completed"]

    broker.next()
    assert drain(broker) == []
    assert broker.long_positions[SYMBOL].size == 2


def test_a_completion_fact_completes_without_fabricating_a_fill(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)
    env.facts.status_value = status_of(order)
    env.facts.completion_value = {"completion_id": "done-1", "completed_quantity": "1"}

    broker.next()

    assert order.status == bt.Order.Completed
    assert order.executed.size == 0
    assert broker.long_positions[SYMBOL].size == 0
    assert statuses(drain(broker)) == ["Completed"]
    # A second authoritative completion record is not a second transition.
    broker.next()
    assert drain(broker) == []


def test_a_missing_fill_reader_is_unknown_and_applies_no_fill(env):
    env.facts.fills = None
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)
    env.facts.status_value = status_of(order)

    broker.next()

    assert order.status == bt.Order.Accepted
    assert order.alive()
    assert order.executed.size == 0
    assert broker.long_positions[SYMBOL].size == 0
    assert order.info["execution_parent_unknown"] is True
    assert order.info["execution_projection_code"] == "FILL_PORT_UNAVAILABLE"
    # One Accepted notification carries the finite unknown reason too.
    assert statuses(drain(broker)) == ["Accepted"]


def test_fill_facts_without_venue_source_are_refused(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)
    env.facts.status_value = status_of(order)
    env.facts.fills_value = [
        {"fill_id": "f1", "child_id": "c1", "quantity": "1", "price": "3500", "source": "PLAN"}
    ]

    broker.next()

    assert order.status == bt.Order.Submitted
    assert order.executed.size == 0
    assert broker.long_positions[SYMBOL].size == 0
    assert order.info["execution_projection_code"] == "FILL_SOURCE_UNSUPPORTED"
    assert drain(broker) == []


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------
def test_a_cancelled_cancel_fact_cancels_the_order(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)
    env.facts.status_value = status_of(order, children=[child()])
    env.facts.fills_value = []
    env.facts.cancel_value = {"cancel_id": "cancel-1", "outcome": "CANCELED"}

    broker.next()

    assert order.status == bt.Order.Canceled
    assert statuses(drain(broker)) == ["Canceled"]
    assert order.info["execution_parent_state"] == "ACCEPTED"

    broker.next()
    assert drain(broker) == []


# ---------------------------------------------------------------------------
# unknown / frozen / unreadable
# ---------------------------------------------------------------------------
def test_an_unknown_parent_keeps_the_order_active_with_a_finite_reason(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)
    env.facts.status_value = status_of(order, state="UNKNOWN")

    broker.next()

    assert order.alive() and order.status == bt.Order.Submitted
    assert order.info["execution_parent_unknown"] is True
    assert order.info["execution_projection_code"] == "EXECUTION_PARENT_UNKNOWN"
    assert statuses(drain(broker)) == ["Submitted"]

    broker.next()
    assert drain(broker) == []  # same finite reason: no second notification


def test_a_frozen_parent_is_never_terminal(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)
    env.facts.status_value = status_of(order, frozen=True)

    broker.next()

    assert order.alive() and order.status == bt.Order.Accepted
    assert order.info["execution_parent_frozen"] is True
    assert order.info["execution_projection_code"] == "EXECUTION_PARENT_FROZEN"
    assert statuses(drain(broker)) == ["Accepted"]


def test_an_unreadable_status_port_is_unknown_and_never_resends(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)
    env.facts.status_error = TimeoutError("status read lost")

    broker.next()

    assert order.alive() and order.status == bt.Order.Submitted
    assert order.info["execution_projection_code"] == "EXECUTION_STATUS_UNREADABLE"
    assert statuses(drain(broker)) == ["Submitted"]
    assert len(env.parent_port.submit_calls) == 1  # nothing resent

    broker.next()
    assert drain(broker) == []


def test_a_port_without_a_status_reader_keeps_the_order_submitted(env):
    env.facts.status = None
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)

    broker.next()

    assert order.alive() and order.status == bt.Order.Submitted
    assert order.executed.size == 0
    assert order.info["execution_projection_code"] == "EXECUTION_FACTS_PORT_INVALID"
    assert drain(broker) == []
    assert env.facts.reads == collections.Counter()


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------
def test_execution_projection_metadata_round_trips(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker, size=2)
    drain(broker)
    request_id = order.info["execution_request_id"]

    entries = broker.execution_projection_metadata()

    assert len(entries) == 1
    entry = entries[0]
    assert entry["request_id"] == request_id
    # The unverified write reply cannot supply a parent identity.
    assert entry["parent_ref"] is None
    assert entry["request_key"] == broker._direct_meta[order.ref]["execution_request_key"]
    assert entry["run_id"] == RUN_ID
    assert entry["binding"] == {
        "request_id": request_id,
        "bt_ref": order.ref,
        "side": "buy",
        "offset": "open",
        "quantity": "2",
        "price": "3500",
    }
    assert broker.restore_execution_projection(entries, orders={request_id: order}) == {
        request_id: None
    }
    # A separate injected facts fixture may subsequently populate projection
    # state; it is a fake and does not establish a trusted real source.
    env.facts.status_value = status_of(order, parent_ref="fact-parent")
    broker.next()
    state = broker.execution_projection_snapshot()
    assert state["projection"]["requests"][request_id]["parent_ref"] == "fact-parent"
    # Metadata still reflects the routing result, not that later fact.
    assert broker.execution_projection_metadata()[0]["parent_ref"] is None
    assert len(env.parent_port.submit_calls) == 1
    assert env.api.direct_places == 0 and env.api.place_calls == []


def test_an_invalid_restart_state_is_a_finite_refusal(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)

    result = broker.restore_execution_projection(
        [{"request_id": "req-1"}], state={"schema": "not-the-apply-schema"}
    )

    assert result == {"*": "EXECUTION_RECORD_INVALID"}
    assert broker._direct_execution_app is None


def test_restore_without_a_facts_port_is_finite(env):
    broker = env.start(first_init=True)
    metadata = {
        "request_id": "req-1",
        "parent_ref": "parent-1",
        "run_id": RUN_ID,
        "request_key": "bt-" + "0" * 32 + "-" + "0" * 16 + "-1",
        "binding": {
            "request_id": "req-1",
            "bt_ref": 1,
            "side": "buy",
            "offset": "open",
            "quantity": "1",
            "price": "3500",
        },
    }

    result = broker.restore_execution_projection([metadata])

    assert result == {"req-1": "EXECUTION_FACTS_PORT_UNAVAILABLE"}
    assert broker.get_execution_projection_status() is None


def test_restore_reconstructs_a_parent_from_persisted_metadata(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = bt.BuyOrder(owner=None, data=env.feed, size=2, price=3500.0, exectype=bt.Order.Limit)
    order.submit(broker)
    broker.orders[order.ref] = order
    metadata = {
        "request_id": "req-9",
        "parent_ref": "parent-9",
        "run_id": RUN_ID,
        "request_key": "bt-" + "1" * 32 + "-" + "1" * 16 + "-9",
        "binding": {
            "request_id": "req-9",
            "bt_ref": order.ref,
            "side": "buy",
            "offset": "open",
            "quantity": "2",
            "price": "3500",
        },
    }
    assert broker.restore_execution_projection([metadata], orders={"req-9": order}) == {
        "req-9": None
    }

    env.facts.status_value = {
        "request_id": "req-9",
        "parent_ref": "parent-9",
        "state": "ACCEPTED",
        "request_sha256": None,
        "frozen": False,
        "last_error": None,
        "remote_attempts": 1,
        "children": [],
        "unknown_children": [],
    }
    env.facts.fills_value = [fill("f1", child_id="c1")]

    broker.next()

    assert order.status == bt.Order.Partial
    assert order.executed.size == 1
    assert broker.long_positions[SYMBOL].size == 1
    assert broker.get_execution_projection_status()["records"] == 1


def test_a_restored_projection_does_not_reapply_the_same_facts(tmp_path):
    feed = make_feed(SYMBOL)
    facts = FakeExecutionFacts()
    facts.status_value = {
        "request_id": "req-1",
        "parent_ref": "parent-1",
        "state": "ACCEPTED",
        "request_sha256": None,
        "frozen": False,
        "last_error": None,
        "remote_attempts": 1,
        "children": [],
        "unknown_children": [],
    }
    facts.fills_value = [fill("f1", child_id="c1")]

    def make_order():
        order = bt.BuyOrder(owner=None, data=feed, size=2, price=3500.0, exectype=bt.Order.Limit)
        order.submit(None)
        return order

    first_position = bt.Position()
    first_events = []

    def on_fact(record, fact, code):
        first_events.append(("fact", None if fact is None else fact.bt_status_name))

    def on_notification(record, notification, *, status_changed=False):
        first_events.append(("note", notification.kind))

    def make_delta(position, events):
        def on_delta(record, delta):
            apply_position_delta(position, delta)
            events.append(("delta", delta.fill_id))

        return on_delta

    app = ExecutionRoutingApplication(
        facts=facts,
        on_fact=on_fact,
        on_notification=on_notification,
        on_delta=make_delta(first_position, first_events),
        interval=0.0,
    )
    assert app.register(request_id="req-1", order=make_order(), parent_ref="parent-1") is None

    app.poll()

    assert first_position.size == 1
    assert [event for event in first_events if event[0] != "fact"] == [
        ("delta", "f1"),
        ("note", "submitted"),
        ("note", "accepted"),
    ]
    state = app.snapshot()

    second_position = bt.Position()
    second_events = []

    def second_notification(record, notification, *, status_changed=False):
        second_events.append(("note", notification.kind))

    restarted = ExecutionRoutingApplication(
        facts=facts,
        on_fact=lambda record, fact, code: None,
        on_notification=second_notification,
        on_delta=make_delta(second_position, second_events),
        interval=0.0,
        restore=state,
    )
    assert (
        restarted.register(
            request_id="req-1",
            order=make_order(),
            binding=state["records"]["req-1"]["binding"],
            parent_ref="parent-1",
        )
        is None
    )

    restarted.poll()  # the exact same facts after restore

    assert second_events == []
    assert second_position.size == 0

    facts.fills_value = [fill("f1", child_id="c1"), fill("f2", child_id="c1")]
    restarted.poll()  # a later fact advances exactly once

    assert second_events == [("delta", "f2")]
    assert second_position.size == 1

    restarted.poll()
    assert second_events == [("delta", "f2")]
    assert second_position.size == 1


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------
def test_stop_does_not_cancel_or_terminalize_a_routed_parent(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)
    env.facts.status_value = status_of(order)

    summary = broker.stop()

    assert order.alive() and order.status == bt.Order.Submitted
    assert order.info["stop_unresolved"] == "execution_routed_parent"
    assert summary["status"] == "STOPPED_WITH_WORKING_ORDERS"
    assert summary["cancelled_requested"] == 0
    assert summary["unresolved_working_orders"] == 1
    assert summary["routed_parents_unresolved"] == 1
    assert summary["routed_parent_refs"] == [order.ref]
    # Neither the venue cancel nor the key-based routed cancel ran.
    assert env.api.cancel_calls == []
    assert env.parent_port.cancel_calls == []


def test_routed_cancels_still_go_through_the_key_hook_before_stop(env):
    broker = env.start(first_init=True, direct_execution_facts=env.facts)
    order = place(env, broker)
    drain(broker)

    broker.cancel(order)

    assert len(env.parent_port.cancel_calls) == 1
    assert env.api.direct_cancels == 0 and env.api.cancel_calls == []
    assert order.info["execution_cancel_outcome"] == "EXECUTION_UNKNOWN"
    assert order.info["execution_cancel_unknown"] is True
    assert order.info["execution_cancel_code"] == "EXECUTION_UNVERIFIED_REPLY"
    assert env.parent_port.cancel_calls[0]["remote_parent_ref"] is None

    summary = broker.stop()
    assert order.alive()
    assert summary["routed_parents_unresolved"] == 1
    assert len(env.parent_port.cancel_calls) == 1  # stop never sends another cancel


# ---------------------------------------------------------------------------
# application-level guards
# ---------------------------------------------------------------------------
def test_registering_a_conflicting_binding_is_refused(tmp_path):
    facts = FakeExecutionFacts()
    app = ExecutionRoutingApplication(facts=facts, interval=0.0)
    feed = make_feed(SYMBOL)
    order = bt.BuyOrder(owner=None, data=feed, size=2, price=3500.0, exectype=bt.Order.Limit)
    binding = {
        "request_id": "req-1",
        "bt_ref": order.ref,
        "side": "buy",
        "offset": "open",
        "quantity": "2",
        "price": "3500",
    }

    assert app.register(request_id="req-1", binding=binding) is None
    conflicting = dict(binding, quantity="3")
    assert app.register(request_id="req-1", binding=conflicting) == "EXECUTION_RECORD_CONFLICT"
    assert app.register(request_id="req-1", order=order, offset="open") is None


def test_a_metadata_only_record_keeps_its_facts_pending(tmp_path):
    facts = FakeExecutionFacts()
    facts.status_value = {
        "request_id": "req-1",
        "parent_ref": "parent-1",
        "state": "ACCEPTED",
        "request_sha256": None,
        "frozen": False,
        "last_error": None,
        "remote_attempts": 1,
        "children": [],
        "unknown_children": [],
    }
    facts.fills_value = [fill("f1")]
    binding = {
        "request_id": "req-1",
        "bt_ref": 1,
        "side": "buy",
        "offset": "open",
        "quantity": "1",
        "price": "3500",
    }
    app = ExecutionRoutingApplication(facts=facts, interval=0.0)
    assert app.register(request_id="req-1", binding=binding, parent_ref="parent-1") is None

    app.poll()

    record = app.record("req-1")
    assert record["has_order"] is False
    assert record["pending_deltas"] == 1
    assert record["applied_deltas"] == 0
    assert record["last_status"] == bt.Order.Accepted

    feed = make_feed(SYMBOL)
    order = bt.BuyOrder(owner=None, data=feed, size=1, price=3500.0, exectype=bt.Order.Limit)
    applied = []
    app._on_delta = lambda record, delta: applied.append(delta.fill_id)
    app._on_notification = lambda record, notification, *, status_changed=False: applied.append(
        notification.kind
    )
    assert app.attach("req-1", order) is None

    app.poll()

    assert applied == ["f1", "submitted", "accepted"]
    assert app.record("req-1")["pending_deltas"] == 0
    assert app.record("req-1")["applied_deltas"] == 1


def test_pending_facts_survive_a_restart_and_deliver_once(tmp_path):
    facts = FakeExecutionFacts()
    facts.status_value = {
        "request_id": "req-1",
        "parent_ref": "parent-1",
        "state": "ACCEPTED",
        "request_sha256": None,
        "frozen": False,
        "last_error": None,
        "remote_attempts": 1,
        "children": [],
        "unknown_children": [],
    }
    facts.fills_value = [fill("f1")]
    binding = {
        "request_id": "req-1",
        "bt_ref": 1,
        "side": "buy",
        "offset": "open",
        "quantity": "1",
        "price": "3500",
    }
    app = ExecutionRoutingApplication(facts=facts, interval=0.0)
    assert app.register(request_id="req-1", binding=binding, parent_ref="parent-1") is None
    app.poll()  # no order yet: the facts stay pending
    state = app.snapshot()

    applied = []
    restarted = ExecutionRoutingApplication(
        facts=facts,
        on_fact=lambda record, fact, code: None,
        on_notification=lambda record, notification, *, status_changed=False: applied.append(
            notification.kind
        ),
        on_delta=lambda record, delta: applied.append(delta.fill_id),
        interval=0.0,
        restore=state,
    )
    feed = make_feed(SYMBOL)
    order = bt.BuyOrder(owner=None, data=feed, size=1, price=3500.0, exectype=bt.Order.Limit)
    assert restarted.register(request_id="req-1", binding=binding, order=order) is None

    restarted.poll()

    assert applied == ["f1", "submitted", "accepted"]
    restarted.poll()
    assert applied == ["f1", "submitted", "accepted"]


def test_the_projection_is_bounded_by_the_configured_order_budget(tmp_path):
    facts = FakeExecutionFacts()
    app = ExecutionRoutingApplication(facts=facts, interval=0.0, max_orders=1)
    feed = make_feed(SYMBOL)
    for index in (1, 2):
        order = bt.BuyOrder(owner=None, data=feed, size=1, price=3500.0, exectype=bt.Order.Limit)
        binding = {
            "request_id": f"req-{index}",
            "bt_ref": order.ref,
            "side": "buy",
            "offset": "open",
            "quantity": "1",
            "price": "3500",
        }
        assert app.register(request_id=f"req-{index}", order=order, binding=binding) is None
    facts.status_value = lambda request_id: {
        "request_id": request_id,
        "parent_ref": "parent-1",
        "state": "UNKNOWN",
        "request_sha256": None,
        "frozen": False,
        "last_error": None,
        "remote_attempts": 1,
        "children": [],
        "unknown_children": [],
    }

    first = app.poll()

    assert first.polled == 1
    assert facts.reads["status"] == 1  # one parent read per bounded round
    app.poll()
    assert facts.reads["status"] == 2  # the next round continues with the other parent
