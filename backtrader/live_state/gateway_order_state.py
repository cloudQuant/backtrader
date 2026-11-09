"""Durable pre-event BT order descriptions, without venue or authority claims."""
from __future__ import annotations

import copy
import hashlib

from bt_api_py.gateway_direct_client import gateway_intent_from_mapping, gateway_intent_to_mapping

from ._common import is_strict_int
from .gateway_execution_state import _json_bytes, _projection

_MAX_BYTES = 64 * 1024 * 1024
_STATE_KEYS = {"codec", "feeds", "orders", "positions", "trades", "groups"}


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
    if state["version"] == 6:
        notices = gateway["local_notifications"]
        if type(notices) is not dict or len(notices) > 2 * gateway["max_entries"]:
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_CAPACITY")
        for key, notice in notices.items():
            if key.startswith("cancel:"):
                request_key = key[len("cancel:"):]
                if (type(notice) is not dict or set(notice) !=
                        {"notification_id", "status", "bt_ref", "snapshot"}
                        or request_key not in snapshots or request_key not in notices
                        or entries[request_key]["record"] is None
                        or entries[request_key]["record"]["state"] != "RELEASED"):
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


def upgrade_for_local_notifications(host):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] == 5:
            state["version"] = 6
            state["gateway"]["local_notifications"] = {}
            host._store._store(state, trim_history=False)
        elif state["version"] != 6:
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
        elif state["version"] in (5, 6):
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
        if state["version"] not in (5, 6):
            raise ValueError("GATEWAY_ORDER_UPGRADE_REQUIRED")
        if local_submitted and state["version"] != 6:
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
        if state["version"] not in (5, 6):
            return {}
        snapshots = state["gateway"]["order_snapshots"]
        return copy.deepcopy({key: snapshots[key] for key in sorted(snapshots)})


def load_order_snapshot(host, request_key):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] not in (5, 6):
            return None
        return copy.deepcopy(state["gateway"]["order_snapshots"].get(request_key))


def local_notifications(host):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] != 6:
            return {}
        return copy.deepcopy(state["gateway"]["local_notifications"])


def save_released_notification(host, request_key, *, bt_ref, snapshot):
    if type(request_key) is not str or not is_strict_int(bt_ref, minimum=1):
        raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
    with host._store._lock():
        state = host._store._load()
        entries = host._check_state(state)
        if state["version"] != 6:
            raise ValueError("GATEWAY_LOCAL_NOTIFICATION_UPGRADE_REQUIRED")
        gateway = state["gateway"]
        entry = entries.get(request_key)
        if (entry is None or entry["record"] is None or entry["record"]["state"] != "RELEASED"
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


def confirm_local_notifications(host, entries):
    if type(entries) is not dict or not entries:
        raise ValueError("GATEWAY_LOCAL_NOTIFICATION_INVALID")
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] != 6:
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
