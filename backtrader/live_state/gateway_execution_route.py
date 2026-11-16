"""Local immutable route selection; it does not establish remote authority."""
from __future__ import annotations

from dataclasses import dataclass
import os
import threading

from bt_api_py.gateway_direct_client import gateway_intent_from_mapping
from .gateway_order_state import _hex64, _ref, save_order_intent


@dataclass(frozen=True)
class GatewayExecutionRoute:
    kind: str
    account: str
    strategy: str
    request_key: str
    intent_digest: str
    configuration_id: str
    execution_domain_ref: str
    request_id: str | None = None
    request_sha256: str | None = None
    parent_ref: str | None = None


def make_pending(intent, configuration_id):
    if not _ref(configuration_id):
        raise ValueError("GATEWAY_EXECUTION_CONFIGURATION_INVALID")
    return dict(kind="PENDING", account=intent.binding.account_scope,
                strategy=intent.binding.strategy_scope, request_key=intent.request_key,
                intent_digest=intent.digest, configuration_id=configuration_id,
                execution_domain_ref=intent.route.scope.execution_domain_ref,
                request_id=None, request_sha256=None, parent_ref=None)


def route_allowed(state, key, kinds):
    route = state["gateway"].get("execution_routes", {}).get(key)
    return route is None or route["kind"] in kinds


def require_route(state, key, kinds):
    if not route_allowed(state, key, kinds):
        raise ValueError("GATEWAY_EXECUTION_ROUTE_NOT_ALLOWED")


def validate_routes(state, binding):
    gateway = state["gateway"]
    routes = gateway["execution_routes"]
    if type(routes) is not dict or len(routes) > gateway["max_entries"]:
        raise ValueError("GATEWAY_EXECUTION_ROUTE_INVALID")
    fields = set(GatewayExecutionRoute.__dataclass_fields__)
    for key, route in routes.items():
        if type(route) is not dict or set(route) != fields or key not in gateway["intents"]:
            raise ValueError("GATEWAY_EXECUTION_ROUTE_INVALID")
        intent = gateway_intent_from_mapping(gateway["intents"][key]["intent"], expected_binding=binding)
        expected = make_pending(intent, route["configuration_id"])
        for name in ("account", "strategy", "request_key", "intent_digest", "execution_domain_ref"):
            if route[name] != expected[name] or type(route[name]) is not str:
                raise ValueError("GATEWAY_EXECUTION_ROUTE_IDENTITY")
        if key != route["request_key"] or key not in gateway["order_snapshots"] or key not in gateway["local_notifications"]:
            raise ValueError("GATEWAY_EXECUTION_ROUTE_ORPHAN")
        kind = route["kind"]
        if kind not in ("PENDING", "EXECUTION_PARENT", "GATEWAY", "RISK"):
            raise ValueError("GATEWAY_EXECUTION_ROUTE_INVALID")
        if kind == "EXECUTION_PARENT":
            if not _ref(route["request_id"]) or not _hex64(route["request_sha256"]) or not _ref(route["parent_ref"]):
                raise ValueError("GATEWAY_EXECUTION_ROUTE_INVALID")
        elif any(route[name] is not None for name in ("request_id", "request_sha256", "parent_ref")):
            raise ValueError("GATEWAY_EXECUTION_ROUTE_INVALID")
        entry = gateway["intents"][key]
        delegated = key in gateway["delegated_commands"]
        if kind in ("PENDING", "EXECUTION_PARENT"):
            if (any(entry[name] is not None for name in ("record", "marker_id", "release"))
                    or delegated or "reject:" + key in gateway["local_notifications"]
                    or "cancel:" + key in gateway["local_notifications"]):
                raise ValueError("GATEWAY_EXECUTION_ROUTE_CONFLICT")
        elif kind == "GATEWAY" and delegated:
            raise ValueError("GATEWAY_EXECUTION_ROUTE_CONFLICT")
        elif kind == "RISK" and any(entry[name] is not None for name in ("record", "marker_id", "release")):
            raise ValueError("GATEWAY_EXECUTION_ROUTE_CONFLICT")


def upgrade(host):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] == 7:
            state["version"] = 8
            state["gateway"]["execution_routes"] = {}
            host._store._store(state, trim_history=False)
        elif state["version"] != 8:
            raise ValueError("GATEWAY_EXECUTION_ROUTING_UPGRADE_REQUIRED")
    return host


def save_intent(host, intent, *, local_seq, bt_ref, snapshot, configuration_id):
    if not _ref(configuration_id):
        raise ValueError("GATEWAY_EXECUTION_CONFIGURATION_INVALID")
    return save_order_intent(host, intent, local_seq=local_seq, bt_ref=bt_ref, snapshot=snapshot,
                             local_submitted=True, execution_configuration_id=configuration_id)


def issue_direct_decision(host, route):
    """Remember the successful first local write; this is not a NO_MATCH proof.

    The caller may choose direct only after the original SDK router returns
    DIRECT_PATH for this invocation. A lost process, thread or write consumes
    the opportunity; it is never reconstructed from the durable PENDING row.
    """
    host._execution_route_decisions[route["request_key"]] = (
        os.getpid(), threading.current_thread(), host._store, host._binding,
        route["intent_digest"], route["configuration_id"],
    )


def _consume_direct_decision(host, route):
    saved = host._execution_route_decisions.pop(route["request_key"], None)
    if (saved is None or saved[0] != os.getpid() or saved[1] is not threading.current_thread()
            or saved[2] is not host._store or saved[3] is not host._binding
            or saved[4] != route["intent_digest"] or saved[5] != route["configuration_id"]):
        raise ValueError("GATEWAY_EXECUTION_ROUTE_DECISION_UNAVAILABLE")


def _load_v8(host, state, key):
    host._check_state(state)
    if state["version"] != 8:
        raise ValueError("GATEWAY_EXECUTION_ROUTING_UPGRADE_REQUIRED")
    route = state["gateway"]["execution_routes"].get(key)
    if route is None:
        raise ValueError("GATEWAY_EXECUTION_ROUTE_NOT_FOUND")
    return route


def bind_parent(host, request_key, prepared):
    # Retire even if acquiring the durable-store lock fails.
    host._execution_route_decisions.pop(request_key, None)
    with host._store._lock():
        from bt_api_py.execution_routing import ExecutionPreparedRoute
        if type(prepared) is not ExecutionPreparedRoute:
            raise ValueError("GATEWAY_EXECUTION_PREPARED_INVALID")
        state = host._store._load()
        route = _load_v8(host, state, request_key)
        for name in ("account", "strategy", "request_key", "intent_digest", "configuration_id", "execution_domain_ref"):
            if getattr(prepared, name) != route[name] or type(getattr(prepared, name)) is not str:
                raise ValueError("GATEWAY_EXECUTION_ROUTE_IDENTITY")
        candidate = dict(route, kind="EXECUTION_PARENT", request_id=prepared.request_id,
                         request_sha256=prepared.request_sha256, parent_ref=prepared.parent_ref)
        if not _ref(prepared.request_id) or not _hex64(prepared.request_sha256) or not _ref(prepared.parent_ref):
            raise ValueError("GATEWAY_EXECUTION_PREPARED_INVALID")
        if route["kind"] != "PENDING":
            if route != candidate:
                raise ValueError("GATEWAY_EXECUTION_ROUTE_CONFLICT")
            return True
        state["gateway"]["execution_routes"][request_key] = candidate
        host._store._store(state, trim_history=False)
        return True


def bind_direct(host, request_key, route_kind):
    if type(route_kind) is not str or route_kind not in ("GATEWAY", "RISK"):
        raise ValueError("GATEWAY_EXECUTION_ROUTE_INVALID")
    with host._store._lock():
        state = host._store._load()
        route = _load_v8(host, state, request_key)
        if route["kind"] != "PENDING":
            if route["kind"] != route_kind:
                raise ValueError("GATEWAY_EXECUTION_ROUTE_CONFLICT")
            return True
        _consume_direct_decision(host, route)
        route["kind"] = route_kind
        host._store._store(state, trim_history=False)
        return True


def load_route(host, request_key):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] != 8:
            return None
        value = state["gateway"]["execution_routes"].get(request_key)
        return None if value is None else GatewayExecutionRoute(**value)
