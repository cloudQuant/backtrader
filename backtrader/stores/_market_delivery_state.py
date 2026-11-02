"""Backtrader-owned market event delivery counters and health projection."""

from __future__ import annotations

import collections
import time
import uuid
from collections.abc import Mapping
from typing import Any, Dict, Optional, Tuple

from ..events import MarketOrderBookEnvelope


class StoreMarketDeliveryState:
    """Single owner for Store-side stream loss, delivery, and continuity state.

    The SDK owns provider sessions and channel queues. This component owns only
    the Backtrader projection of those queues and the accounting of events that
    cross the Store/Feed/strategy boundary.
    """

    def __init__(self, *, delivery_id_limit: int, drop_record_limit: int) -> None:
        self._delivery_id_limit = max(int(delivery_id_limit), 1)
        self._drop_record_limit = max(int(drop_record_limit), 1)
        self._sdk_book_drops: Dict[str, int] = {}
        self._strategy_delivered_ids: Dict[str, collections.OrderedDict] = (
            collections.defaultdict(collections.OrderedDict)
        )
        self._feed_dropped_ids: Dict[str, collections.OrderedDict] = (
            collections.defaultdict(collections.OrderedDict)
        )
        self._market_drop_records: Dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=self._drop_record_limit)
        )
        self._sdk_sequences: Dict[Tuple[str, str], int] = {}
        self._stream_health: Dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter
        )
        self._stream_state: Dict[str, Dict[str, Any]] = collections.defaultdict(dict)

    def reset_generation(self) -> None:
        """Clear event identities while retaining bounded completed-bar loss evidence."""
        retained_bar_drops = {
            symbol: tuple(
                record
                for record in records
                if record.get("kind") == "bar"
                and record.get("reason") == "store_live_bar_queue_overflow"
            )
            for symbol, records in self._market_drop_records.items()
        }
        self._sdk_book_drops.clear()
        self._sdk_sequences.clear()
        self._strategy_delivered_ids.clear()
        self._feed_dropped_ids.clear()
        self._market_drop_records.clear()
        for symbol, records in retained_bar_drops.items():
            self._market_drop_records[symbol].extend(records)
        self._stream_health.clear()
        self._stream_state.clear()

    def clear_book_drop_counts(self) -> None:
        self._sdk_book_drops.clear()

    def clear_event_sequences(self) -> None:
        self._sdk_sequences.clear()

    def book_drop_counts(self) -> Dict[str, int]:
        return dict(self._sdk_book_drops)

    def increment(self, symbol: str, counter: str, amount: int = 1) -> None:
        self._stream_health[str(symbol)][counter] += amount

    def set_state(self, symbol: str, key: str, value: Any) -> None:
        self._stream_state[str(symbol)][key] = value

    def update_state(self, symbol: str, **values: Any) -> None:
        self._stream_state[str(symbol)].update(values)

    def pop_state(self, symbol: str, key: str) -> None:
        self._stream_state[str(symbol)].pop(key, None)

    def mark_unavailable(self, symbol: str, channel: str, code: str) -> None:
        if channel == "orderbook":
            state = self._stream_state[str(symbol)]
            state["orderbook_unavailable_code"] = str(code)
            state["orderbook_continuity_status"] = "unavailable"
            return
        self._stream_state[str(symbol)].update(
            stale=True,
            stale_reason="sdk_market_stream_unavailable",
            continuity_status="gap",
        )

    def observe_queue_depth(
        self,
        symbol: str,
        channel: str,
        depth: int,
        clear_unavailable: bool,
    ) -> None:
        self._stream_state[symbol][f"{channel}_queue_depth"] = depth
        if channel == "orderbook" and clear_unavailable:
            self._stream_state[symbol].pop("orderbook_unavailable_code", None)

    def project_binding_closed(self, symbol: str, channel: str) -> None:
        self._stream_state[symbol][f"{channel}_queue_depth"] = 0
        if channel == "tick":
            self._stream_state[symbol].pop("tick_queue_overflow_count", None)
        else:
            self._stream_state[symbol].pop("orderbook_queue_overflow_count", None)

    def record_queue_state(
        self,
        dataname: str,
        channel: str,
        result: Any,
        previous: int,
        *,
        stream_generation: int,
        error_type: type,
    ) -> bool:
        """Project one SDK queue observation into this Store's health state."""
        stream_health = self._stream_health
        stream_state = self._stream_state
        sdk_book_drops = self._sdk_book_drops
        market_drop_records = self._market_drop_records
        symbol = str(dataname)
        dropped = result.dropped_events
        if type(dropped) is not int or type(previous) is not int or dropped < 0:
            raise error_type("SDK market-stream drop count is invalid")

        state = stream_state[symbol]
        continuity_ok = True
        if dropped < previous:
            continuity_ok = False
            stream_health[symbol][f"{channel}_sdk_drop_counter_resets"] += 1
            if channel == "tick":
                state.update(
                    stale=True,
                    stale_reason="sdk_market_stream_drop_counter_reset",
                    continuity_status="gap",
                )
            else:
                state.update(
                    orderbook_stale=True,
                    orderbook_stale_reason="sdk_market_stream_drop_counter_reset",
                    orderbook_continuity_status="gap",
                )
        elif dropped > previous:
            continuity_ok = False
            delta = dropped - previous
            stream_health[symbol][f"{channel}_sdk_dropped"] += delta
            if channel == "tick":
                stream_health[symbol]["sdk_tick_dropped"] += delta
                stream_health[symbol]["tick_sdk_dropped"] += delta
                state.update(
                    stale=True,
                    stale_reason="sdk_market_stream_overflow",
                    continuity_status="gap",
                )
                reason = "sdk_reported_tick_events_dropped_before_delivery"
            else:
                sdk_book_drops[symbol] = sdk_book_drops.get(symbol, 0) + delta
                state.update(
                    orderbook_stale=True,
                    orderbook_stale_reason="sdk_market_stream_overflow",
                    orderbook_continuity_status="gap",
                )
                reason = "sdk_reported_orderbook_events_dropped_before_delivery"
            market_drop_records[symbol].append(
                {
                    "event_id": "",
                    "kind": channel,
                    "reason": "sdk_market_stream_overflow",
                    "safety_impact": reason,
                    "dropped_count": delta,
                    "stream_generation": stream_generation,
                }
            )

        state[f"{channel}_queue_depth"] = result.queue_depth
        state[f"{channel}_queue_overflow_count"] = dropped
        return continuity_ok

    def project_polled_event(
        self, symbol, channel, result, route, is_active, cleanup_unverified,
        previous_dropped, *, pump_only, record_queue_state, record_drop,
    ):
        """Project a polled SDK result into this Store's delivery accounting."""
        if result is None:
            return None
        continuity_ok = record_queue_state(symbol, channel, result, previous_dropped)
        if not is_active:
            reason = (
                "sdk_market_stream_cleanup_unverified"
                if cleanup_unverified
                else "sdk_market_stream_resync_required"
            )
            continuity = "disconnected" if cleanup_unverified else "gap"
            if channel == "tick":
                self.update_state(
                    symbol,
                    stale=True,
                    stale_reason=reason,
                    continuity_status=continuity,
                )
            else:
                self.update_state(
                    symbol,
                    orderbook_stale=True,
                    orderbook_stale_reason=reason,
                    orderbook_continuity_status=continuity,
                )
            for event in result.events:
                record_drop(
                    event,
                    "sdk_market_stream_recovery_required",
                    safety_impact="event_not_delivered_while_stream_recovery_is_required",
                    symbol=symbol,
                    kind=channel,
                    mark_stale=channel == "tick",
                )
            return None
        if not continuity_ok:
            for event in result.events:
                record_drop(
                    event,
                    "sdk_market_stream_drop_count_changed",
                    safety_impact="event_not_delivered_after_stream_loss_evidence",
                    symbol=symbol,
                    kind=channel,
                    mark_stale=channel == "tick",
                )
            return None
        if pump_only or not result.events:
            return None
        event = result.events[0]
        self.increment(symbol, "sdk_ingress")
        self.increment(symbol, f"{channel}_sdk_ingress")
        if channel == "tick":
            self.increment(symbol, "tick_ingress")
        cursor = event.cursor
        event_id = f"{cursor.stream_id}:{cursor.epoch}:{cursor.sequence}"
        self.set_last_enqueued_event_id(symbol, channel, event_id)
        if channel == "tick":
            return event
        return MarketOrderBookEnvelope(
            sdk_event=event,
            data_name=symbol,
            exchange_name=route,
        )

    @staticmethod
    def event_kind(event: Any) -> str:
        """Return the canonical market kind without interpreting venue payloads."""
        from bt_api_py.market_stream_contracts import market_event_kind

        if getattr(event, "event_type", None) == "orderbook":
            return "orderbook"
        if getattr(getattr(event, "key", None), "channel", None) == "orderbook":
            return "orderbook"
        return market_event_kind(event)

    def mark_feed_inflight(self, event: Any) -> None:
        symbol = str(getattr(event, "symbol", "") or "")
        if not symbol:
            instrument = getattr(getattr(event, "key", None), "instrument", None)
            symbol = str(getattr(instrument, "native_symbol", "") or "")
        if not symbol:
            return
        kind = self.event_kind(event)
        self._stream_health[symbol][f"{kind}_feed_inflight"] += 1

    def record_drop(
        self,
        event: Any,
        reason: str,
        *,
        stream_generation: int,
        safety_impact: str = "stream_marked_stale",
        mark_stale: bool = True,
        symbol: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> None:
        """Record one canonical market event as explicitly discarded."""
        getter = (
            event.get
            if isinstance(event, Mapping)
            else lambda key, default=None: getattr(event, key, default)
        )
        symbol = str(symbol or getter("symbol", "") or "")
        if not symbol:
            instrument = getattr(getattr(event, "key", None), "instrument", None)
            symbol = str(getattr(instrument, "native_symbol", "") or "")
        if not symbol:
            return
        kind = str(kind or self.event_kind(event)).lower()
        event_id = str(getter("event_id", "") or "")
        if not event_id:
            cursor = getattr(event, "cursor", None)
            if cursor is not None:
                event_id = ":".join(
                    str(value)
                    for value in (
                        getattr(cursor, "stream_id", ""),
                        getattr(cursor, "epoch", ""),
                        getattr(cursor, "sequence", ""),
                    )
                )
        counters = self._stream_health[symbol]
        counters["store_dropped"] += 1
        counters[f"{kind}_store_dropped"] += 1
        state = self._stream_state[symbol]
        state.update(
            last_drop_event_id=event_id,
            last_drop_kind=kind,
            last_drop_reason=str(reason),
        )
        if mark_stale:
            if kind == "orderbook":
                state.update(
                    orderbook_stale=True,
                    orderbook_stale_reason=str(reason),
                    orderbook_continuity_status="gap",
                )
            else:
                state.update(
                    stale=True,
                    stale_reason=str(reason),
                    continuity_status="gap",
                )
        self._market_drop_records[symbol].append(
            {
                "event_id": event_id,
                "kind": kind,
                "reason": str(reason),
                "safety_impact": str(safety_impact),
                "stream_generation": stream_generation,
            }
        )

    def set_last_enqueued_event_id(self, symbol: str, channel: str, event_id: str) -> None:
        self._stream_state[symbol][f"{channel}_last_enqueued_event_id"] = event_id
        if channel == "tick":
            self._stream_state[symbol]["last_enqueued_event_id"] = event_id

    def mark_feed_dropped(self, event: Any, reason: str, *, stream_generation: int) -> None:
        """Close a polled event's accounting when the Feed cannot dispatch it."""
        symbol = str(getattr(event, "symbol", "") or "")
        if not symbol:
            return
        event_id = str(getattr(event, "event_id", "") or "")
        dropped = self._feed_dropped_ids[symbol]
        if event_id and event_id in dropped:
            dropped.move_to_end(event_id)
            self._stream_health[symbol]["feed_drop_alias"] += 1
            return
        if event_id:
            dropped[event_id] = None
            if len(dropped) > self._delivery_id_limit:
                dropped.popitem(last=False)
        kind = self.event_kind(event)
        inflight_key = f"{kind}_feed_inflight"
        if self._stream_health[symbol][inflight_key] > 0:
            self._stream_health[symbol][inflight_key] -= 1
        self.record_drop(
            event,
            reason,
            stream_generation=stream_generation,
            safety_impact="event_not_visible_to_strategy",
        )

    def mark_strategy_delivered(self, event: Any) -> None:
        """Account for a standard event after its strategy callback returns."""
        symbol = str(getattr(event, "symbol", "") or "")
        if not symbol:
            return
        event_id = str(getattr(event, "event_id", "") or "")
        if event_id:
            delivered = self._strategy_delivered_ids[symbol]
            if event_id in delivered:
                delivered.move_to_end(event_id)
                self._stream_health[symbol]["strategy_delivery_alias"] += 1
                return
            delivered[event_id] = None
            if len(delivered) > self._delivery_id_limit:
                delivered.popitem(last=False)
        counters = self._stream_health[symbol]
        kind = self.event_kind(event)
        inflight_key = f"{kind}_feed_inflight"
        if counters[inflight_key] > 0:
            counters[inflight_key] -= 1
        counters["strategy_delivered"] += 1
        counters[f"{kind}_strategy_delivered"] += 1

    def stream_health(
        self,
        dataname: Optional[str],
        *,
        stream_generation: int,
        live_bar_queue: Any,
        live_bar_queue_size: int,
        market_stream_adapter: Any,
    ) -> Dict[str, Any]:
        """Compose the Backtrader health view from owned state and queue observations."""
        symbols = (
            [str(dataname)]
            if dataname is not None
            else sorted(
                set(self._stream_health)
                | set(self._stream_state)
                | set(live_bar_queue.symbols())
                | set(market_stream_adapter.symbols())
            )
        )
        result = {}
        for symbol in symbols:
            counters = dict(self._stream_health[symbol])
            state = dict(self._stream_state[symbol])
            book_ingress = counters.get("orderbook_sdk_ingress", 0)
            book_coalesced = counters.get("orderbook_sdk_coalesced", 0)
            book_dropped = (
                counters.get("orderbook_store_dropped", 0)
                + counters.get("orderbook_sdk_dropped", 0)
            )
            book_delivered = counters.get("orderbook_strategy_delivered", 0)
            book_inflight = counters.get("orderbook_feed_inflight", 0)
            book_queue_depth = market_stream_adapter.observed_queue_depth(
                symbol, "orderbook"
            )
            (
                live_bar_queue_depth,
                live_bar_overflow_count,
                persistent_bar_stale_reason,
            ) = live_bar_queue.snapshot(symbol)
            tick_queue_depth = market_stream_adapter.observed_queue_depth(symbol, "tick")
            tick_queue_overflow_count = int(state.get("tick_queue_overflow_count", 0) or 0)
            stale = bool(state.get("stale", False) or persistent_bar_stale_reason)
            result[symbol] = {
                **counters,
                **state,
                "stale_reason": state.get("stale_reason") or persistent_bar_stale_reason,
                "continuity_status": (
                    "gap" if persistent_bar_stale_reason else state.get("continuity_status")
                ),
                "book_queue_depth": book_queue_depth,
                # The SDK owns both channel queues; these are last observations.
                "tick_queue_depth": tick_queue_depth,
                "tick_queue_overflow_count": tick_queue_overflow_count,
                "live_bar_queue_depth": live_bar_queue_depth,
                "live_bar_queue_capacity": live_bar_queue_size,
                # This is separate from intentional duplicate filtering and
                # counts only completed bars evicted from the bounded queue.
                "live_bar_queue_overflow_count": live_bar_overflow_count,
                "store_dropped": counters.get("store_dropped", 0),
                "strategy_delivered": counters.get("strategy_delivered", 0),
                "sdk_ingress": counters.get("sdk_ingress", 0),
                "sdk_coalesced": counters.get("sdk_coalesced", 0),
                "book_ingress": book_ingress,
                "book_coalesced": book_coalesced,
                "book_dropped": book_dropped,
                "book_strategy_delivered": book_delivered,
                "book_feed_inflight": book_inflight,
                "book_conservation": (
                    book_ingress
                    == book_coalesced
                    + book_dropped
                    + book_delivered
                    + book_inflight
                    + book_queue_depth
                ),
                "market_drop_records": list(self._market_drop_records[symbol]),
                "stream_generation": stream_generation,
                "stale": stale,
            }
        if dataname is not None:
            return result.get(
                str(dataname),
                {
                    "stream_generation": stream_generation,
                    "tick_queue_overflow_count": int(
                        self._stream_state[str(dataname)].get(
                            "tick_queue_overflow_count", 0
                        )
                        or 0
                    ),
                    "live_bar_queue_depth": 0,
                    "live_bar_queue_capacity": live_bar_queue_size,
                    "live_bar_queue_overflow_count": live_bar_queue.snapshot(str(dataname))[1],
                    "stale_reason": live_bar_queue.stale_reason(str(dataname)),
                    "continuity_status": (
                        "gap" if live_bar_queue.stale_reason(str(dataname)) else ""
                    ),
                    "stale": bool(live_bar_queue.stale_reason(str(dataname))),
                },
            )
        return result

    def is_stream_ready(self, dataname: str, *, live_bar_queue: Any) -> bool:
        key = str(dataname)
        return not bool(
            self._stream_state[key].get("stale", False)
            or live_bar_queue.stale_reason(key)
        )

    def record_sdk_market_event(
        self,
        venue: str,
        raw_event: Mapping[str, Any],
        *,
        stream_generation: int,
    ):
        """Apply the Backtrader continuity projection to one neutral SDK event."""
        from bt_api_py.market_delivery_projection import (
            normalize_sdk_market_event,
            project_sdk_market_event,
        )

        event, symbol, kind = normalize_sdk_market_event(raw_event)
        if not symbol:
            return None
        counters = self._stream_health[symbol]
        state = self._stream_state[symbol]
        if kind == "orderbook":
            self.record_drop(
                event,
                "untyped_orderbook_event",
                stream_generation=stream_generation,
                safety_impact="event_has_no_verified_sdk_market_stream_binding",
                mark_stale=False,
                symbol=symbol,
                kind="orderbook",
            )
            return None
        try:
            coalesced_count = max(int(event.get("coalesced_count", 1) or 1), 1)
        except (TypeError, ValueError):
            coalesced_count = 1
        counters["sdk_ingress"] += coalesced_count
        counters["sdk_coalesced"] += coalesced_count - 1
        counters[f"{kind}_sdk_ingress"] += coalesced_count
        counters[f"{kind}_sdk_coalesced"] += coalesced_count - 1
        projection = project_sdk_market_event(
            event,
            venue,
            symbol,
            state,
            self._sdk_sequences.get((venue, symbol)),
            coalesced_count,
            event_id_factory=lambda: uuid.uuid4().hex,
            wall_time_factory=time.time,
        )
        for name, delta in projection.counter_deltas:
            counters[name] += delta
        if projection.state_updates:
            state.update(dict(projection.state_updates))
        if projection.drop_reason is not None:
            self.record_drop(
                projection.event,
                projection.drop_reason,
                stream_generation=stream_generation,
                safety_impact=projection.drop_safety_impact,
                mark_stale=projection.drop_mark_stale,
            )
            return None
        return projection.event

    def accept_sdk_market_event(self, event: Mapping[str, Any], native_event: Any) -> None:
        """Commit sequence/recovery only after native projection validation succeeds."""
        sequence = event.get("_sequence_value")
        sequence_key = event.get("_sequence_key")
        if sequence and isinstance(sequence_key, tuple):
            self._sdk_sequences[sequence_key] = int(sequence)
        if not event.get("_recovery_candidate"):
            return
        symbol = str(event.get("symbol") or "")
        continuity = str(event.get("continuity_status") or "unknown")
        self._stream_state[symbol].update(
            stale=False,
            stale_reason="",
            continuity_status=continuity,
            last_event_id=str(event.get("event_id") or ""),
        )
        if isinstance(native_event, dict):
            native_event.update(stale=False, stale_reason="")
        else:
            native_event.stale = False
            native_event.stale_reason = ""

    def mark_disconnected(self, symbol: str) -> None:
        self._stream_health[symbol]["disconnect"] += 1
        self._stream_state[symbol].update(
            stale=True,
            stale_reason="stream_disconnected",
            continuity_status="disconnected",
        )


__all__ = ("StoreMarketDeliveryState",)
