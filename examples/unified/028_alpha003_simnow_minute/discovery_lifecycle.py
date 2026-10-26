"""Bounded normal shutdown for a discovery-only RegisteredSimStore.

This module does not create a Store, load configuration, or contact a provider.
The caller supplies the exact Store whose read-only discovery has finished.
"""

from __future__ import annotations

import math
import re
import sys
import threading
import weakref
from dataclasses import dataclass, replace
from types import ModuleType
from typing import Any, Dict, Optional


_RECEIPT_MODULE = "bt_api_ctp.ctp.client"
_NATIVE_STOP_RECEIPT = "CtpNativeStopReceipt"
_STARTUP_STOP_RECEIPT = "CtpNativeStartupStopReceipt"
_STARTUP_OUTCOMES = frozenset(
    {
        "preflight_no_owner",
        "factory_uncertain",
        "api_created_unconfirmed",
        "api_created_released",
    }
)
_SHUTDOWN_STATES = frozenset(
    {"NOT_STARTED", "RUNNING", "PASS", "INCOMPLETE", "FAIL"}
)
_OWNER_STATES: Dict[int, "_OwnerState"] = {}
_OWNER_STATES_LOCK = threading.RLock()


@dataclass(frozen=True)
class ClientStopObservation:
    """Redacted facts from one typed SDK stop receipt."""

    present: bool
    receipt_present: bool
    complete: Optional[bool] = None
    connection_generation: Optional[int] = None
    native_released: Optional[bool] = None
    join_required: Optional[bool] = None
    join_completed: Optional[bool] = None
    thread_alive: Optional[bool] = None
    timed_out: Optional[bool] = None
    startup_outcome: Optional[str] = None


@dataclass(frozen=True)
class DiscoveryStoreCloseResult:
    """Finite close facts; this projection never contains clients or errors."""

    status: str
    reason_code: str
    complete: bool
    already_attempted: bool
    store_stop_attempted: bool
    store_stop_returned: Optional[bool]
    store_connected_before: Optional[bool]
    store_connected_after: Optional[bool]
    wrapper_connected_after: Optional[bool]
    shutdown_state: Optional[str]
    store_workers_quiescent: Optional[bool]
    worker_alive: Optional[bool]
    funding_worker_alive: Optional[bool]
    close_thread_alive: Optional[bool]
    queue_depth: Optional[int]
    inflight: Optional[int]
    publications_pending: Optional[int]
    broker_update_queue_depth: Optional[int]
    funding_queue_depth: Optional[int]
    funding_inflight: Optional[bool]
    funding_pending: Optional[int]
    read_only_metadata_probe_active: Optional[bool]
    md_client: ClientStopObservation
    trader_client: ClientStopObservation


class _Custody:
    """Keep exact references alive while close remains uncertain."""

    __slots__ = ("store", "wrapper", "md_client", "trader_client")

    def __init__(self, store: Any) -> None:
        self.store = store
        self.wrapper = None
        self.md_client = None
        self.trader_client = None

    def __repr__(self) -> str:
        return "<DiscoveryStoreCloseCustody: references retained; details redacted>"


class DiscoveryStoreCloseError(RuntimeError):
    """A close that did not prove normal Store and native-client shutdown."""

    def __init__(
        self, result: DiscoveryStoreCloseResult, custody: Optional[_Custody]
    ) -> None:
        super().__init__("discovery Store shutdown is incomplete; custody retained")
        self.result = result
        self.custody = custody


class _OwnerState:
    __slots__ = ("owner_ref", "custody", "result", "busy")

    def __init__(self, store: Any) -> None:
        self.owner_ref = None
        self.custody = _Custody(store)
        self.result = _empty_result("IN_PROGRESS", "close_in_progress")
        self.busy = True


class _CloseIncomplete(Exception):
    def __init__(self, result: DiscoveryStoreCloseResult) -> None:
        super().__init__("discovery Store shutdown is incomplete")
        self.result = result


def _empty_result(
    status: str,
    reason_code: str,
    *,
    already_attempted: bool = False,
    store_stop_attempted: bool = False,
    store_stop_returned: Optional[bool] = None,
    store_connected_before: Optional[bool] = False,
) -> DiscoveryStoreCloseResult:
    missing = ClientStopObservation(present=False, receipt_present=False)
    return DiscoveryStoreCloseResult(
        status=status,
        reason_code=reason_code,
        complete=False,
        already_attempted=already_attempted,
        store_stop_attempted=store_stop_attempted,
        store_stop_returned=store_stop_returned,
        store_connected_before=store_connected_before,
        store_connected_after=None,
        wrapper_connected_after=None,
        shutdown_state=None,
        store_workers_quiescent=None,
        worker_alive=None,
        funding_worker_alive=None,
        close_thread_alive=None,
        queue_depth=None,
        inflight=None,
        publications_pending=None,
        broker_update_queue_depth=None,
        funding_queue_depth=None,
        funding_inflight=None,
        funding_pending=None,
        read_only_metadata_probe_active=None,
        md_client=missing,
        trader_client=missing,
    )


def _valid_timeout(timeout: Any) -> float:
    if type(timeout) not in (int, float):
        raise ValueError("timeout must be a finite number between 0 and 30 seconds")
    value = float(timeout)
    if not math.isfinite(value) or value < 0.0 or value > 30.0:
        raise ValueError("timeout must be a finite number between 0 and 30 seconds")
    return value


def _existing_state(store: Any, key: int) -> Optional[_OwnerState]:
    state = _OWNER_STATES.get(key)
    if state is None:
        return None
    if state.custody is not None:
        same_owner = state.custody.store is store
    else:
        same_owner = state.owner_ref is not None and state.owner_ref() is store
    if same_owner:
        return state
    _OWNER_STATES.pop(key, None)
    return None


def _result_for_repeat() -> DiscoveryStoreCloseResult:
    return _empty_result(
        "ALREADY_ATTEMPTED",
        "close_already_attempted",
        already_attempted=True,
    )


def _finish_incomplete(
    key: int,
    state: _OwnerState,
    result: DiscoveryStoreCloseResult,
) -> None:
    with _OWNER_STATES_LOCK:
        state.result = result
        state.busy = False
        _OWNER_STATES[key] = state


def _fail(result: DiscoveryStoreCloseResult) -> None:
    raise _CloseIncomplete(result) from None


def _number(value: Any) -> Optional[int]:
    if type(value) is int and value >= 0:
        return value
    return None


def _safe_bool(value: Any) -> Optional[bool]:
    return value if type(value) is bool else None


def _receipt_observation(
    receipt: Any,
    *,
    present: bool,
    allowed_types: tuple[str, ...],
    minimum_generation: int,
) -> ClientStopObservation:
    if receipt is None:
        return ClientStopObservation(present=present, receipt_present=False)

    receipt_type = type(receipt)
    receipt_module = sys.modules.get(_RECEIPT_MODULE)
    if (
        not isinstance(receipt_module, ModuleType)
        or receipt_module.__name__ != _RECEIPT_MODULE
        or receipt_type.__module__ != _RECEIPT_MODULE
        or receipt_type.__name__ not in allowed_types
    ):
        raise ValueError("typed SDK stop receipt is unavailable")
    if vars(receipt_module).get(receipt_type.__name__) is not receipt_type:
        raise ValueError("typed SDK stop receipt is unavailable")

    generation = _number(getattr(receipt, "connection_generation", None))
    native_released_raw = getattr(receipt, "native_released", None)
    native_released = _safe_bool(native_released_raw)
    join_required = _safe_bool(getattr(receipt, "join_required", None))
    join_completed = _safe_bool(getattr(receipt, "join_completed", None))
    thread_alive_raw = getattr(receipt, "thread_alive", None)
    thread_alive = _safe_bool(thread_alive_raw)
    timed_out = _safe_bool(getattr(receipt, "timed_out", None))
    if (
        generation is None
        or generation < minimum_generation
        or join_required is None
        or join_completed is None
        or timed_out is None
    ):
        raise ValueError("typed SDK stop receipt fields are invalid")

    startup_outcome = None
    if receipt_type.__name__ == _STARTUP_STOP_RECEIPT:
        if generation != 0 or type(native_released_raw) not in (bool, type(None)):
            raise ValueError("typed SDK startup receipt generation is invalid")
        if type(thread_alive_raw) not in (bool, type(None)):
            raise ValueError("typed SDK startup receipt thread state is invalid")
        startup_outcome = getattr(receipt, "outcome", None)
        if type(startup_outcome) is not str or startup_outcome not in _STARTUP_OUTCOMES:
            raise ValueError("typed SDK startup outcome is invalid")
        attempt_id = getattr(receipt, "api_attempt_id", None)
        complete = getattr(receipt, "complete", None)
        if type(complete) is not bool:
            raise ValueError("typed SDK startup completion is invalid")
        if startup_outcome == "preflight_no_owner":
            expected = (
                attempt_id is None
                and native_released_raw is None
                and join_required is False
                and join_completed is True
                and thread_alive is False
                and timed_out is False
            )
        elif startup_outcome == "api_created_released":
            expected = (
                type(attempt_id) is str
                and re.fullmatch(r"[0-9a-f]{32}", attempt_id, re.ASCII) is not None
                and native_released is True
                and (join_required is False or join_completed is True)
                and thread_alive is False
                and timed_out is False
            )
        else:
            expected = False
        if complete is not expected:
            raise ValueError("typed SDK startup receipt contradicts its outcome")
    else:
        if native_released is None or (
            thread_alive_raw is not None and thread_alive is None
        ):
            raise ValueError("typed SDK stop receipt fields are invalid")
        complete = (
            native_released
            and (not join_required or join_completed)
            and thread_alive is False
            and timed_out is False
        )
        sdk_complete = getattr(receipt, "complete", None)
        if type(sdk_complete) is not bool or sdk_complete is not complete:
            raise ValueError("typed SDK stop completion is inconsistent")

    return ClientStopObservation(
        present=present,
        receipt_present=True,
        complete=complete,
        connection_generation=generation,
        native_released=native_released,
        join_required=join_required,
        join_completed=join_completed,
        thread_alive=thread_alive,
        timed_out=timed_out,
        startup_outcome=startup_outcome,
    )


def _store_health(store: Any) -> Dict[str, Any]:
    raw = store.get_command_health()
    if type(raw) is not dict:
        raise ValueError("Store health is unavailable")
    bool_names = (
        "worker_alive",
        "funding_worker_alive",
        "funding_inflight",
        "close_thread_alive",
        "read_only_metadata_probe_active",
        "restart_blocked_by_worker",
        "funding_restart_blocked_by_worker",
        "restart_blocked_by_close",
    )
    count_names = (
        "queue_depth",
        "inflight",
        "publications_pending",
        "broker_update_queue_depth",
        "funding_queue_depth",
        "funding_pending",
    )
    state = raw.get("shutdown_state")
    if type(state) is not str or state not in _SHUTDOWN_STATES:
        state = None
    values: Dict[str, Any] = {"shutdown_state": state}
    valid = state is not None
    for name in bool_names:
        item = raw.get(name)
        item = _safe_bool(item)
        values[name] = item
        valid = valid and item is not None
    for name in count_names:
        item = _number(raw.get(name))
        values[name] = item
        valid = valid and item is not None
    values["quiescent"] = bool(
        valid
        and all(values[name] is False for name in bool_names)
        and all(values[name] == 0 for name in count_names)
    )
    return values


def _health_result_fields(health: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "shutdown_state": health["shutdown_state"],
        "store_workers_quiescent": health["quiescent"],
        "worker_alive": health["worker_alive"],
        "funding_worker_alive": health["funding_worker_alive"],
        "close_thread_alive": health["close_thread_alive"],
        "queue_depth": health["queue_depth"],
        "inflight": health["inflight"],
        "publications_pending": health["publications_pending"],
        "broker_update_queue_depth": health["broker_update_queue_depth"],
        "funding_queue_depth": health["funding_queue_depth"],
        "funding_inflight": health["funding_inflight"],
        "funding_pending": health["funding_pending"],
        "read_only_metadata_probe_active": health[
            "read_only_metadata_probe_active"
        ],
    }


def _owner_collected(key: int, owner_ref: Any) -> None:
    with _OWNER_STATES_LOCK:
        state = _OWNER_STATES.get(key)
        if state is not None and state.owner_ref is owner_ref:
            _OWNER_STATES.pop(key, None)


def _discovery_topology_is_closed(store: Any) -> bool:
    return (
        store.provider == "ctp"
        and store.backend == "direct"
        and store._registered_sim_allow_writes is False
        and store._managed_execution_adapter is None
        and store._started is False
        and store._broker is None
        and type(store._data_feeds) is list
        and not store._data_feeds
        and type(store._subscribed_datanames) is set
        and not store._subscribed_datanames
        and type(store._tick_consumers) is dict
        and not store._tick_consumers
    )


def _perform_close(
    store: Any, timeout_seconds: float, state: _OwnerState
) -> DiscoveryStoreCloseResult:
    key = id(store)
    custody = state.custody
    try:
        from backtrader.stores.registered_sim import RegisteredSimWrapper

        wrapper = getattr(store, "_api", None)
        custody.wrapper = wrapper
        custody.md_client = getattr(wrapper, "md_client", None)
        custody.trader_client = getattr(wrapper, "trader_client", None)

        store_connected = _safe_bool(getattr(store, "_connected", None))
        wrapper_connected = _safe_bool(getattr(wrapper, "_connected", None))
        base = _empty_result(
            "INCOMPLETE",
            "store_not_discovery_only",
            store_connected_before=store_connected,
        )

        if not _discovery_topology_is_closed(store):
            _fail(base)
        if not isinstance(wrapper, RegisteredSimWrapper):
            _fail(replace(base, reason_code="registered_wrapper_unavailable"))
        if store_connected is None or wrapper_connected is None:
            _fail(replace(base, reason_code="connection_state_unavailable"))
        if store_connected is not wrapper_connected:
            _fail(replace(base, reason_code="connection_state_inconsistent"))

        store_stop_attempted = False
        store_stop_returned: Optional[bool] = None
        store_stop_raised = False
        if store_connected:
            store_stop_attempted = True
            try:
                store.stop(timeout=timeout_seconds)
                store_stop_returned = True
            except Exception:
                store_stop_returned = False
                store_stop_raised = True

        try:
            health = _store_health(store)
        except Exception:
            _fail(
                replace(
                    base,
                    reason_code="store_health_unavailable",
                    store_stop_attempted=store_stop_attempted,
                    store_stop_returned=store_stop_returned,
                    store_connected_after=_safe_bool(getattr(store, "_connected", None)),
                    wrapper_connected_after=_safe_bool(
                        getattr(wrapper, "_connected", None)
                    ),
                ),
            )

        health_fields = _health_result_fields(health)
        if not health["quiescent"]:
            _fail(
                replace(
                    base,
                    reason_code="store_workers_not_quiescent",
                    store_stop_attempted=store_stop_attempted,
                    store_stop_returned=store_stop_returned,
                    store_connected_after=_safe_bool(getattr(store, "_connected", None)),
                    wrapper_connected_after=_safe_bool(
                        getattr(wrapper, "_connected", None)
                    ),
                    **health_fields,
                ),
            )

        startup_path = not store_connected
        md_client = custody.md_client
        trader_client = custody.trader_client
        md_observation = ClientStopObservation(
            present=md_client is not None, receipt_present=False
        )
        trader_observation = ClientStopObservation(
            present=trader_client is not None, receipt_present=False
        )
        receipt_error = False

        if md_client is not None:
            try:
                receipt = md_client.stop_and_wait(timeout=timeout_seconds)
                md_observation = _receipt_observation(
                    receipt,
                    present=True,
                    allowed_types=(_NATIVE_STOP_RECEIPT,),
                    minimum_generation=1 if store_connected else 0,
                )
            except Exception:
                receipt_error = True

        if trader_client is not None:
            try:
                if startup_path:
                    receipt = trader_client.stop_startup_and_wait(
                        timeout=timeout_seconds
                    )
                    allowed = (_NATIVE_STOP_RECEIPT, _STARTUP_STOP_RECEIPT)
                else:
                    receipt = trader_client.stop_and_wait(timeout=timeout_seconds)
                    allowed = (_NATIVE_STOP_RECEIPT,)
                trader_observation = _receipt_observation(
                    receipt,
                    present=True,
                    allowed_types=allowed,
                    minimum_generation=1 if store_connected else 0,
                )
            except Exception:
                receipt_error = True

        connected_after = _safe_bool(getattr(store, "_connected", None))
        wrapper_connected_after = _safe_bool(getattr(wrapper, "_connected", None))
        clients_complete = (
            md_observation.present
            and trader_observation.present
            and md_observation.receipt_present
            and trader_observation.receipt_present
            and md_observation.complete is True
            and trader_observation.complete is True
        )
        md_startup_disposition_unproven = (
            startup_path
            and md_observation.receipt_present
            and md_observation.connection_generation == 0
        )
        store_state_complete = (
            health["shutdown_state"] == "PASS"
            if store_connected
            else health["shutdown_state"] == "NOT_STARTED"
        )
        store_complete = (
            connected_after is False
            and wrapper_connected_after is False
            and store_state_complete
            and health["quiescent"]
            and not md_startup_disposition_unproven
            and (not store_connected or store_stop_returned is True)
        )
        complete = store_complete and clients_complete and not receipt_error
        if complete:
            result = replace(
                base,
                status="CLOSED",
                reason_code="complete",
                complete=True,
                store_stop_attempted=store_stop_attempted,
                store_stop_returned=store_stop_returned,
                store_connected_after=connected_after,
                wrapper_connected_after=wrapper_connected_after,
                md_client=md_observation,
                trader_client=trader_observation,
                **health_fields,
            )
            return result

        if store_stop_raised:
            reason_code = "store_stop_raised"
        elif md_startup_disposition_unproven:
            reason_code = "md_startup_disposition_unproven"
        elif receipt_error:
            reason_code = "typed_stop_receipt_invalid"
        elif not md_observation.present or not trader_observation.present:
            reason_code = "client_reference_missing"
        elif not md_observation.receipt_present or not trader_observation.receipt_present:
            reason_code = "typed_stop_receipt_missing"
        elif not clients_complete:
            reason_code = "native_stop_incomplete"
        else:
            reason_code = "store_close_incomplete"
        result = replace(
            base,
            status="INCOMPLETE",
            reason_code=reason_code,
            store_stop_attempted=store_stop_attempted,
            store_stop_returned=store_stop_returned,
            store_connected_after=connected_after,
            wrapper_connected_after=wrapper_connected_after,
            md_client=md_observation,
            trader_client=trader_observation,
            **health_fields,
        )
        _fail(result)
    except _CloseIncomplete:
        raise
    except Exception:
        # No raw exception, traceback payload, or exception type is exposed.
        result = replace(
            state.result,
            status="INCOMPLETE",
            reason_code="lifecycle_observation_failed",
            complete=False,
            already_attempted=False,
        )
        _fail(result)


def close_discovery_store(
    store: Any, timeout: float = 5.0
) -> DiscoveryStoreCloseResult:
    """Close one exact discovery-only ``RegisteredSimStore`` exactly once.

    Connected Stores use their normal ``stop`` path before observing each
    retained CTP client's typed receipt. An unconnected Store uses the trader's
    startup receipt API and the market-data client's typed stop API directly;
    the Store's unconnected early return is not native shutdown evidence.

    If any lifecycle step is uncertain, this raises
    :class:`DiscoveryStoreCloseError`, retaining the exact Store/wrapper/client
    references. Every second call fails closed without repeating any stop
    operation, including after a prior successful close.
    """

    timeout_seconds = _valid_timeout(timeout)
    from backtrader.stores.registered_sim import RegisteredSimStore

    if type(store) is not RegisteredSimStore:
        raise TypeError("close_discovery_store requires an exact RegisteredSimStore")

    key = id(store)
    with _OWNER_STATES_LOCK:
        state = _existing_state(store, key)
        if state is not None:
            result = _result_for_repeat()
            custody = state.custody or _Custody(store)
            raise DiscoveryStoreCloseError(result, custody) from None
        state = _OwnerState(store)
        _OWNER_STATES[key] = state

    incomplete_result: Optional[DiscoveryStoreCloseResult] = None
    try:
        result = _perform_close(store, timeout_seconds, state)
    except _CloseIncomplete as incomplete:
        incomplete_result = incomplete.result
    except Exception:
        incomplete_result = replace(
            state.result,
            status="INCOMPLETE",
            reason_code="lifecycle_observation_failed",
            complete=False,
            already_attempted=False,
        )

    if incomplete_result is not None:
        _finish_incomplete(key, state, incomplete_result)
        raise DiscoveryStoreCloseError(
            incomplete_result, state.custody
        ) from None

    with _OWNER_STATES_LOCK:
        state.result = result
        state.busy = False
        state.custody = None
        state.owner_ref = weakref.ref(
            store,
            lambda owner_ref, owner_key=key: _owner_collected(
                owner_key, owner_ref
            ),
        )
    return result


__all__ = [
    "ClientStopObservation",
    "DiscoveryStoreCloseError",
    "DiscoveryStoreCloseResult",
    "close_discovery_store",
]
