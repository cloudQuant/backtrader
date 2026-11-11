"""Durable pre-event BT order descriptions, without venue or authority claims.

Pending state version 7 (iteration 64) adds one record kind for orders placed
through the Risk service: the Gateway command exists under the Risk delegate's
principal on behalf of this strategy, so the strategy holds no own command
record. A *delegated command record* keeps, per request key, what Risk answered
(permit, reservation, view digest), whether Backtrader asked for the dispatch,
the delegate principal the Gateway reported for that key and the last observed
command state; durable delegated cancel attempts sit beside it. These are
local claims used to bind returns and to refuse anything else; they are not
venue facts or authority. Version 6 files are upgraded only when Risk is
selected; code that knows version 6 refuses a version 7 file.
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass

from bt_api_py.gateway_direct_client import gateway_intent_from_mapping, gateway_intent_to_mapping

from ._common import is_strict_int
from .gateway_execution_state import _json_bytes, _projection

_MAX_BYTES = 64 * 1024 * 1024
_STATE_KEYS = {"codec", "feeds", "orders", "positions", "trades", "groups"}
# Gateway records proving a reservation ended without any dispatch: released by
# the strategy, or expired by the Gateway (its TTL or owner generation passed).
_NEVER_SENT_FINAL = frozenset({"RELEASED", "EXPIRED"})
# Delegated command states as direct.delegated_command_status reports them.
DELEGATED_COMMAND_VERSIONS = {"RESERVED": 1, "DISPATCHING": 2, "SENT": 3, "NOT_SENT": 3,
                              "UNKNOWN": 3, "RELEASED": 2, "EXPIRED": 2}
_DELEGATED_FINAL = frozenset({"SENT", "NOT_SENT", "UNKNOWN", "RELEASED", "EXPIRED"})
_DELEGATED_KEYS = frozenset({"schema_version", "request_key", "reservation_id", "digest",
                             "permit_id", "view_digest", "actor_principal",
                             "dispatch_requested", "gateway_state", "gateway_version"})
_CANCEL_VERSIONS = {"REQUESTED": 1, "DISPATCHING": 2, "SENT": 3, "NOT_SENT": 3, "UNKNOWN": 3}
_CANCEL_PLAN_KEYS = frozenset({"schema_version", "binding", "route", "operation_id",
                               "request_key", "reservation_id", "digest",
                               "target_actor_principal"})
_CANCEL_OBSERVATION_KEYS = ("account_scope", "strategy_scope", "requester_principal",
                            "target_actor_principal", "request_key", "operation_id",
                            "attempt_id", "target_reservation_id", "target_digest", "state",
                            "version", "owner_generation", "attempt_generation")


@dataclass(frozen=True)
class GatewayDelegatedCommandRecord:
    """A Risk-routed order's local record (pending state version 7)."""

    request_key: str
    reservation_id: str
    digest: str
    permit_id: str | None
    view_digest: str | None
    actor_principal: str | None
    dispatch_requested: bool
    gateway_state: str | None
    gateway_version: int | None

    def to_mapping(self):
        return {"schema_version": 1, "request_key": self.request_key,
                "reservation_id": self.reservation_id, "digest": self.digest,
                "permit_id": self.permit_id, "view_digest": self.view_digest,
                "actor_principal": self.actor_principal,
                "dispatch_requested": self.dispatch_requested,
                "gateway_state": self.gateway_state, "gateway_version": self.gateway_version}


def _ref(value):
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= 256
    except UnicodeError:
        return False


def _hex64(value):
    return (type(value) is str and len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value))


def _binding_of(state):
    from .gateway_pending import _binding_from_mapping
    return _binding_from_mapping(state["gateway"]["binding"])


def _delegated_record(value, key, entries, binding):
    """Validate one stored delegated command record against its intent."""
    entry = entries.get(key)
    if (entry is None or type(value) is not dict or set(value) != _DELEGATED_KEYS
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["request_key"] != key
            # A key is either this strategy's own command or a delegated one.
            or any(entry[name] is not None for name in ("record", "marker_id", "release"))):
        raise ValueError("GATEWAY_DELEGATED_RECORD_INVALID")
    intent = gateway_intent_from_mapping(entry["intent"], expected_binding=binding)
    state, version = value["gateway_state"], value["gateway_version"]
    if (not _ref(value["reservation_id"]) or value["digest"] != intent.digest
            or (value["permit_id"] is not None and not _ref(value["permit_id"]))
            or (value["view_digest"] is not None and not _hex64(value["view_digest"]))
            or (value["actor_principal"] is not None
                and (not _ref(value["actor_principal"])
                     # The strategy's own principal never acts as its delegate.
                     or value["actor_principal"] == binding.principal))
            or type(value["dispatch_requested"]) is not bool
            or (state is None) != (version is None)
            or (state is not None and (type(version) is not int
                                       or DELEGATED_COMMAND_VERSIONS.get(state) != version))):
        raise ValueError("GATEWAY_DELEGATED_RECORD_INVALID")
    return GatewayDelegatedCommandRecord(key, value["reservation_id"], value["digest"],
        value["permit_id"], value["view_digest"], value["actor_principal"],
        value["dispatch_requested"], state, version)


def _route_mapping(route):
    scope, identity = route.scope, route.identity
    return {"mount": route.mount, "service_id": route.service_id,
            "instance_id": route.instance_id, "scope_ref": route.scope_ref,
            "scope": {"execution_domain_ref": scope.execution_domain_ref,
                      "account_ref": scope.account_ref, "account_refs": list(scope.account_refs),
                      "strategy_ref": scope.strategy_ref, "run_id": scope.run_id,
                      "manual_book_ref": scope.manual_book_ref,
                      "portfolio_ref": scope.portfolio_ref, "group_id": scope.group_id,
                      "leg_id": scope.leg_id},
            "identity": {"role": identity.role.value, "principal_ref": identity.principal_ref,
                         "actor_ref": identity.actor_ref, "delegate_ref": identity.delegate_ref}}


def _route_from(value):
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_py.gateway_direct_client import GatewayClientRoute

    if (type(value) is not dict or set(value) != {"mount", "service_id", "instance_id",
                                                   "scope_ref", "scope", "identity"}
            or type(value["scope"]) is not dict or type(value["identity"]) is not dict
            or type(value["scope"].get("account_refs")) is not list):
        raise ValueError("GATEWAY_DELEGATED_CANCEL_INVALID")
    identity = value["identity"]
    if set(identity) != {"role", "principal_ref", "actor_ref", "delegate_ref"}:
        raise ValueError("GATEWAY_DELEGATED_CANCEL_INVALID")
    return GatewayClientRoute(value["mount"], value["service_id"], value["instance_id"],
        value["scope_ref"], WireScope(**value["scope"]),
        WireIdentity(WireRole(identity["role"]), identity["principal_ref"],
                     identity["actor_ref"], identity["delegate_ref"]))


def _cancel_plan_mapping(plan):
    from .gateway_pending import _binding_mapping
    return {"schema_version": 1, "binding": _binding_mapping(plan.binding),
            "route": _route_mapping(plan.route), "operation_id": plan.operation_id,
            "request_key": plan.request_key, "reservation_id": plan.reservation_id,
            "digest": plan.digest, "target_actor_principal": plan.target_actor_principal}


def _delegated_cancel_plan(value, state, binding):
    """A durable delegated cancel plan bound to one known delegated command."""
    from bt_api_py.gateway_delegated_cancel import GatewayDelegatedCancelPlan
    from .gateway_pending import _binding_from_mapping

    gateway = state["gateway"]
    if (type(value) is not dict or set(value) != _CANCEL_PLAN_KEYS
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or _binding_from_mapping(value["binding"]) != binding
            or not all(_ref(value[name]) for name in ("operation_id", "request_key",
                                                      "reservation_id", "target_actor_principal"))
            or not _hex64(value["digest"])):
        raise ValueError("GATEWAY_DELEGATED_CANCEL_INVALID")
    key = value["request_key"]
    record = _delegated_record(gateway["delegated_commands"].get(key), key,
                               gateway["intents"], binding)
    intent = gateway_intent_from_mapping(gateway["intents"][key]["intent"],
                                         expected_binding=binding)
    route = _route_from(value["route"])
    if (route != intent.route or value["reservation_id"] != record.reservation_id
            or value["digest"] != record.digest
            or record.actor_principal is None
            or value["target_actor_principal"] != record.actor_principal):
        raise ValueError("GATEWAY_DELEGATED_CANCEL_TARGET_CONFLICT")
    return GatewayDelegatedCancelPlan(binding, route, value["operation_id"], key,
        value["reservation_id"], value["digest"], value["target_actor_principal"])


def _delegated_cancel_observation(value, plan, binding):
    from bt_api_py.gateway_delegated_cancel import GatewayDelegatedCancelObservation

    if type(value) is not dict or set(value) != set(_CANCEL_OBSERVATION_KEYS):
        raise ValueError("GATEWAY_DELEGATED_CANCEL_INVALID")
    observation = GatewayDelegatedCancelObservation(**value)
    if (observation.account_scope != binding.account_scope
            or observation.strategy_scope != binding.strategy_scope
            or observation.requester_principal != binding.principal
            or observation.target_actor_principal != plan.target_actor_principal
            or observation.request_key != plan.request_key
            or observation.operation_id != plan.operation_id
            or observation.target_reservation_id != plan.reservation_id
            or observation.target_digest != plan.digest
            or not all(_ref(getattr(observation, name))
                       for name in ("attempt_id", "owner_generation", "attempt_generation"))
            or type(observation.version) is not int
            or _CANCEL_VERSIONS.get(observation.state) != observation.version):
        raise ValueError("GATEWAY_DELEGATED_CANCEL_INVALID")
    return observation


def _validate_delegated(state):
    gateway = state["gateway"]
    binding = _binding_of(state)
    records, attempts = gateway["delegated_commands"], gateway["delegated_cancel_attempts"]
    if (type(records) is not dict or len(records) > gateway["max_entries"]
            or type(attempts) is not dict or len(attempts) > gateway["max_cancel_entries"]):
        raise ValueError("GATEWAY_DELEGATED_CAPACITY_INVALID")
    reservations = set()
    for key, value in records.items():
        record = _delegated_record(value, key, gateway["intents"], binding)
        if record.reservation_id in reservations:
            raise ValueError("GATEWAY_DELEGATED_RECORD_INVALID")
        reservations.add(record.reservation_id)
    for operation_id, attempt in attempts.items():
        if type(attempt) is not dict or set(attempt) != {"plan", "observation"}:
            raise ValueError("GATEWAY_DELEGATED_CANCEL_INVALID")
        plan = _delegated_cancel_plan(attempt["plan"], state, binding)
        if plan.operation_id != operation_id:
            raise ValueError("GATEWAY_DELEGATED_CANCEL_INVALID")
        if attempt["observation"] is not None:
            _delegated_cancel_observation(attempt["observation"], plan, binding)


def _snapshot(value, request_key, bt_ref, limit):
    # The execution checkpoint already supplies strict, bounded JSON validation.
    result = _projection(value, limit)
    state = result["state"]
    if (set(state) != _STATE_KEYS or type(state["codec"]) is not int
            or state["codec"] != 1
            or any(type(state[name]) is not dict
                   for name in ("feeds", "orders", "positions", "trades", "groups"))
            or set(state["orders"]) != {request_key}
            or state["positions"] or state["trades"]):
        raise ValueError("GATEWAY_ORDER_SNAPSHOT_INVALID")
    order = state["orders"][request_key]
    if (type(order) is not dict or not is_strict_int(order.get("ref"), minimum=1)
            or order["ref"] != bt_ref):
        raise ValueError("GATEWAY_ORDER_SNAPSHOT_REF_CONFLICT")
    return result


def validate_order_state(state):
    gateway = state["gateway"]
    limit, snapshots, entries = (gateway["max_order_snapshot_bytes"],
                                  gateway["order_snapshots"], gateway["intents"])
    if (not is_strict_int(limit, minimum=1) or limit > _MAX_BYTES
            or type(snapshots) is not dict or len(snapshots) > gateway["max_entries"]):
        raise ValueError("GATEWAY_ORDER_CAPACITY_INVALID")
    total = 0
    order_refs = set()
    for key, envelope in snapshots.items():
        if (type(key) is not str or key not in entries or type(envelope) is not dict
                or set(envelope) != {"schema_version", "local_seq", "bt_ref", "snapshot"}
                or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1
                or not is_strict_int(envelope["local_seq"], minimum=1)
                or not is_strict_int(envelope["bt_ref"], minimum=1)
                or entries[key]["local_seq"] != envelope["local_seq"]
                or entries[key]["bt_ref"] != envelope["bt_ref"]):
            raise ValueError("GATEWAY_ORDER_SNAPSHOT_BINDING_INVALID")
        if envelope["bt_ref"] in order_refs:
            raise ValueError("GATEWAY_ORDER_SNAPSHOT_REF_CONFLICT")
        order_refs.add(envelope["bt_ref"])
        snap = _snapshot(envelope["snapshot"], key, envelope["bt_ref"], limit)
        total += len(_json_bytes(snap))
        if total > limit:
            raise ValueError("GATEWAY_ORDER_CAPACITY_EXCEEDED")
    if state["version"] in (6, 7):
        notices = gateway["local_notifications"]
        if type(notices) is not dict or len(notices) > 2 * gateway["max_entries"]:
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_CAPACITY")
        for key, notice in notices.items():
            if key.startswith("reject:"):
                request_key = key[len("reject:"):]
                entry = entries.get(request_key)
                if (type(notice) is not dict or set(notice) !=
                        {"notification_id", "status", "bt_ref", "snapshot", "code"}
                        or request_key not in snapshots or request_key not in notices
                        or entry is None
                        or any(entry[name] is not None for name in ("record", "marker_id", "release"))
                        or request_key in gateway.get("delegated_commands", {})
                        or "cancel:" + request_key in notices
                        or type(notice["code"]) is not str or not _REJECT_CODE(notice["code"])):
                    raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
                reject_snapshot = _snapshot(notice["snapshot"], request_key,
                                            notice["bt_ref"], limit)
                if (reject_snapshot["state"]["orders"][request_key]["status"] != 8
                        or notice["status"] not in ("pending", "confirmed")
                        or notice["notification_id"] != _reject_notice_id(
                            state, request_key, notice["bt_ref"], reject_snapshot,
                            notice["code"])
                        or (notice["status"] == "confirmed"
                            and notices[request_key]["status"] != "confirmed")):
                    raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
                total += len(_json_bytes(reject_snapshot))
                if total > limit:
                    raise ValueError("GATEWAY_ORDER_CAPACITY_EXCEEDED")
                continue
            if key.startswith("cancel:"):
                request_key = key[len("cancel:"):]
                if (type(notice) is not dict or set(notice) !=
                        {"notification_id", "status", "bt_ref", "snapshot"}
                        or request_key not in snapshots or request_key not in notices
                        or not _never_sent_final(gateway, entries, request_key)):
                    raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
                cancel_snapshot = _snapshot(notice["snapshot"], request_key,
                                            notice["bt_ref"], limit)
                if (cancel_snapshot["state"]["orders"][request_key]["status"] != 5
                        or notice["status"] not in ("pending", "confirmed")
                        or notice["notification_id"] != _cancel_notice_id(
                            state, request_key, notice["bt_ref"], cancel_snapshot)
                        or (notice["status"] == "confirmed"
                            and notices[request_key]["status"] != "confirmed")):
                    raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
                total += len(_json_bytes(cancel_snapshot))
                if total > limit:
                    raise ValueError("GATEWAY_ORDER_CAPACITY_EXCEEDED")
                continue
            envelope = snapshots.get(key)
            if (envelope is None or type(notice) is not dict
                    or set(notice) != {"notification_id", "status"}
                    or envelope["snapshot"]["state"]["orders"][key]["status"] != 1
                    or notice["status"] not in ("pending", "confirmed")
                    or notice["notification_id"] != _notice_id(state, key, envelope)):
                raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
    if state["version"] == 7:
        _validate_delegated(state)


def _never_sent_final(gateway, entries, request_key):
    """The own record, or the Gateway state of the delegated command, ended unsent."""
    record = entries[request_key]["record"]
    if record is not None:
        return record["state"] in _NEVER_SENT_FINAL
    delegated = gateway.get("delegated_commands", {}).get(request_key)
    return delegated is not None and delegated["gateway_state"] in _NEVER_SENT_FINAL


def _notice_id(state, key, envelope):
    payload = {"domain": "backtrader.gateway.local-submitted.v1",
               "strategy_uuid": state["strategy_uuid"], "request_key": key,
               "order": envelope}
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _cancel_notice_id(state, key, bt_ref, snapshot):
    payload = {"domain": "backtrader.gateway.local-canceled.v1",
               "strategy_uuid": state["strategy_uuid"], "request_key": key,
               "bt_ref": bt_ref, "snapshot": snapshot}
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _REJECT_CODE(code):
    # A Gateway request-denial code: short upper-case ASCII identifier.
    return (0 < len(code) <= 64 and code.isascii() and code == code.strip()
            and all(ch.isupper() or ch.isdigit() or ch == "_" for ch in code))


def _reject_notice_id(state, key, bt_ref, snapshot, code):
    payload = {"domain": "backtrader.gateway.local-rejected.v1",
               "strategy_uuid": state["strategy_uuid"], "request_key": key,
               "bt_ref": bt_ref, "code": code, "snapshot": snapshot}
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def upgrade_for_local_notifications(host):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] == 5:
            state["version"] = 6
            state["gateway"]["local_notifications"] = {}
            host._store._store(state, trim_history=False)
        elif state["version"] not in (6, 7):
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_UPGRADE_REQUIRED")
    return host


def upgrade_for_order_state(cls, strategy_dir, strategy_uuid, binding, *,
                            max_order_snapshot_bytes, lock_timeout):
    if (not is_strict_int(max_order_snapshot_bytes, minimum=1)
            or max_order_snapshot_bytes > _MAX_BYTES):
        raise ValueError("INVALID_GATEWAY_ORDER_CAPACITY")
    host = cls(strategy_dir, strategy_uuid, binding, lock_timeout=lock_timeout)
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] == 4:
            state["version"] = 5
            state["gateway"]["max_order_snapshot_bytes"] = max_order_snapshot_bytes
            state["gateway"]["order_snapshots"] = {}
            host._store._store(state, trim_history=False)
        elif state["version"] in (5, 6, 7):
            if state["gateway"]["max_order_snapshot_bytes"] != max_order_snapshot_bytes:
                raise ValueError("GATEWAY_ORDER_CAPACITY_MISMATCH")
        else:
            raise ValueError("GATEWAY_ORDER_UPGRADE_REQUIRED")
    return host


def save_order_intent(host, intent, *, local_seq, bt_ref, snapshot, local_submitted=False):
    if type(local_submitted) is not bool:
        raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
    if not is_strict_int(local_seq, minimum=1) or not is_strict_int(bt_ref, minimum=1):
        raise ValueError("GATEWAY_FACT_INVALID")
    mapping = gateway_intent_to_mapping(intent)
    canonical = gateway_intent_from_mapping(mapping, expected_binding=host._binding)
    with host._store._lock():
        state = host._store._load()
        entries = host._check_state(state)
        if state["version"] not in (5, 6, 7):
            raise ValueError("GATEWAY_ORDER_UPGRADE_REQUIRED")
        if local_submitted and state["version"] not in (6, 7):
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_UPGRADE_REQUIRED")
        gateway = state["gateway"]
        snap = _snapshot(snapshot, canonical.request_key, bt_ref,
                         gateway["max_order_snapshot_bytes"])
        envelope = {"schema_version": 1, "local_seq": local_seq, "bt_ref": bt_ref,
                    "snapshot": snap}
        previous = gateway["order_snapshots"].get(canonical.request_key)
        entry = entries.get(canonical.request_key)
        if previous is None and entry is not None and any(
            entry[name] is not None for name in ("record", "marker_id", "release")
        ):
            raise ValueError("GATEWAY_ORDER_SNAPSHOT_TOO_LATE")
        if previous is not None and _json_bytes(previous) != _json_bytes(envelope):
            raise ValueError("GATEWAY_ORDER_SNAPSHOT_CONFLICT")
        changed = host._save_intent_in_state(state, mapping, canonical, local_seq, bt_ref)
        if previous is None:
            gateway["order_snapshots"][canonical.request_key] = envelope
            changed = True
        if local_submitted:
            notice_id = _notice_id(state, canonical.request_key, envelope)
            notices = gateway["local_notifications"]
            if canonical.request_key not in notices:
                if previous is not None:
                    raise ValueError("GATEWAY_LOCAL_NOTIFICATION_TOO_LATE")
                notices[canonical.request_key] = {"notification_id": notice_id,
                                                  "status": "pending"}
                changed = True
            elif notices[canonical.request_key]["notification_id"] != notice_id:
                raise ValueError("GATEWAY_LOCAL_NOTIFICATION_CONFLICT")
        validate_order_state(state)
        if changed:
            host._store._store(state)


def iter_order_snapshots(host):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] not in (5, 6, 7):
            return {}
        snapshots = state["gateway"]["order_snapshots"]
        return copy.deepcopy({key: snapshots[key] for key in sorted(snapshots)})


def load_order_snapshot(host, request_key):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] not in (5, 6, 7):
            return None
        return copy.deepcopy(state["gateway"]["order_snapshots"].get(request_key))


def local_notifications(host):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] not in (6, 7):
            return {}
        return copy.deepcopy(state["gateway"]["local_notifications"])


def save_released_notification(host, request_key, *, bt_ref, snapshot):
    if type(request_key) is not str or not is_strict_int(bt_ref, minimum=1):
        raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
    with host._store._lock():
        state = host._store._load()
        entries = host._check_state(state)
        if state["version"] not in (6, 7):
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_UPGRADE_REQUIRED")
        gateway = state["gateway"]
        entry = entries.get(request_key)
        if (entry is None or not _never_sent_final(gateway, entries, request_key)
                or request_key not in gateway["local_notifications"]):
            raise ValueError("GATEWAY_RELEASE_NOT_PROVEN")
        snap = _snapshot(snapshot, request_key, bt_ref, gateway["max_order_snapshot_bytes"])
        if snap["state"]["orders"][request_key]["status"] != 5:
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
        notice = {"notification_id": _cancel_notice_id(state, request_key, bt_ref, snap),
                  "status": "pending", "bt_ref": bt_ref, "snapshot": snap}
        key = "cancel:" + request_key
        old = gateway["local_notifications"].get(key)
        if old is not None:
            if any(old[field] != notice[field] for field in ("notification_id", "bt_ref", "snapshot")):
                raise ValueError("GATEWAY_LOCAL_NOTIFICATION_CONFLICT")
            return copy.deepcopy(old)
        gateway["local_notifications"][key] = notice
        validate_order_state(state)
        host._store._store(state, trim_history=False)
        return copy.deepcopy(notice)


def save_rejected_notification(host, request_key, *, bt_ref, snapshot, code):
    """Record a Gateway request denial for an intent that never got a record.

    Only a validated REQUEST_DENIED reserve reply proves no reservation was
    created; an unknown or lost reply must stay on the recovery path.
    """
    if (type(request_key) is not str or not is_strict_int(bt_ref, minimum=1)
            or type(code) is not str or not _REJECT_CODE(code)):
        raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
    with host._store._lock():
        state = host._store._load()
        entries = host._check_state(state)
        if state["version"] not in (6, 7):
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_UPGRADE_REQUIRED")
        gateway = state["gateway"]
        entry = entries.get(request_key)
        if (entry is None or request_key not in gateway["local_notifications"]
                or any(entry[name] is not None for name in ("record", "marker_id", "release"))
                or request_key in gateway.get("delegated_commands", {})):
            raise ValueError("GATEWAY_REJECTION_NOT_PROVEN")
        snap = _snapshot(snapshot, request_key, bt_ref, gateway["max_order_snapshot_bytes"])
        if snap["state"]["orders"][request_key]["status"] != 8:
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
        notice = {"notification_id": _reject_notice_id(state, request_key, bt_ref, snap, code),
                  "status": "pending", "bt_ref": bt_ref, "snapshot": snap, "code": code}
        key = "reject:" + request_key
        old = gateway["local_notifications"].get(key)
        if old is not None:
            if any(old[field] != notice[field]
                   for field in ("notification_id", "bt_ref", "snapshot", "code")):
                raise ValueError("GATEWAY_LOCAL_NOTIFICATION_CONFLICT")
            return copy.deepcopy(old)
        gateway["local_notifications"][key] = notice
        validate_order_state(state)
        host._store._store(state, trim_history=False)
        return copy.deepcopy(notice)


def confirm_local_notifications(host, entries):
    if type(entries) is not dict or not entries:
        raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] not in (6, 7):
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_UPGRADE_REQUIRED")
        notices = state["gateway"]["local_notifications"]
        for key, notice_id in entries.items():
            item = notices.get(key)
            if item is None or item["notification_id"] != notice_id:
                raise ValueError("GATEWAY_LOCAL_NOTIFICATION_CONFLICT")
        changed = False
        for key in entries:
            if notices[key]["status"] == "pending":
                notices[key]["status"] = "confirmed"
                changed = True
        if changed:
            validate_order_state(state)
            host._store._store(state, trim_history=False)


# --- pending state version 7: orders placed through the Risk service ---------------


def upgrade_for_risk_routing(host):
    """Explicitly extend a validated version 6 file to version 7 in place."""
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] == 6:
            state["version"] = 7
            state["gateway"]["delegated_commands"] = {}
            state["gateway"]["delegated_cancel_attempts"] = {}
            validate_order_state(state)
            host._store._store(state, trim_history=False)
        elif state["version"] != 7:
            raise ValueError("GATEWAY_RISK_ROUTING_UPGRADE_REQUIRED")
    return host


def _v7(host, state):
    entries = host._check_state(state)
    if state["version"] != 7:
        raise ValueError("GATEWAY_RISK_ROUTING_UPGRADE_REQUIRED")
    return entries


def load_delegated_command(host, request_key):
    with host._store._lock():
        state = host._store._load()
        entries = host._check_state(state)
        if state["version"] != 7:
            return None
        value = state["gateway"]["delegated_commands"].get(request_key)
        return None if value is None else _delegated_record(value, request_key, entries,
                                                            host._binding)


def save_delegated_command(host, request_key, *, reservation_id, digest, permit_id=None,
                           view_digest=None, actor_principal=None, dispatch_requested=False,
                           gateway_state=None, gateway_version=None):
    """Create or monotonically extend one delegated command record.

    Identity fields never change once stored; the actor principal is learned
    once and must equal it afterwards; a dispatch request is never withdrawn;
    the observed Gateway state only moves forward by version.
    """
    with host._store._lock():
        state = host._store._load()
        entries = _v7(host, state)
        records = state["gateway"]["delegated_commands"]
        old = records.get(request_key)
        new = {"schema_version": 1, "request_key": request_key,
               "reservation_id": reservation_id, "digest": digest, "permit_id": permit_id,
               "view_digest": view_digest, "actor_principal": actor_principal,
               "dispatch_requested": dispatch_requested is True,
               "gateway_state": gateway_state, "gateway_version": gateway_version}
        if old is None:
            if len(records) >= state["gateway"]["max_entries"]:
                raise ValueError("GATEWAY_DELEGATED_CAPACITY_EXCEEDED")
            merged = new
        else:
            merged = dict(old)
            if old["reservation_id"] != reservation_id or old["digest"] != digest:
                raise ValueError("GATEWAY_DELEGATED_IDENTITY_CONFLICT")
            for name, conflict in (("permit_id", "GATEWAY_DELEGATED_PERMIT_CONFLICT"),
                                   ("view_digest", "GATEWAY_DELEGATED_PERMIT_CONFLICT"),
                                   ("actor_principal", "GATEWAY_DELEGATED_PRINCIPAL_CONFLICT")):
                if new[name] is None:
                    continue
                if old[name] is not None and old[name] != new[name]:
                    raise ValueError(conflict)
                merged[name] = new[name]
            merged["dispatch_requested"] = old["dispatch_requested"] or new["dispatch_requested"]
            if gateway_state is not None:
                previous = old["gateway_version"]
                if previous is None or gateway_version > previous:
                    if old["gateway_state"] in _DELEGATED_FINAL:
                        raise ValueError("GATEWAY_DELEGATED_STATE_CONFLICT")
                    merged["gateway_state"], merged["gateway_version"] = gateway_state, gateway_version
                elif gateway_version == previous and gateway_state != old["gateway_state"]:
                    raise ValueError("GATEWAY_DELEGATED_STATE_CONFLICT")
                # an older observation never replaces a newer one
        record = _delegated_record(merged, request_key, entries, host._binding)
        if merged != old:
            records[request_key] = merged
            validate_order_state(state)
            host._store._store(state, trim_history=False)
        return record


def save_delegated_cancel_plan(host, plan):
    from bt_api_py.gateway_delegated_cancel import GatewayDelegatedCancelPlan

    if type(plan) is not GatewayDelegatedCancelPlan:
        raise ValueError("GATEWAY_DELEGATED_CANCEL_INVALID")
    mapping = _cancel_plan_mapping(plan)
    with host._store._lock():
        state = host._store._load()
        _v7(host, state)
        attempts = state["gateway"]["delegated_cancel_attempts"]
        canonical = _delegated_cancel_plan(mapping, state, host._binding)
        prior = attempts.get(canonical.operation_id)
        if prior is not None:
            # The first committed plan of an operation id wins; never overwritten.
            return _delegated_cancel_plan(prior["plan"], state, host._binding)
        if len(attempts) >= state["gateway"]["max_cancel_entries"]:
            raise ValueError("GATEWAY_CANCEL_CAPACITY_EXCEEDED")
        attempts[canonical.operation_id] = {"plan": mapping, "observation": None}
        validate_order_state(state)
        host._store._store(state, trim_history=False)
        return canonical


def load_delegated_cancel_plan(host, operation_id):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] != 7:
            return None
        attempt = state["gateway"]["delegated_cancel_attempts"].get(operation_id)
        return None if attempt is None else _delegated_cancel_plan(attempt["plan"], state,
                                                                   host._binding)


def save_delegated_cancel_observation(host, operation_id, observation):
    from bt_api_py.gateway_delegated_cancel import GatewayDelegatedCancelObservation

    if type(observation) is not GatewayDelegatedCancelObservation:
        raise ValueError("GATEWAY_DELEGATED_CANCEL_INVALID")
    mapping = {name: getattr(observation, name) for name in _CANCEL_OBSERVATION_KEYS}
    with host._store._lock():
        state = host._store._load()
        _v7(host, state)
        attempt = state["gateway"]["delegated_cancel_attempts"].get(operation_id)
        if attempt is None:
            raise ValueError("GATEWAY_CANCEL_PLAN_REQUIRED")
        plan = _delegated_cancel_plan(attempt["plan"], state, host._binding)
        current = _delegated_cancel_observation(mapping, plan, host._binding)
        if attempt["observation"] is not None:
            previous = _delegated_cancel_observation(attempt["observation"], plan, host._binding)
            if (previous.attempt_id != current.attempt_id
                    or previous.attempt_generation != current.attempt_generation
                    or current.version < previous.version
                    or (current.version == previous.version and current.state != previous.state)
                    or (current.version > previous.version
                        and previous.state in {"SENT", "NOT_SENT", "UNKNOWN"})):
                raise ValueError("GATEWAY_DELEGATED_CANCEL_CONFLICT")
        if attempt["observation"] != mapping:
            attempt["observation"] = mapping
            validate_order_state(state)
            host._store._store(state, trim_history=False)
        return current


def load_delegated_cancel_observation(host, operation_id):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] != 7:
            return None
        attempt = state["gateway"]["delegated_cancel_attempts"].get(operation_id)
        if attempt is None or attempt["observation"] is None:
            return None
        plan = _delegated_cancel_plan(attempt["plan"], state, host._binding)
        return _delegated_cancel_observation(attempt["observation"], plan, host._binding)
