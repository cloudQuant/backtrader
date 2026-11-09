"""Durable pre-event BT order descriptions, without venue or authority claims."""
from __future__ import annotations

import copy

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
        elif state["version"] == 5:
            if state["gateway"]["max_order_snapshot_bytes"] != max_order_snapshot_bytes:
                raise ValueError("GATEWAY_ORDER_CAPACITY_MISMATCH")
        else:
            raise ValueError("GATEWAY_ORDER_UPGRADE_REQUIRED")
    return host


def save_order_intent(host, intent, *, local_seq, bt_ref, snapshot):
    if not is_strict_int(local_seq, minimum=1) or not is_strict_int(bt_ref, minimum=1):
        raise ValueError("GATEWAY_FACT_INVALID")
    mapping = gateway_intent_to_mapping(intent)
    canonical = gateway_intent_from_mapping(mapping, expected_binding=host._binding)
    with host._store._lock():
        state = host._store._load()
        entries = host._check_state(state)
        if state["version"] != 5:
            raise ValueError("GATEWAY_ORDER_UPGRADE_REQUIRED")
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
            validate_order_state(state)
            changed = True
        if changed:
            host._store._store(state)


def iter_order_snapshots(host):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] != 5:
            return {}
        snapshots = state["gateway"]["order_snapshots"]
        return copy.deepcopy({key: snapshots[key] for key in sorted(snapshots)})


def load_order_snapshot(host, request_key):
    with host._store._lock():
        state = host._store._load()
        host._check_state(state)
        if state["version"] != 5:
            return None
        return copy.deepcopy(state["gateway"]["order_snapshots"].get(request_key))
