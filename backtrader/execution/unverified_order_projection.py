"""Backtrader binding and projections for unverified SDK execution events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict


def project_unverified_order_update(
    *,
    local_ref: int,
    client_order_id: str,
    symbol: str,
    venue: str,
) -> Dict[str, Any]:
    """Build the conservative UNKNOWN Broker update for one bound order."""
    return {
        "kind": "order",
        "local_ref": local_ref,
        "bt_order_ref": local_ref,
        "client_order_id": client_order_id,
        "symbol": symbol,
        "data_name": symbol,
        "exchange_name": venue,
        "status": "unknown",
        "execution_unknown": True,
        "terminal_confirmed": False,
        "error_code": "sdk_execution_event_unverified",
    }


def project_unverified_execution_event_drop(venue: Any, event: Any) -> Dict[str, Any]:
    """Delegate the neutral identifier projection to the unified SDK."""
    from bt_api_py.execution_event_projection import (
        project_unverified_execution_event_drop as project,
    )

    return project(venue, event)


def project_store_unverified_order_event(store, venue, event):
    """Turn unverified order/trade events into an UNKNOWN update only.

    ``poll_events`` promises normalized mappings, but the current facade
    does not attach a typed, request-bound order/fill proof to these event
    rows.  Store therefore never forwards their status or fill quantities
    as execution evidence.  A local order can only be marked UNKNOWN when
    the SDK-issued neutral correlation is already bound in this Store.
    """
    if not isinstance(event, Mapping):
        store._record_unverified_sdk_execution_event(venue, None)
        return None
    event_kind = event.get("kind")
    if event_kind not in {"order", "trade"}:
        store._record_unverified_sdk_execution_event(venue, event)
        return None
    client_id = event.get("client_order_id")
    if type(client_id) is not str or not client_id or client_id != client_id.strip():
        client_id = None
    binding = (
        store._sdk_execution_bindings.by_client_id(venue, client_id)
        if client_id
        else None
    )
    if not isinstance(binding, Mapping):
        store._record_unverified_sdk_execution_event(venue, event)
        return None

    correlation = binding.get("correlation")
    local_ref = binding.get("bt_order_ref")
    symbol = binding.get("symbol")
    event_symbol = event.get("symbol")
    if (
        type(symbol) is not str
        or not symbol
        or type(local_ref) is not int
        or type(client_id) is not str
        or binding.get("client_order_id") != client_id
        or binding.get("exchange_name") != venue
        or binding.get("api") is not store._api
        or (type(event_symbol) is str and event_symbol != symbol)
    ):
        store._record_unverified_sdk_execution_event(venue, event)
        return None
    try:
        command_types = store._sdk_correlated_order_adapter.warm_command_types()
    except Exception:
        store._record_unverified_sdk_execution_event(venue, event)
        return None
    if type(correlation) is not command_types["OrderCorrelation"]:
        store._record_unverified_sdk_execution_event(venue, event)
        return None
    bound = store._sdk_execution_bindings.binding_matches(
        binding,
        correlation=correlation,
        api=store._api,
        exchange_name=venue,
        symbol=symbol,
        require_all_indexes=True,
    )
    if not bound:
        store._record_unverified_sdk_execution_event(venue, event)
        return None

    store._latch_risk_state_unknown("sdk_execution_event_unverified")
    return project_unverified_order_update(
        local_ref=local_ref,
        client_order_id=correlation.client_order_id,
        symbol=symbol,
        venue=venue,
    )


def record_store_unverified_execution_event(store, venue, event) -> None:
    """Record an unsupported or unbound execution event without its payload."""
    safe = project_unverified_execution_event_drop(venue, event)
    store._command_runtime.record_drop(safe, "sdk_execution_event_unverified")


__all__ = (
    "project_unverified_execution_event_drop",
    "project_unverified_order_update",
    "project_store_unverified_order_event",
    "record_store_unverified_execution_event",
)
