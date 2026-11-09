"""Explicit Store lifecycle for an independently hosted Gateway session.

The caller owns the pending host and supplies already-resolved transport keys.
This module neither connects a provider nor establishes trading readiness.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping
from copy import deepcopy


def compose_gateway_contract_metadata(strategy_config, contracts, explicit, error_type):
    """Combine local declarations with exact configured SDK instrument keys.

    These values describe local intent; they do not establish provider rules,
    market provenance, account authority, or permission to place orders.
    """
    from bt_api_base.market_protocol import MarketInstrumentKey

    keys = list(strategy_config.instruments_by_ref.values())
    instruments = {}
    for key in keys:
        if type(key) is not MarketInstrumentKey or key.native_symbol in instruments:
            raise error_type("GATEWAY_CONTRACT_SYMBOL_AMBIGUOUS")
        instruments[key.native_symbol] = key
    if contracts is None:
        contracts = {}
    if explicit is None:
        explicit = {}
    if not isinstance(contracts, Mapping) or not isinstance(explicit, Mapping):
        raise error_type("GATEWAY_CONTRACT_CONFIGURATION_INVALID")
    if any(type(k) is not str or k not in instruments for k in (*contracts, *explicit)):
        raise error_type("GATEWAY_CONTRACT_INSTRUMENT_UNKNOWN")
    route = strategy_config.exchange_name
    result = {}
    for symbol in sorted(set(contracts) | set(explicit)):
        key = instruments[symbol]
        configured = contracts.get(symbol)
        provided = explicit.get(symbol)
        if ((symbol in contracts and not isinstance(configured, Mapping))
                or (symbol in explicit and not isinstance(provided, Mapping))):
            raise error_type("GATEWAY_CONTRACT_CONFIGURATION_INVALID")
        configured = deepcopy(dict(configured or {}))
        provided = deepcopy(dict(provided or {}))
        for row in (configured, provided):
            if not row:
                continue
            if (type(row.get("quantity_unit")) is not str
                    or row["quantity_unit"] not in {"base", "contracts", "lots", "native"}
                    or type(row.get("time_in_force")) is not str
                    or row["time_in_force"] not in {"GTC", "GFD", "DAY", "IOC", "FOK"}):
                raise error_type("GATEWAY_CONTRACT_RULES_REQUIRED")
            if "exchange" in row and row["exchange"] != key.venue:
                raise error_type("GATEWAY_CONTRACT_INSTRUMENT_CONFLICT")
            if "exchange_name" in row and row["exchange_name"] != route:
                raise error_type("GATEWAY_CONTRACT_ROUTE_CONFLICT")
            if "instrument_key" in row:
                declared = row["instrument_key"]
                try:
                    if isinstance(declared, Mapping):
                        declared = MarketInstrumentKey.from_dict(dict(declared))
                except (TypeError, ValueError):
                    raise error_type("GATEWAY_CONTRACT_INSTRUMENT_CONFLICT") from None
                if type(declared) is not MarketInstrumentKey or declared != key:
                    raise error_type("GATEWAY_CONTRACT_INSTRUMENT_CONFLICT")
                row["instrument_key"] = declared.to_dict()
            if "gateway_rule_source" in row and row["gateway_rule_source"] != "local_configuration":
                raise error_type("GATEWAY_CONTRACT_SOURCE_CONFLICT")
        if symbol in contracts and not configured:
            raise error_type("GATEWAY_CONTRACT_RULES_REQUIRED")
        if symbol in explicit and not provided:
            raise error_type("GATEWAY_CONTRACT_RULES_REQUIRED")
        # A standalone explicit projection must already bind exact identity;
        # only a rules row from the named configuration may be composed.
        if symbol in explicit and ("instrument_key" not in provided or "exchange_name" not in provided):
            raise error_type("GATEWAY_CONTRACT_IDENTITY_REQUIRED")
        for field in configured.keys() & provided.keys():
            if configured[field] != provided[field]:
                raise error_type("GATEWAY_CONTRACT_RULE_CONFLICT")
        result[symbol] = {**configured, **provided, "instrument_key": key.to_dict(),
                          "exchange_name": route, "gateway_rule_source": "local_configuration"}
    return result


def _release_owned_gateway_lock(store):
    if store._gateway_owns_run_lock:
        store._gateway_run_lock.release()
        store._gateway_run_lock = None
        store._gateway_owns_run_lock = False


def _check_gateway_sequence_consistency(host, state, error_type):
    """Reject state that cannot preserve request, sequence and BT ref identity."""
    from ..live_state.atomic import read_json
    from ..live_state.pending import validate_pending_state

    path = state.pending.path
    raw = validate_pending_state(read_json(path), path, state.strategy_uuid)
    if raw["version"] not in (5, 6):
        raise error_type("GATEWAY_ORDER_STATE_UPGRADE_REQUIRED")
    initial_sequence = state.sequence.read()
    intents = host.list_intents()
    snapshots = host.iter_order_snapshots()
    keys = [intent.request_key for intent in intents]
    if len(set(keys)) != len(keys) or set(keys) != set(snapshots):
        raise error_type("GATEWAY_ORDER_STATE_INCOMPLETE")
    refs, local_sequences = {}, set()
    for key in keys:
        context = raw["gateway"]["intents"].get(key)
        entry = snapshots[key]
        if (type(context) is not dict or type(context.get("bt_ref")) is not int
                or context["bt_ref"] <= 0 or type(context.get("local_seq")) is not int
                or context["local_seq"] <= 0 or type(entry) is not dict
                or entry.get("bt_ref") != context["bt_ref"]
                or entry.get("local_seq") != context["local_seq"]):
            raise error_type("GATEWAY_ORDER_STATE_INCOMPLETE")
        ref, local_seq = context["bt_ref"], context["local_seq"]
        if ref in refs or local_seq in local_sequences:
            raise error_type("GATEWAY_ORDER_IDENTITY_DUPLICATE")
        if (ref > initial_sequence["ref_high_water"]
                or local_seq > initial_sequence["local_seq"]):
            raise error_type("GATEWAY_SEQUENCE_BEHIND_PENDING")
        refs[ref] = key
        local_sequences.add(local_seq)
    if raw["version"] == 6:
        notices = host.local_order_notifications()
        for notice_key, notice in notices.items():
            prefix = next((p for p in ("cancel:", "reject:") if notice_key.startswith(p)), None)
            if prefix is None:
                continue
            key, ref = notice_key[len(prefix):], notice["bt_ref"]
            if type(ref) is not int or ref <= 0 or key not in snapshots:
                raise error_type("GATEWAY_ORDER_STATE_INCOMPLETE")
            if ref > initial_sequence["ref_high_water"]:
                raise error_type("GATEWAY_SEQUENCE_BEHIND_PENDING")
            if ref in refs and refs[ref] != key:
                raise error_type("GATEWAY_ORDER_IDENTITY_DUPLICATE")
            refs[ref] = key
    # Each public host read uses the existing pending lock. Refuse concurrent
    # changes rather than combining observations from different states.
    if (read_json(path) != raw or state.sequence.read() != initial_sequence):
        raise error_type("GATEWAY_ORDER_STATE_CHANGED")


def start_gateway_store(store, *, data, broker, error_type):
    if store._gateway_pid != os.getpid():
        raise error_type("GATEWAY_WRONG_PROCESS")
    if data is not None:
        # The Feed's explicit adapter owns the Gateway subscription; Store
        # must never fall back to its direct MarketStreamPort path.
        from ..feeds.btapifeed import BtApiFeed
        enabled = getattr(data, "_gateway_market_enabled_for_store", None)
        if not isinstance(data, BtApiFeed) or not callable(enabled) or enabled(store) is not True:
            raise error_type("GATEWAY_MARKET_FEED_UNAVAILABLE")
    if store._gateway_closed:
        raise error_type("GATEWAY_STORE_CLOSED")
    if broker is not None and store._broker is not None and store._broker is not broker:
        raise error_type("GATEWAY_BROKER_CONFLICT")
    if broker is not None:
        store._broker = broker
    if data is not None and data not in store._data_feeds:
        store._data_feeds.append(data)
        hook = getattr(store._broker, "data_started", None)
        if callable(hook):
            hook(data)
        env = getattr(data, "_env", None)
        if env is not None:
            store._env = store._cerebro = env
    if store._started:
        if not store.is_connected:
            raise error_type("GATEWAY_SESSION_UNAVAILABLE")
        return
    if store._gateway_start_attempted:
        raise error_type("GATEWAY_START_REQUIRES_CLOSE")
    if store._gateway_run_lock is None:
        store._gateway_run_lock = store._gateway_state.acquire_run_lock()
        store._gateway_owns_run_lock = True
    try:
        if not store._gateway_run_lock.held:
            raise error_type("GATEWAY_RUN_LOCK_INVALID")
        from ..live_state.state_dir import StrategyStateDir
        current = StrategyStateDir(store._gateway_state.strategy_dir)
        if current.strategy_uuid != store._gateway_host._store.strategy_uuid:
            raise error_type("GATEWAY_HOST_IDENTITY_MISMATCH")
        _check_gateway_sequence_consistency(store._gateway_host, current, error_type)
        # Before any Strategy is created, restore the framework's existing
        # global ref basis from this strategy's durable high-water mark.
        store._gateway_state.sequence.restore_ref_basis()
    except BaseException:
        _release_owned_gateway_lock(store)
        raise
    store._gateway_start_attempted = True
    api = store._gateway_strategy_config.create_api(
        host=store._gateway_host, cancel_host=store._gateway_host,
        security_profiles=store._gateway_security_profiles
    )
    # Retain even on an ambiguous start failure, so stop can close this exact
    # session and no second runtime is created while cleanup is uncertain.
    store._api = api
    try:
        snapshot = api.start(timeout_seconds=store._command_shutdown_timeout)
        if (snapshot.state != "running" or snapshot.healthy is not True
                or snapshot.thread_alive is not True):
            raise error_type("GATEWAY_SESSION_UNAVAILABLE")
    except BaseException:
        store._shutdown_state = "INCOMPLETE"
        raise
    store._connected = True
    store._started = True
    store._shutdown_state = "RUNNING"


def _close_with_cleanup_retry(api, timeout):
    """Close the SDK facade, retrying its own retryable cleanup until ``timeout``.

    ``CLEANUP_FAILED`` means the client runtime kept its resources and waits for
    another close (for example a market bootstrap still pending at the Gateway,
    I63-E100); each further close lets it retry that cleanup. A zero timeout
    never retries; the caller then records INCOMPLETE as before.
    """
    deadline = time.monotonic() + float(timeout)
    while True:
        remaining = deadline - time.monotonic()
        try:
            return api.close(timeout_seconds=remaining if timeout and remaining > 0 else 1e-9)
        except Exception as exc:
            if (getattr(exc, "code", None) != "CLEANUP_FAILED" or not timeout
                    or deadline - time.monotonic() <= 0.2):
                raise
        time.sleep(0.2)


def stop_gateway_store(store, *, timeout):
    if store._gateway_pid != os.getpid():
        raise RuntimeError("GATEWAY_WRONG_PROCESS")
    if timeout is None:
        timeout = store._command_shutdown_timeout
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
        raise ValueError("invalid Gateway stop timeout")
    api = store._api
    if api is None:
        store._connected = False
        store._started = False
        _release_owned_gateway_lock(store)
        if store._gateway_start_attempted:
            store._gateway_closed = True
        return store.get_command_health()
    # Fence Store use immediately, including zero-timeout and uncertain close.
    store._connected = False
    store._started = False
    try:
        # Even a non-waiting stop must first fence previously handed-out API
        # references. The SDK sets its facade to closing before waiting.
        snapshot = _close_with_cleanup_retry(api, timeout)
    except Exception as exc:
        if timeout == 0 and getattr(exc, "code", None) == "CLOSE_TIMEOUT_WORKER_ALIVE":
            store._shutdown_state = "INCOMPLETE"
            return store.get_command_health()
        store._shutdown_state = "INCOMPLETE"
        raise
    except BaseException:
        store._shutdown_state = "INCOMPLETE"
        raise
    if (snapshot.state != "closed" or snapshot.thread_alive is not False
            or snapshot.cleanup_failures != 0 or snapshot.unregister_uncertainties != 0
            or snapshot.owner_cleanup_uncertainties != 0):
        store._shutdown_state = "INCOMPLETE"
        return store.get_command_health()
    try:
        _release_owned_gateway_lock(store)
    except BaseException:
        store._shutdown_state = "INCOMPLETE"
        raise
    store._api = None
    store._connected = False
    store._started = False
    store._gateway_closed = True
    store._shutdown_state = "PASS"
    return store.get_command_health()
