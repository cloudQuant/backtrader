"""Dispatch SDK events into one Backtrader Store under its existing lock.

The caller owns polling serialization, lifecycle, event state and queues.
"""

from __future__ import annotations


def poll_store_sdk_events(store, venue):
    """Poll one venue without holding Store lifecycle or projection locks."""
    return store._api.poll_events(
        venue,
        max_raw_items=(store._sdk_event_batch_size if store.uses_async_commands else None),
        coalesce_market_snapshots=(
            store._sdk_coalesce_market_snapshots if store.uses_async_commands else ("orderbook",)
        ),
    )


def require_store_event_dispatch_contracts(*, missing_dependency_error_type):
    """Resolve dispatch contracts before polling can consume an SDK batch."""
    try:
        from bt_api_py.market_stream_contracts import (
            decode_market_event_continuity,
            polled_market_event_header,
        )
    except ImportError as exc:
        raise missing_dependency_error_type(
            "bt_api_py market event continuity contract is required"
        ) from exc
    if not callable(decode_market_event_continuity) or not callable(polled_market_event_header):
        raise missing_dependency_error_type(
            "bt_api_py market event continuity contract is required"
        )
    return polled_market_event_header


def dispatch_store_sdk_events_locked(
    store,
    venue,
    events,
    *,
    error_type,
    missing_dependency_error_type,
    event_header=None,
):
    """Project a polled venue batch while the Store event lock is held."""
    if event_header is None:
        event_header = require_store_event_dispatch_contracts(
            missing_dependency_error_type=missing_dependency_error_type
        )

    for event in events:
        kind, symbol = event_header(event, error_type=error_type)
        if kind in {"order", "trade"}:
            update = store._sdk_broker_event(venue, event)
            if update is not None:
                store._append_sdk_update(update)
        elif kind == "account":
            store._apply_sdk_account_push(venue, event)
        elif kind == "position":
            # Position pushes never change local leg accounting (that follows
            # confirmed fills); subscribed accounts keep them as evidence.
            subscription = getattr(store, "_account_position_subscription", None)
            if subscription is not None:
                subscription.on_position_event(event)
            store.emit_runtime_event("venue_position_update", venue=venue)
        elif kind in {"disconnect", "disconnected"}:
            subscription = getattr(store, "_account_position_subscription", None)
            if subscription is not None:
                subscription.on_disconnect(event)
            store._mark_stream_disconnected(venue, event)
        elif kind == "tick":
            if type(symbol) is str and symbol:
                store._market_delivery_state.increment(symbol, "untyped_sdk_tick_event")
            else:
                store._command_health["sdk_unhandled_events"] += 1
            store._record_market_drop(
                event,
                "untyped_sdk_tick_event",
                safety_impact="ignored_without_the_sdk_market_stream",
            )
        elif kind == "orderbook":
            if type(symbol) is str and symbol:
                store._record_market_drop(
                    event,
                    "untyped_orderbook_event",
                    safety_impact="event_has_no_verified_sdk_market_stream_binding",
                    mark_stale=False,
                    symbol=symbol,
                    kind="orderbook",
                )
            else:
                store._command_health["sdk_unhandled_events"] += 1
        elif symbol in store._subscribed_datanames and store._sdk_exchange(symbol) == venue:
            event = store._record_sdk_market_event(venue, event)
            if event is None:
                continue
            if kind == "bar":
                if event.get("bar_final") is False:
                    # A provider bar still marked as forming is never
                    # published; only its final version may become a BT bar.
                    store._market_delivery_state.increment(str(symbol), "unfinished_provider_bar")
                    continue
                store._accept_sdk_market_event(event, event)
                store._enqueue_live_bar(str(symbol), store._copy_or_normalize_bar(event))
            else:
                store._record_market_drop(
                    event,
                    "unsupported_market_event_kind",
                    safety_impact="event_not_consumed_by_store",
                )
        else:
            store._command_health["sdk_unhandled_events"] += 1
            store._record_market_drop(
                event,
                "unhandled_sdk_event_route_or_kind",
                safety_impact="event_not_consumed_by_store",
            )
            raise error_type("SDK poll_events yielded an event kind or route not handled by Store")


def drain_store_sdk_events_locked(store, *, error_type, missing_dependency_error_type):
    """Poll and dispatch events for direct callers retaining the old bridge."""
    event_header = require_store_event_dispatch_contracts(
        missing_dependency_error_type=missing_dependency_error_type
    )
    for venue in store._sdk_exchanges:
        events = poll_store_sdk_events(store, venue)
        dispatch_store_sdk_events_locked(
            store,
            venue,
            events,
            error_type=error_type,
            missing_dependency_error_type=missing_dependency_error_type,
            event_header=event_header,
        )


__all__ = (
    "dispatch_store_sdk_events_locked",
    "drain_store_sdk_events_locked",
    "poll_store_sdk_events",
    "require_store_event_dispatch_contracts",
)
