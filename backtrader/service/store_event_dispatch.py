"""Dispatch SDK events into one Backtrader Store under its existing lock.

The caller owns polling serialization, lifecycle, event state and queues.
"""

from __future__ import annotations


def drain_store_sdk_events_locked(store, *, error_type, missing_dependency_error_type):
    """Convert standard SDK events to native objects on the Cerebro thread."""
    try:
        from bt_api_py.market_stream_contracts import (
            decode_market_event_continuity,
            polled_market_event_header,
        )
    except ImportError as exc:
        raise missing_dependency_error_type(
            "bt_api_py market event continuity contract is required"
        ) from exc
    if not callable(decode_market_event_continuity):
        raise missing_dependency_error_type(
            "bt_api_py market event continuity contract is required"
        )
    for venue in store._sdk_exchanges:
        events = store._api.poll_events(
            venue,
            max_raw_items=(
                store._sdk_event_batch_size if store.uses_async_commands else None
            ),
            coalesce_market_snapshots=(
                store._sdk_coalesce_market_snapshots
                if store.uses_async_commands
                else ("orderbook",)
            ),
        )
        for event in events:
            kind, symbol = polled_market_event_header(event, error_type=error_type)
            if kind in {"order", "trade"}:
                update = store._sdk_broker_event(venue, event)
                if update is not None:
                    store._append_sdk_update(update)
            elif kind == "account":
                store._apply_sdk_account_push(venue, event)
            elif kind == "position":
                # Position pushes are audit-only: startup-policy brokers
                # own local leg accounting from confirmed fills.
                store.emit_runtime_event("venue_position_update", venue=venue)
            elif kind in {"disconnect", "disconnected"}:
                store._mark_stream_disconnected(venue, event)
            elif kind == "tick":
                if type(symbol) is str and symbol:
                    store._market_delivery_state.increment(
                        symbol, "untyped_sdk_tick_event"
                    )
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
                raise error_type(
                    "SDK poll_events yielded an event kind or route not handled by Store"
                )


__all__ = ("drain_store_sdk_events_locked",)
