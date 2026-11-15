"""Iteration 65: BtApiBroker direct mode routes immediate places/cancels to Execution.

UNIT/FAKE. The fake facade mirrors the SDK ``make_order``/``cancel_order`` wrap
exactly: it builds the Gateway intent from the request, then calls the real SDK
``route_order`` over a real ``ExecutionOrderRouter`` backed by a temporary
SQLite file and a fake Execution parent port. Nothing here starts a service,
opens a socket, or contacts a provider or an account. A local PREPARED row or a
port acknowledgement proves no Gateway acceptance, no Risk approval and no
venue state.
"""

from __future__ import annotations

import collections
import hashlib
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
    ExecutionCancelTarget,
    ExecutionOrderRouter,
    ExecutionRoutingOutcome,
    install_execution_routing_tables,
    parse_execution_routing,
)
from bt_api_py.gateway_direct_client import GatewayClientRoute

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


def routing_option(**overrides):
    value = {
        "schema_version": 1,
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
    """The injected ``service.execution_parent`` port; every reply is a fake."""

    def __init__(self, *, reply=None, cancel_reply=None, with_cancel=True):
        self.submit_reply = (
            {"status": "ACCEPTED", "parent_ref": "parent-1"} if reply is None else reply
        )
        self.cancel_reply = {"status": "ACCEPTED"} if cancel_reply is None else cancel_reply
        self.submit_calls = []
        self.cancel_calls = []
        if with_cancel:
            self.cancel = self._cancel

    def submit(self, request):
        self.submit_calls.append(request)
        if isinstance(self.submit_reply, BaseException):
            raise self.submit_reply
        return self.submit_reply

    def _cancel(self, payload):
        self.cancel_calls.append(payload)
        if isinstance(self.cancel_reply, BaseException):
            raise self.cancel_reply
        return self.cancel_reply


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


def parent_row(strategy_dir, request_key):
    connection = sqlite3.connect(strategy_dir / "state" / "execution_routing.sqlite")
    try:
        return connection.execute(
            "SELECT request_id, request_sha256, payload, result, cancel_result "
            "FROM execution_parent_requests_v1 WHERE account=? AND strategy=? AND request_key=?",
            (ACCOUNT, STRATEGY, request_key),
        ).fetchone()
    finally:
        connection.close()


class RoutingApi(FakeApi):
    """Fake facade whose place mirrors the SDK routing wrap exactly."""

    def __init__(self, selection=None):
        super().__init__()
        self.selection = selection
        self.direct_places = 0
        self.direct_cancels = 0
        self.foreign_replies = collections.deque()

    def make_order(
        self, exchange_name, request, *, pre_dispatch_commit, host_scope, request_summary=None
    ):
        if self.foreign_replies:
            return self.foreign_replies.popleft()
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
        # Contract metadata the Broker reads for the venue and quantity unit.
        self.contract_metadata = {
            SYMBOL: {
                "instrument_key": KEY,
                "quantity_unit": "base",
                "price_tick": 1.0,
                "exchange": VENUE,
            }
        }


class RoutingEnv:
    """One strategy directory, one routing fake facade, one Store, real feeds."""

    def __init__(self, tmp_path, *, routed=True, port=None, run_id=RUN_ID, config=None):
        self.strategy_dir = tmp_path / "strategy"
        self.strategy_dir.mkdir(parents=True, exist_ok=True)
        self.port = FakeExecutionParentPort() if port is None else port
        self.selection = (
            make_selection(self.strategy_dir, self.port, run_id=run_id, config=config)
            if routed
            else None
        )
        self.api = RoutingApi(self.selection)
        self.feed = make_feed(SYMBOL)
        self.other_feed = make_feed("hc2701", price=3300.0)
        self.store = RoutingStore(self.api, [self.feed, self.other_feed], self.selection)
        self.brokers = []
        self.strategy = SimpleNamespace(name="direct-strategy")

    def broker(self, **params):
        values = {"strategy_dir": str(self.strategy_dir), "stop_cancel_timeout": 0.2}
        values.update(params)
        broker = BtApiBroker(store=self.store, **values)
        self.brokers.append(broker)
        return broker

    def start(self, **params):
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
    environment = RoutingEnv(tmp_path)
    try:
        yield environment
    finally:
        environment.close()


@pytest.fixture
def broker(env):
    return env.start(first_init=True)


def place(env, broker, side="buy", size=1, **kwargs):
    kwargs.setdefault("price", 3500.0)
    kwargs.setdefault("exectype", bt.Order.Limit)
    kwargs.setdefault("offset", "open")
    method = broker.buy if side == "buy" else broker.sell
    return method(env.strategy, env.feed, size, **kwargs)


def expected_key(strategy_uuid, run_id, sequence):
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    return f"bt-{strategy_uuid.replace('-', '')}-{digest}-{sequence}"


# ---------------------------------------------------------------------------
# matched place
# ---------------------------------------------------------------------------


def test_matched_place_is_submitted_without_venue_identity(env, broker):
    order = place(env, broker)
    meta = broker._direct_meta[order.ref]
    sequence = meta["local_seq"]
    key = meta["execution_request_key"]

    assert key == expected_key(broker._direct_uuid, RUN_ID, sequence)
    assert order.status == bt.Order.Submitted
    # No venue identity, marker or fill was fabricated.
    assert meta["identity"] is None
    assert meta["marker_id"] is None
    assert order.executed.size == 0
    assert order.info["execution_routing_outcome"] == "EXECUTION_ACCEPTED"
    assert order.info["execution_parent_ref"] == "parent-1"
    assert order.info["execution_request_id"].startswith("sdk-request-v1:")
    assert len(order.info["execution_request_sha256"]) == 64
    # The fake Execution port saw exactly one submit; the direct path never ran.
    assert len(env.port.submit_calls) == 1
    assert env.api.direct_places == 0
    assert env.api.place_calls == []
    # The request carried the stable key and the Gateway account scope.
    assert env.port.submit_calls[0]["request_id"] == order.info["execution_request_id"]
    row = parent_row(env.strategy_dir, key)
    assert row is not None and row[3] is not None
    assert row[0] == order.info["execution_request_id"]
    assert [bt.Order.Status[item.status] for item in drain(broker)] == ["Submitted"]


def test_place_request_carries_the_key_and_gateway_account(env, broker):
    order = place(env, broker)
    meta = broker._direct_meta[order.ref]

    assert meta["execution_request_key"].startswith("bt-")
    assert env.port.submit_calls[0]["spec"]["account_scope"] == ACCOUNT
    assert env.port.submit_calls[0]["spec"]["quantity"] == "1.0"
    assert env.port.submit_calls[0]["spec"]["limit_price"] == "3500.0"
    assert env.port.submit_calls[0]["order_type"] == "limit"


# ---------------------------------------------------------------------------
# stable request key
# ---------------------------------------------------------------------------


def test_request_key_is_the_same_after_a_restart(env, broker):
    order = place(env, broker)
    meta = broker._direct_meta[order.ref]
    first = broker._direct_execution_intent_identity({"local_seq": meta["local_seq"]})
    strategy_uuid = broker._direct_uuid
    crash(broker)

    restarted = env.start()

    second = restarted._direct_execution_intent_identity({"local_seq": meta["local_seq"]})
    assert first == second
    assert restarted._direct_uuid == strategy_uuid
    # The very same key still names the durable parent: a cancel by key replays
    # the stored outcome instead of creating or resending anything.
    target = ExecutionCancelTarget(request_key=first[0], run_id=RUN_ID)
    replay = restarted.store.execution_routing_selection.router.cancel_target(target)
    assert replay.outcome is ExecutionRoutingOutcome.EXECUTION_CANCEL_ACCEPTED
    assert len(env.port.submit_calls) == 1
    assert len(env.port.cancel_calls) == 1


def test_request_key_changes_with_the_intent_and_the_run(env, broker):
    order = place(env, broker)
    meta = broker._direct_meta[order.ref]
    sequence = meta["local_seq"]

    same = broker._direct_execution_intent_identity({"local_seq": sequence})
    next_intent = broker._direct_execution_intent_identity({"local_seq": sequence + 1})
    other_run = make_selection(env.strategy_dir, env.port, run_id="run-2")

    assert same != next_intent
    assert broker._direct_execution_intent_identity({"local_seq": sequence}) == same
    env.store.execution_routing_selection = other_run
    try:
        changed = broker._direct_execution_intent_identity({"local_seq": sequence})
    finally:
        env.store.execution_routing_selection = env.selection
    assert changed is not None
    assert changed[0] == expected_key(broker._direct_uuid, "run-2", sequence)


def test_an_unproven_identity_refuses_before_the_sdk(env, broker):
    broker._direct_uuid = ""

    order = place(env, broker)

    assert order.status == bt.Order.Rejected
    assert "execution_request_identity_unavailable" in str(order.info.get("error_code"))
    assert env.port.submit_calls == []
    assert env.api.place_calls == []
    assert env.api.direct_places == 0


# ---------------------------------------------------------------------------
# outcome mapping
# ---------------------------------------------------------------------------


def test_a_local_receipt_is_submitted_but_not_reported_as_accepted(env, tmp_path):
    port = FakeExecutionParentPort(reply={"status": "LOCAL_RECEIVED"})
    environment = RoutingEnv(tmp_path / "alt", port=port)
    try:
        broker = environment.start(first_init=True)

        order = place(environment, broker)

        assert order.status == bt.Order.Submitted
        assert order.info["execution_routing_outcome"] == "EXECUTION_LOCAL_RECEIPT"
        assert order.info.get("execution_prepared") is True
        assert order.info.get("outcome_unknown") is None
        assert broker._direct_meta[order.ref]["execution_routing"]["code"] is None
    finally:
        environment.close()


def test_unknown_place_keeps_the_order_submitted_and_never_resends(env, broker):
    env.port.submit_reply = TimeoutError("reply lost")

    order = place(env, broker)
    meta = broker._direct_meta[order.ref]

    assert order.status == bt.Order.Submitted
    assert order.info.get("outcome_unknown") is True
    assert order.info["execution_routing_outcome"] == "EXECUTION_UNKNOWN"
    assert order.info["execution_routing_code"] == "CALL_OUTCOME_UNKNOWN"
    assert env.api.direct_places == 0
    assert len(env.port.submit_calls) == 1
    # The SDK keeps the outcome under the same key: replaying the exact intent
    # returns it and makes no second remote call.
    from bt_api_py.gateway_direct_client import build_gateway_order_intent

    intent = build_gateway_order_intent(
        env.selection.binding,
        env.selection.route,
        broker._direct_request(order, dict(meta)),
        ttl_seconds=env.selection.ttl_seconds,
    )
    replay = env.selection.router.route(intent)
    assert replay.outcome is ExecutionRoutingOutcome.EXECUTION_UNKNOWN
    assert len(env.port.submit_calls) == 1


def test_rejected_place_is_a_local_rejection(env, broker):
    env.port.submit_reply = {"status": "REJECTED", "code": "EXECUTION_RULE_REJECTED"}

    order = place(env, broker)

    assert order.status == bt.Order.Rejected
    assert "execution_rejected:EXECUTION_RULE_REJECTED" in str(order.info.get("error_code"))
    assert env.api.direct_places == 0
    assert env.api.place_calls == []


def test_unavailable_execution_never_falls_back_to_direct(env, broker):
    env.port.__dict__.pop("submit", None)
    env.port.submit = None  # a port without the submit capability

    order = place(env, broker)

    assert order.status == bt.Order.Rejected
    assert "execution_unavailable:EXECUTION_UNAVAILABLE" in str(order.info.get("error_code"))
    assert env.api.direct_places == 0
    assert env.api.place_calls == []


def test_a_dynamically_matched_market_order_is_rejected_before_execution(tmp_path):
    # D65-07: Execution accepts limit parents only. A rule that does not narrow
    # the order type matches a market order dynamically; that request is refused
    # before any parent exists and is never converted to a limit order.
    rule = routing_option()["rules"][0]
    rule["match"] = {key: value for key, value in rule["match"].items() if key != "order_types"}
    config = parse_execution_routing(routing_option(rules=[rule]))
    environment = RoutingEnv(tmp_path / "alt", config=config)
    try:
        broker = environment.start(first_init=True)

        order = place(environment, broker, exectype=bt.Order.Market, price=None)

        assert order.status == bt.Order.Rejected
        assert "execution_rejected:EXECUTION_ORDER_TYPE_UNSUPPORTED" in str(
            order.info.get("error_code")
        )
        assert environment.port.submit_calls == []
        assert environment.api.direct_places == 0
        assert environment.api.place_calls == []
    finally:
        environment.close()


def test_a_limit_only_rule_leaves_a_market_order_on_the_existing_path(env, broker):
    # A market request never counts as matched by a limit-only rule: the
    # existing direct path runs exactly once, unchanged.
    order = place(env, broker, exectype=bt.Order.Market, price=None)

    assert order.status == bt.Order.Submitted
    assert env.api.direct_places == 1
    assert env.api.place_calls != []
    assert env.port.submit_calls == []


def test_a_foreign_reply_is_a_finite_local_refusal(env, broker):
    env.api.foreign_replies.append(SimpleNamespace(sent=True, marker_id="x"))

    order = place(env, broker)

    assert order.status == bt.Order.Rejected
    assert "execution_reply_invalid" in str(order.info.get("error_code"))
    assert env.port.submit_calls == []
    assert env.api.place_calls == []
    assert broker._direct_meta[order.ref]["marker_id"] is None


def test_an_unmatched_request_keeps_the_existing_direct_path_once(env, tmp_path):
    rule = routing_option()["rules"][0]
    rule["match"] = {**rule["match"], "side": "sell"}
    config = parse_execution_routing(routing_option(rules=[rule]))
    environment = RoutingEnv(tmp_path / "alt", config=config)
    try:
        broker = environment.start(first_init=True)

        order = place(environment, broker)
        meta = broker._direct_meta[order.ref]

        assert env.port.submit_calls == []
        assert environment.api.direct_places == 1
        assert environment.api.place_calls != []
        assert order.status == bt.Order.Submitted
        # The SDK built the intent before routing, so the stable key exists and
        # a later cancel can still be routed by it.
        assert meta["execution_request_key"].startswith("bt-")
        assert meta["marker_id"] is not None and meta["identity"] is not None
        assert parent_row(environment.strategy_dir, meta["execution_request_key"]) is None
    finally:
        environment.close()


def test_direct_path_without_any_selection_is_unchanged(tmp_path):
    environment = RoutingEnv(tmp_path / "alt", routed=False)
    try:
        broker = environment.start(first_init=True)

        order = place(environment, broker)
        meta = broker._direct_meta[order.ref]

        assert broker._direct_execution_routing() is None
        assert "execution_request_key" not in meta
        assert environment.api.place_calls[0].request.idempotency_key == ""
        assert environment.api.place_calls[0].request.account_id == "direct"
        assert order.status == bt.Order.Submitted
        assert meta["marker_id"] is not None and meta["identity"] is not None
    finally:
        environment.close()


def test_an_unmatched_order_still_cancels_through_the_direct_path(env, tmp_path):
    rule = routing_option()["rules"][0]
    rule["match"] = {**rule["match"], "side": "sell"}
    config = parse_execution_routing(routing_option(rules=[rule]))
    environment = RoutingEnv(tmp_path / "alt", config=config)
    try:
        broker = environment.start(first_init=True)
        order = place(environment, broker)
        meta = broker._direct_meta[order.ref]

        broker.cancel(order)

        assert meta.get("execution_routed") is None
        assert environment.api.direct_cancels == 1
        assert environment.port.cancel_calls == []
    finally:
        environment.close()


# ---------------------------------------------------------------------------
# routed cancel
# ---------------------------------------------------------------------------


def test_matched_cancel_routes_by_the_same_key_and_never_direct(env, broker):
    order = place(env, broker)
    key = broker._direct_meta[order.ref]["execution_request_key"]
    request_id = order.info["execution_request_id"]

    broker.cancel(order)

    assert order.alive()
    assert len(env.port.cancel_calls) == 1
    payload = env.port.cancel_calls[0]
    assert payload["request_id"] == request_id
    assert payload["operation_id"].startswith("sdk-cancel-v1:")
    assert payload["request_sha256"] == order.info["execution_request_sha256"]
    assert order.info["execution_cancel_outcome"] == "EXECUTION_CANCEL_ACCEPTED"
    assert env.api.direct_cancels == 0
    assert env.api.cancel_calls == []
    assert parent_row(env.strategy_dir, key)[4] is not None
    # Repeating the strategy cancel replays the stored operation, no resend.
    broker.cancel(order)
    assert len(env.port.cancel_calls) == 1


def test_routed_cancel_unknown_keeps_the_order_and_reports_it(env, tmp_path):
    port = FakeExecutionParentPort(cancel_reply=TimeoutError("reply lost"))
    environment = RoutingEnv(tmp_path / "alt", port=port)
    try:
        broker = environment.start(first_init=True)
        order = place(environment, broker)

        broker.cancel(order)

        assert order.alive()
        assert order.info.get("execution_cancel_unknown") is True
        assert environment.api.direct_cancels == 0
        assert len(port.cancel_calls) == 1
    finally:
        environment.close()


def test_routed_cancel_without_a_cancel_port_is_finite_and_never_direct(env, tmp_path):
    port = FakeExecutionParentPort(with_cancel=False)
    environment = RoutingEnv(tmp_path / "alt", port=port)
    try:
        broker = environment.start(first_init=True)
        order = place(environment, broker)

        broker.cancel(order)

        assert order.alive()
        assert order.info["cancel_error"] == "EXECUTION_CANCEL_UNAVAILABLE"
        assert environment.api.direct_cancels == 0
        assert environment.api.cancel_calls == []
    finally:
        environment.close()


def test_a_routed_key_without_a_parent_is_never_a_blind_venue_cancel(env, broker):
    order = place(env, broker)
    meta = broker._direct_meta[order.ref]
    meta["execution_request_key"] = "bt-" + "0" * 32 + "-" + "0" * 16 + "-999"

    broker.cancel(order)

    assert order.alive()
    assert order.info["cancel_error"] == "execution_parent_not_recorded"
    assert env.api.direct_cancels == 0
    assert env.port.cancel_calls == []


def test_a_routed_order_is_not_reported_as_a_venue_working_order(env, broker):
    order = place(env, broker)

    assert [bt.Order.Status[item.status] for item in drain(broker)] == ["Submitted"]
    assert broker._direct_meta[order.ref].get("identity") is None
    # No return can be matched to it and nothing pretends one was received.
    broker.next()
    assert order.status == bt.Order.Submitted
