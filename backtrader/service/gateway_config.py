"""Explicit Store lifecycle for an independently hosted Gateway session.

The caller owns the pending host and supplies already-resolved transport keys.
This module neither connects a provider nor establishes trading readiness.
"""

from __future__ import annotations

import math
import os
import stat
import time
from collections.abc import Mapping
from copy import deepcopy

from ..utils.log_message import get_logger

_LOG = get_logger(__name__)
# Seconds between attempts to register a new session after one was lost.
_RECONNECT_BACKOFF = (0.0, 1.0, 2.0, 5.0, 10.0, 30.0)
_EXECUTION_DB_FILENAME = "gateway_execution_routing.sqlite"
_MARKET_SESSION_DRAIN_CANCELLED = object()


def _gateway_state_dir_trusted(directory):
    """Owner-only, no-follow state directory check (POSIX / Windows parity)."""
    if os.name != "posix":
        from bt_api_py._win32_security import (
            Win32SecurityUnavailable, inspect_owner, is_reparse_point,
        )
        try:
            if is_reparse_point(directory) or not os.path.isdir(directory):
                return False
            owner = inspect_owner(directory)
            return bool(owner.is_current_user and not owner.others_writable)
        except (Win32SecurityUnavailable, OSError):
            return False
    try:
        info = os.lstat(directory)
    except OSError:
        return False
    owner = getattr(os, "getuid", lambda: info.st_uid)()
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == owner
            and not info.st_mode & 0o022)


def _gateway_db_identity(fd, path):
    """Identity tuple for the open DB handle and the path, or None if untrusted."""
    if os.name != "posix":
        from bt_api_py._win32_security import (
            Win32SecurityUnavailable, inspect_owner, is_reparse_point,
        )
        try:
            if is_reparse_point(path):
                return None
            owner = inspect_owner(path)
            if not owner.is_current_user or owner.others_writable:
                return None
            # On Windows lstat().st_dev/st_ino are the volume serial and file
            # id, matching fstat() on the already-open handle.  Comparing them
            # detects a path swap without reopening (which the native share
            # mode of this handle would refuse).
            info = os.fstat(fd)
            named = os.lstat(path)
            if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(named.st_mode)
                    or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)
                    or info.st_nlink != 1):
                return None
            return (info.st_dev, info.st_ino)
        except (Win32SecurityUnavailable, OSError):
            return None
    try:
        info = os.fstat(fd)
        named = os.lstat(path)
    except OSError:
        return None
    if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(named.st_mode)
            or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
        return None
    owner = getattr(os, "getuid", lambda: info.st_uid)()
    if info.st_uid != owner or info.st_nlink != 1:
        return None
    return (info.st_dev, info.st_ino)


def _open_gateway_execution_db(store):
    """Open the strategy-owned routing journal only while its run lock is held."""
    if store._gateway_execution_db is not None:
        return store._gateway_execution_db
    if store._gateway_run_lock is None or not store._gateway_run_lock.held:
        raise RuntimeError("GATEWAY_RUN_LOCK_INVALID")
    import sqlite3
    from bt_api_py.execution_routing import install_execution_routing_tables

    directory = store._gateway_state.paths.state_dir
    if not _gateway_state_dir_trusted(directory):
        raise ValueError("GATEWAY_EXECUTION_STATE_PATH_INVALID")
    path = os.path.join(directory, _EXECUTION_DB_FILENAME)
    parents = _gateway_execution_parent_routes(store)
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    if not parents:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        if _gateway_db_identity(fd, path) is None:
            raise ValueError("GATEWAY_EXECUTION_STATE_PATH_INVALID")
        db = sqlite3.connect(path, isolation_level=None)
        try:
            if _gateway_db_identity(fd, path) is None:
                raise ValueError("GATEWAY_EXECUTION_STATE_PATH_INVALID")
            db.execute("BEGIN IMMEDIATE")
            try:
                install_execution_routing_tables(db)
                db.commit()
            except BaseException:
                if db.in_transaction:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                raise
        except BaseException:
            if store._gateway_execution_db is db:
                store._gateway_execution_db = None
            try:
                db.close()
            except Exception:
                pass
            raise
        store._gateway_execution_db = db
        return db
    finally:
        os.close(fd)


def _close_gateway_execution_db(store):
    db = store._gateway_execution_db
    if db is not None:
        db.close()
        store._gateway_execution_db = None


def _gateway_execution_parent_routes(store):
    """Read durable parent bindings without mixing different host snapshots."""
    from ..live_state.atomic import read_json

    host = store._gateway_host
    path = store._gateway_state.pending.path
    before = read_json(path)
    parents = []
    for intent in host.list_intents():
        route = host.load_execution_route(intent.request_key)
        if route is not None and route.kind == "EXECUTION_PARENT":
            parents.append((intent, route))
    if read_json(path) != before:
        raise ValueError("GATEWAY_ORDER_STATE_CHANGED")
    return parents


def _verify_gateway_execution_parents(store, api):
    """Reject missing or rolled-back parent journal records before startup."""
    if getattr(store._gateway_strategy_config, "execution_selection", None) is None:
        return
    from bt_api_py.execution_routing import ExecutionPreparedRoute
    from ..live_state.atomic import read_json

    path = store._gateway_state.pending.path
    before = read_json(path)
    for intent, route in _gateway_execution_parent_routes(store):
        prepared = ExecutionPreparedRoute(
            account=route.account, strategy=route.strategy, request_key=route.request_key,
            intent_digest=route.intent_digest, request_id=route.request_id,
            request_sha256=route.request_sha256, configuration_id=route.configuration_id,
            execution_domain_ref=route.execution_domain_ref, parent_ref=route.parent_ref,
        )
        if api.verify_execution_parent_route(intent, prepared) is not True:
            raise ValueError("GATEWAY_EXECUTION_JOURNAL_MISMATCH")
    if read_json(path) != before:
        raise ValueError("GATEWAY_ORDER_STATE_CHANGED")


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


def _create_gateway_api(store):
    """Compose the SDK facade; with Risk selected the pending host also keeps
    durable delegated cancel plans (orders placed through Risk are cancelled as
    this strategy's delegated commands, D64-02)."""
    options = {}
    selected = getattr(store._gateway_strategy_config, "execution_selection", None) is not None
    if getattr(store._gateway_strategy_config, "risk_selection", None) is not None or selected:
        store._gateway_host.upgrade_for_local_notifications()  # v5 -> v6 first
        store._gateway_host.upgrade_for_risk_routing()          # v6 -> v7
    if getattr(store._gateway_strategy_config, "risk_selection", None) is not None:
        options["delegated_cancel_host"] = store._gateway_host
    if selected:
        store._gateway_host.upgrade_for_execution_routing()
        options["execution_db"] = _open_gateway_execution_db(store)
    if selected:
        store._gateway_composition_uncertain = True
        binding = store._gateway_composition_binding = (
            store._api, store._gateway_run_lock, store._gateway_execution_db,
        )
    try:
        api = store._gateway_strategy_config.create_api(
            host=store._gateway_host, cancel_host=store._gateway_host,
            security_profiles=store._gateway_security_profiles, **options
        )
    except BaseException as exc:
        if selected:
            owner = getattr(exc, "cleanup_owner", None)
            store._gateway_composition_cleanup_owner = owner
            if store._gateway_composition_binding is binding:
                store._gateway_composition_binding = (*binding, owner)
        raise
    store._gateway_composition_uncertain = False
    store._gateway_composition_binding = None
    return api


def _retry_gateway_composition_cleanup(store, timeout):
    """Confirm the exact failed composition before reusing its resources."""
    binding = store._gateway_composition_binding
    owner = store._gateway_composition_cleanup_owner

    def same_binding():
        return (type(binding) is tuple and len(binding) == 4
                and store._gateway_composition_binding is binding
                and store._gateway_composition_cleanup_owner is owner and owner is binding[3]
                and store._api is binding[0] and store._gateway_run_lock is binding[1]
                and store._gateway_execution_db is binding[2]
                and binding[1] is not None and binding[1].held and binding[2] is not None)

    if owner is None or not same_binding():
        return False
    try:
        if owner.cleanup_confirmed is not True:
            owner.close(timeout_seconds=timeout if timeout else 1e-9)
        if owner.cleanup_confirmed is not True or not same_binding():
            return False
    except Exception:
        return False
    store._gateway_composition_cleanup_owner = None
    store._gateway_composition_binding = None
    store._gateway_composition_uncertain = False
    return True


def _release_owned_gateway_lock(store):
    if store._gateway_owns_run_lock:
        store._gateway_run_lock.release()
        store._gateway_run_lock = None
        store._gateway_owns_run_lock = False


def _gateway_facade_cleanup_confirmed(api):
    """Require the SDK's explicit confirmation for all facade-owned resources."""
    try:
        state = api.lifecycle_state
        return api.cleanup_confirmed is True and type(state) is str and state == "closed"
    except Exception:
        return False


def _check_gateway_sequence_consistency(host, state, error_type, *, execution_selection=None):
    """Reject state that cannot preserve request, sequence and BT ref identity."""
    from ..live_state.atomic import read_json
    from ..live_state.pending import validate_pending_state

    path = state.pending.path
    raw = validate_pending_state(read_json(path), path, state.strategy_uuid)
    if raw["version"] not in (5, 6, 7, 8):
        raise error_type("GATEWAY_ORDER_STATE_UPGRADE_REQUIRED")
    if raw["version"] == 8:
        if execution_selection is None:
            raise error_type("GATEWAY_EXECUTION_SELECTION_REQUIRED")
        for route in raw["gateway"]["execution_routes"].values():
            try:
                config = execution_selection.routing
                same = (route["configuration_id"] == config.configuration_id
                        and route["account"] == config.account_ref
                        and route["strategy"] == config.strategy_ref
                        and route["execution_domain_ref"] == config.execution_domain_ref)
            except (AttributeError, KeyError, TypeError):
                same = False
            if not same:
                raise error_type("GATEWAY_EXECUTION_CONFIGURATION_MISMATCH")
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
    if raw["version"] in (6, 7, 8):
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
        from ..feeds.base_btapi_feed import BaseBtApiFeed
        from ..feeds.direct_btapi_feed import DirectBtApiFeed
        enabled = getattr(data, "_gateway_market_enabled_for_store", None)
        if (not isinstance(data, BaseBtApiFeed) or isinstance(data, DirectBtApiFeed)
                or not callable(enabled) or enabled(store) is not True):
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
        _check_gateway_sequence_consistency(
            store._gateway_host, current, error_type,
            execution_selection=getattr(store._gateway_strategy_config, "execution_selection", None),
        )
        # Before any Strategy is created, restore the framework's existing
        # global ref basis from this strategy's durable high-water mark.
        store._gateway_state.sequence.restore_ref_basis()
    except BaseException:
        _release_owned_gateway_lock(store)
        raise
    store._gateway_start_attempted = True
    try:
        api = _create_gateway_api(store)
    except BaseException:
        # A failed SDK composition may have retained a still-running owner.
        # Without a positive cleanup proof the borrowed DB and lock stay held.
        store._shutdown_state = "INCOMPLETE"
        raise
    # Retain even on an ambiguous start failure, so stop can close this exact
    # session and no second runtime is created while cleanup is uncertain.
    store._api = api
    try:
        _verify_gateway_execution_parents(store, api)
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


def gateway_session_recoverable(store):
    """Whether this Store still runs its Gateway session slot in this process.

    True while the Store is started, owns its run lock and has not been
    stopped; only then may a lost SDK session be replaced by a new one.
    """
    return bool(
        getattr(store, "_gateway_mode", False) and store._gateway_pid == os.getpid()
        and store._connected and store._started and not store._gateway_closed
        and store._api is not None and store._gateway_run_lock is not None
        and store._gateway_run_lock.held
    )


def reconnect_gateway_store(store, *, timeout=None):
    """Replace a lost SDK Gateway session inside the same process (D63-03).

    A strategy keeps running while its Gateway is restarted or its lease ran
    out: the old client runtime is closed and a new session registers with the
    Gateway again (a restarted Gateway has a new service epoch, so the old
    registration can never be renewed). Returns True once a new healthy
    session is installed. Returns False while that is not possible yet (the
    old runtime has not released its resources, the Gateway is unreachable,
    the old lease has not expired); the caller keeps waiting and calls again,
    and attempts are spaced by a backoff.

    This only re-establishes the connection. It never changes the strategy
    state, the run lock or the pending host, never retries a command, and
    never falls back to a direct connection. Whether orders may be sent again
    is decided afterwards by the usual recovery and admission checks.
    """
    if not gateway_session_recoverable(store):
        return False
    if timeout is None:
        timeout = store._command_shutdown_timeout
    deadline = time.monotonic() + float(timeout)
    state = store.gateway_session_state()
    if state == "CONNECTED":
        from .gateway_market_adapter import (
            begin_gateway_market_session_drain,
            end_gateway_market_session_drain,
            resume_gateway_market_session_drain,
        )
        pending_drain = begin_gateway_market_session_drain(
            store, store._api, pending_only=True, deadline=deadline
        )
        if pending_drain is None:
            return False
        complete = pending_drain[5]
        end_gateway_market_session_drain(pending_drain)
        if complete is not True:
            resume_gateway_market_session_drain(pending_drain, deadline=deadline)
            return False
        return resume_gateway_market_session_drain(pending_drain, deadline=deadline)
    if state != "LOST":
        return False
    now = time.monotonic()
    if now < store._gateway_reconnect_next:
        return False
    attempt = store._gateway_reconnect_attempt
    store._gateway_reconnect_next = now + _RECONNECT_BACKOFF[min(attempt, len(_RECONNECT_BACKOFF) - 1)]
    store._gateway_reconnect_attempt = attempt + 1
    def waiting(reason, error=None):
        # Name why the strategy is still waiting, once per distinct cause.
        code = getattr(error, "code", None)
        if error is not None:
            reason += ":" + (code if type(code) is str and code.isupper() else type(error).__name__)
        if reason != store._gateway_reconnect_reason:
            store._gateway_reconnect_reason = reason
            _LOG.warning("Gateway session not re-registered yet: %s", reason)
        return False

    api = store._api
    run_lock = store._gateway_run_lock
    composition_remaining = max(0.0, deadline - time.monotonic())
    if (store._gateway_composition_uncertain
            and not _retry_gateway_composition_cleanup(store, composition_remaining)):
        return waiting("COMPOSITION_CLEANUP_UNCONFIRMED")
    if (store._api is not api or store._gateway_run_lock is not run_lock
            or not gateway_session_recoverable(store)):
        return waiting("OLD_SESSION_BINDING_CHANGED")
    from .gateway_market_adapter import (
        begin_gateway_market_session_drain,
        end_gateway_market_session_drain,
        resume_gateway_market_session_drain,
    )
    try:
        drain = begin_gateway_market_session_drain(
            store, api, deadline=deadline
        )
    except Exception as error:
        return waiting("MARKET_LEASE_DRAIN_FAILED", error)
    if drain is None:
        return waiting("MARKET_LEASE_DRAIN_UNCONFIRMED")
    if drain[5] is not True:
        end_gateway_market_session_drain(drain)
        if (store.gateway_session_state() == "CONNECTED"
                and store._api is api and store._gateway_run_lock is run_lock
                and gateway_session_recoverable(store)):
            resume_gateway_market_session_drain(drain, deadline=deadline)
        return waiting("MARKET_LEASE_DRAIN_UNCONFIRMED")
    try:
        result = _reconnect_gateway_store_after_drain(
            store, api, run_lock, timeout, deadline, attempt, waiting
        )
    finally:
        end_gateway_market_session_drain(drain)
    if result is _MARKET_SESSION_DRAIN_CANCELLED:
        if store.gateway_session_state() != "CONNECTED":
            return waiting("OLD_SESSION_STATE_CHANGED")
        resumed = resume_gateway_market_session_drain(drain, deadline=deadline)
        if not resumed:
            return waiting("MARKET_LEASE_RESUME_UNCONFIRMED")
        if store.gateway_session_state() == "CONNECTED":
            return True
        return waiting("OLD_SESSION_STATE_CHANGED")
    if (store._api is api
            and store._gateway_run_lock is run_lock
            and gateway_session_recoverable(store)
            and store.gateway_session_state() == "CONNECTED"):
        resume_gateway_market_session_drain(drain, deadline=deadline)
    return result


def _reconnect_gateway_store_after_drain(
        store, api, run_lock, timeout, deadline, attempt, waiting):
    """Close and replace a Store API after all exact BT leases were drained."""
    if (store._api is not api or store._gateway_run_lock is not run_lock
            or not gateway_session_recoverable(store)):
        return waiting("OLD_SESSION_BINDING_CHANGED")
    if store.gateway_session_state() != "LOST":
        return _MARKET_SESSION_DRAIN_CANCELLED
    remaining = max(0.0, deadline - time.monotonic())
    if remaining <= 0:
        return waiting("MARKET_LEASE_DRAIN_TIMEOUT")
    try:
        closed = _close_with_cleanup_retry(api, remaining)
    except Exception as error:
        return waiting("OLD_SESSION_CLOSE_FAILED", error)
    # The SDK close returns only after the runtime closed every transport and
    # owner resource (otherwise it raises CLEANUP_FAILED or a timeout). A
    # runtime that failed (lease lost, Gateway restarted) ends in "failed",
    # not "closed". A second runtime is never started beside a live thread.
    if closed.state not in ("closed", "failed") or closed.thread_alive is not False:
        return waiting("OLD_SESSION_STILL_RUNNING")
    if not _gateway_facade_cleanup_confirmed(api):
        return waiting("OLD_SESSION_CLEANUP_UNCONFIRMED")
    if (store._api is not api or store._gateway_run_lock is not run_lock
            or not gateway_session_recoverable(store)):
        return waiting("OLD_SESSION_BINDING_CHANGED")
    # Its counters now only say what the old Gateway side could not be told
    # (unregister, unsubscribe): that registration ends with its lease or
    # with its Gateway and is not a reason to keep the strategy waiting.
    unresolved = (closed.cleanup_failures, closed.unregister_uncertainties,
                  closed.owner_cleanup_uncertainties)
    try:
        api = _create_gateway_api(store)
    except Exception as error:
        return waiting("COMPOSITION_FAILED", error)
    # Retained even when its start is ambiguous, exactly as on the first
    # start: the next attempt closes this session before creating another.
    store._api = api
    try:
        _verify_gateway_execution_parents(store, api)
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            return waiting("REGISTRATION_TIMEOUT")
        started = api.start(timeout_seconds=remaining)
    except Exception as error:
        return waiting("REGISTRATION_FAILED", error)
    if (started.state != "running" or started.healthy is not True
            or started.thread_alive is not True):
        return waiting("REGISTRATION_NOT_HEALTHY")
    store._gateway_reconnect_reason = None
    store._gateway_reconnect_attempt = 0
    store._gateway_reconnect_next = 0.0
    store._gateway_session_generation += 1
    _LOG.info("Gateway session re-registered in this process (session %d, after %d attempt(s); "
              "old session left %d/%d/%d unconfirmed cleanup, unregister, owner item(s))",
              store._gateway_session_generation, attempt + 1, *unresolved)
    return True


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
    deadline = time.monotonic() + float(timeout)
    api = store._api
    run_lock = store._gateway_run_lock
    if store._gateway_composition_uncertain:
        store._connected = False
        store._started = False
        store._shutdown_state = "INCOMPLETE"
        remaining = max(0.0, deadline - time.monotonic())
        if not _retry_gateway_composition_cleanup(store, remaining):
            return store.get_command_health()
    if api is None:
        store._connected = False
        store._started = False
        try:
            _close_gateway_execution_db(store)
        except BaseException:
            store._shutdown_state = "INCOMPLETE"
            raise
        _release_owned_gateway_lock(store)
        if store._gateway_start_attempted:
            store._gateway_closed = True
            store._shutdown_state = "PASS"
        return store.get_command_health()
    # Fence Store use immediately, including zero-timeout and uncertain close.
    store._connected = False
    store._started = False
    from .gateway_market_adapter import (
        begin_gateway_market_session_drain,
        end_gateway_market_session_drain,
    )
    try:
        drain = begin_gateway_market_session_drain(
            store, api, deadline=deadline
        )
    except BaseException:
        store._shutdown_state = "INCOMPLETE"
        raise
    if drain is None:
        store._shutdown_state = "INCOMPLETE"
        return store.get_command_health()
    if drain[5] is not True:
        end_gateway_market_session_drain(drain)
        store._shutdown_state = "INCOMPLETE"
        return store.get_command_health()
    try:
        return _stop_gateway_store_after_market_drain(
            store, api, run_lock, deadline, zero_timeout=(timeout == 0)
        )
    finally:
        end_gateway_market_session_drain(drain)


def _stop_gateway_store_after_market_drain(
        store, api, run_lock, deadline, *, zero_timeout=False):
    """Close a stopped Store API only after every local market lease drained."""
    remaining = max(0.0, deadline - time.monotonic())
    if remaining <= 0 and not zero_timeout:
        store._shutdown_state = "INCOMPLETE"
        return store.get_command_health()
    try:
        # Even a non-waiting stop must first fence previously handed-out API
        # references. The SDK sets its facade to closing before waiting. Keep
        # the established zero-timeout contract: make one 1 ns close request
        # after a complete (possibly empty) lease drain, but never wait for an
        # unresolved lease or exceed a positive shared deadline.
        snapshot = _close_with_cleanup_retry(api, remaining)
    except Exception as exc:
        if remaining <= 0.01 and getattr(exc, "code", None) == "CLOSE_TIMEOUT_WORKER_ALIVE":
            store._shutdown_state = "INCOMPLETE"
            return store.get_command_health()
        store._shutdown_state = "INCOMPLETE"
        raise
    except BaseException:
        store._shutdown_state = "INCOMPLETE"
        raise
    if (snapshot.state != "closed" or snapshot.thread_alive is not False
            or snapshot.cleanup_failures != 0 or snapshot.unregister_uncertainties != 0
            or snapshot.owner_cleanup_uncertainties != 0
            or not _gateway_facade_cleanup_confirmed(api)
            or store._api is not api or store._gateway_run_lock is not run_lock):
        store._shutdown_state = "INCOMPLETE"
        return store.get_command_health()
    try:
        _close_gateway_execution_db(store)
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
