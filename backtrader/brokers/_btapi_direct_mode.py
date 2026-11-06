"""Direct write mode of :class:`~backtrader.brokers.btapibroker.BtApiBroker` (iteration 62).

When the Store runs the SDK direct path (write admission enabled for the route
and no optional execution component configured), ``BtApiBroker`` routes its
lifecycle through this mixin instead of the managed-execution path:

* writes go through ``BtApi.make_order/cancel_order`` with a pre-dispatch commit
  port (SDK admission -> provider native identity -> durable host marker ->
  one-shot grant -> native send);
* durable local state (strategy UUID, local order sequence, pending markers,
  waiting orders, the versioned position snapshot) lives in
  :mod:`backtrader.live_state` under one strategy directory;
* startup reconciles that snapshot with a complete read-only account
  observation before any write is allowed (D62-05/13/16/17/22);
* identity-matched venue returns are projected onto the Broker's own orders,
  position legs and notifications; nothing is inferred from silence.

One strategy instance per strategy directory.  Stopping cancels only this
strategy's working orders and never flattens (D62-19).  The mixin reuses the
Broker's ``orders``, ``positions``/``long_positions``/``short_positions``,
``notify`` and ``_reject_order``; it holds no second order book.
"""

from __future__ import annotations

import collections
import datetime as _dt
import hashlib
import math
import threading
import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ..order import BuyOrder, Order, SellOrder
from ..position import Position
from ..utils.log_message import get_logger

_log = get_logger(__name__)

__all__ = ("BtApiDirectModeMixin", "DirectModeError")

OFFSETS = ("open", "close", "close_today", "close_yesterday")
_CLOSE_OFFSETS = frozenset(("close", "close_today", "close_yesterday"))
# Venues whose "close" never closes today's position (explicit today/yesterday).
_SPLIT_VENUES = frozenset(("SHFE", "INE"))
_DIRECT_PARAMS = (
    ("strategy_dir", None),
    ("first_init", False),
    ("require_offset", None),
    ("direct_funds_refresh_interval", 60.0),
    ("direct_position_audit_interval", 300.0),
    ("waiting_orders", True),
    ("stop_cancel_timeout", 10.0),
    ("direct_facts_timeout", 10.0),
    # The complete startup observation may be transiently incomplete right
    # after login (e.g. CTP query flow control); retry it, then fail closed.
    ("direct_startup_facts_attempts", 3),
    ("direct_startup_facts_retry_delay", 2.0),
    ("direct_max_events", 256),
    ("check_host_path", True),
)


class DirectModeError(RuntimeError):
    """A direct-mode precondition failed; ``code`` is a stable reason."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _utc_text(value: Optional[_dt.datetime] = None) -> str:
    return (value or _utc_now()).astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_utc(text: Optional[str]) -> Optional[_dt.datetime]:
    if not text:
        return None
    try:
        value = _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=_dt.timezone.utc)


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _positive_finite(value: Any, *, absolute: bool = False) -> bool:
    """``value`` is a finite number above zero (its magnitude when ``absolute``)."""
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if absolute:
        number = abs(number)
    return math.isfinite(number) and number > 0


def identity_keys(fields: Dict[str, Any], client_order_id: Optional[str]) -> List[tuple]:
    """Lookup keys of one native identity.

    CTP ``OrderRef`` is unique only inside one FrontID/SessionID, so the
    session triple is the order key; the venue order id (``ExchangeID`` +
    ``OrderSysID``) is learned from returns and keys trades.  Venues without a
    session identity fall back to their client order id.
    """
    keys = []
    front, session, ref = fields.get("front_id"), fields.get("session_id"), fields.get("order_ref")
    if front is not None and session is not None and ref:
        keys.append(("s", int(front), int(session), str(ref)))
    venue, sys_id = fields.get("exchange_id"), fields.get("order_sys_id")
    if venue and sys_id:
        keys.append(("x", str(venue), str(sys_id).strip()))
    if not keys and client_order_id:
        keys.append(("c", str(client_order_id)))
    return keys


def _snapshot_qty(value: Any) -> Any:
    """Whole lots stay integers; fractional venue quantities are kept exactly.

    CTP lots are integers; OKX contracts and Binance base quantities can be
    fractional (e.g. 0.002 BTC) and must never be rounded away.
    """
    number = round(float(value), 12)
    if abs(number) < 1e-12:
        return 0
    return int(number) if number.is_integer() else number


def _leg_fact(fact: Any) -> Any:
    """Map a one-way (``net``) venue position onto the long or short leg."""
    if fact.side in ("long", "short"):
        return fact
    total = _num(fact.total)
    if not total:
        return None
    import dataclasses

    return dataclasses.replace(
        fact, side="long" if total > 0 else "short", total=abs(total), today=None, yesterday=None
    )


def capture_valid_intent(valid: Any) -> Dict[str, Any]:
    """Original ``valid`` intent, captured before ``Order`` converts it (D62-31)."""
    if valid is None:
        return {"kind": "unspecified", "value": None}
    if valid == Order.DAY or (isinstance(valid, _dt.timedelta) and valid == _dt.timedelta()):
        return {"kind": "day", "value": None}
    if isinstance(valid, _dt.timedelta):
        return {"kind": "timedelta", "value": valid.total_seconds()}
    return {"kind": "absolute", "value": str(valid)}


class BtApiDirectModeMixin:
    """Direct write lifecycle of ``BtApiBroker`` (see module docstring)."""

    # ------------------------------------------------------------------
    # selection and state
    # ------------------------------------------------------------------
    def _direct_init_state(self) -> None:
        self._direct_on = False
        self._direct_attempted = False  # direct mode was selected by start()
        self._direct_stopping = False
        self._direct_api: Any = None
        self._direct_exchange: Optional[str] = None
        self._direct_state: Any = None
        self._direct_run_lock: Any = None
        self._direct_uuid: Optional[str] = None
        self._direct_account_hash: Optional[str] = None
        self._direct_trading_day: Optional[str] = None
        self._direct_writes_enabled = False
        self._direct_require_offset = False
        self._direct_meta: Dict[int, Dict[str, Any]] = {}
        self._direct_index: Dict[tuple, int] = {}
        self._direct_split: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
        self._direct_symbol_venue: Dict[str, str] = {}
        self._direct_data_symbol: Dict[int, str] = {}
        self._direct_applied: Dict[str, List[str]] = {}
        self._direct_blocked: Dict[str, str] = {}
        self._direct_global_block: Optional[str] = None
        self._direct_foreign_orders: List[Any] = []
        self._direct_restored: List[Order] = []
        self._direct_deferred_waiting: List[Dict[str, Any]] = []
        self._direct_deferred_restore: List[Any] = []
        self._direct_awaiting_bar: List[Any] = []
        self._direct_strategy: Any = None
        self._direct_report: Dict[str, Any] = {}
        self._direct_schedule: Any = None
        self._direct_facts_thread: Optional[threading.Thread] = None
        self._direct_facts_stop = threading.Event()
        self._direct_facts_results: collections.deque = collections.deque(maxlen=8)
        self._direct_last_funds = 0.0
        self._direct_last_audit = 0.0
        self._direct_refresh_counts = {"funds": 0, "audit": 0, "failed": 0}
        self._direct_lock = threading.RLock()

    def _direct_selected(self) -> bool:
        """Direct mode: the Store chose the SDK direct write path (I62-08)."""
        if self._is_market_data_only():
            return False
        if self._managed_runtime_session is not None or self._service_execution_session is not None:
            return False
        return bool(getattr(self.store, "direct_write_mode", False))

    def _direct_active(self) -> bool:
        return bool(getattr(self, "_direct_on", False))

    def _direct_owns_stop(self) -> bool:
        """``stop()`` takes the direct path once direct mode was selected.

        Also after a failed or already finished direct start: the managed
        shutdown path must never run for a direct-mode Broker.
        """
        return self._direct_active() or bool(getattr(self, "_direct_attempted", False))

    # ------------------------------------------------------------------
    # startup (R-10 start stage)
    # ------------------------------------------------------------------
    def _direct_start(self) -> None:
        from .. import live_state as ls

        if self._direct_on:
            return
        self._direct_attempted = True
        self._direct_stopping = False  # a retry after stop() of a failed start
        if not self.p.strategy_dir:
            raise DirectModeError("strategy_dir_required")
        store = self.store
        store.start(broker=self)
        self._live_started = True
        api = getattr(store, "sdk_api", None)
        if api is None or not callable(getattr(api, "direct_account_facts", None)):
            raise DirectModeError("direct_sdk_facade_unavailable")
        self._direct_api = api
        self._direct_exchange = self._direct_resolve_exchange()
        require = self.p.require_offset
        self._direct_require_offset = (
            self._direct_exchange.upper().startswith("CTP") if require is None else bool(require)
        )
        admission = getattr(api, "write_admission", None)
        self._direct_writes_enabled = bool(
            admission is not None and admission.is_enabled(self._direct_exchange)
        )
        facts = self._direct_read_startup_facts()
        self._direct_trading_day = facts.trading_day
        account_hash = self._direct_account_reference()
        binding = {"exchange": self._direct_exchange, "account_hash": account_hash}
        check_host = bool(self.p.check_host_path)
        try:
            state = ls.StrategyStateDir(self.p.strategy_dir, check_host_path=check_host)
            first = False
        except ls.LiveStateNotInitialized:
            if not self.p.first_init:
                raise DirectModeError(
                    "first_init_required",
                    "no live state in strategy_dir; start once with first_init=True",
                ) from None
            self._direct_require_flat_account(facts)
            state = ls.StrategyStateDir.initialize(
                self.p.strategy_dir, account_binding=binding, check_host_path=check_host
            )
            first = True
        self._direct_state = state
        # A directory whose identity was created by a backtest (D62-04b2) has
        # no account binding yet; a live-initialized one always has one.
        live_bound = state.identity.account_binding is not None
        self._direct_uuid = state.strategy_uuid
        self._direct_account_hash = account_hash
        self._direct_run_lock = state.acquire_run_lock()
        try:
            if not first and not live_bound and state.snapshot.read() is None:
                # The directory identity exists (e.g. created by a backtest of
                # this strategy directory sharing its local sequence, D62-04b2)
                # but no live snapshot was ever written: this is the first live
                # start and needs the same explicit, flat-account first init.
                # Checked before binding the account so a refusal persists nothing.
                if not self.p.first_init:
                    raise DirectModeError(
                        "first_init_required",
                        "no live snapshot in strategy_dir; start once with first_init=True",
                    )
                self._direct_require_flat_account(facts)
                first = True
            try:
                ls.bind_account(state.strategy_dir, binding)
            except ls.LiveStateIdentityMismatch as exc:
                raise DirectModeError(
                    "account_binding_mismatch", getattr(exc, "code", "")
                ) from None
            state.sequence.restore_ref_basis()
            if first:
                self._direct_write_snapshot()
            self._direct_reconcile(facts)
            self._direct_settle()
            self._direct_apply_balance(facts.balance)
            try:
                self._direct_schedule = api.trading_session_schedule(self._direct_exchange)
            except Exception:
                self._direct_schedule = None
            self._direct_restore_waiting()
        except BaseException:
            # Startup refused after the run lock was taken (unusable snapshot,
            # binding mismatch ...): never leak the lock (D62-13).
            self._direct_release_lock()
            raise
        now = time.monotonic()
        self._direct_last_funds = now
        self._direct_last_audit = now
        self._direct_on = True
        self._startup_ready = True
        self._trading_enabled = True
        self._direct_start_facts_poller()
        _log.info(
            "direct mode started: exchange=%s writes=%s blocked=%d restored=%d",
            self._direct_exchange,
            self._direct_writes_enabled,
            len(self._direct_blocked),
            len(self._direct_restored),
        )

    @staticmethod
    def _direct_require_flat_account(facts: Any) -> None:
        """D62-13: an explicit first initialization needs a flat account without orders."""
        occupied = sorted({f"{p.symbol}:{p.side}" for p in (facts.positions or ()) if p.total > 0})
        if occupied or facts.active_orders:
            raise DirectModeError(
                "first_init_requires_flat_account",
                f"positions={len(occupied)} working_orders={len(facts.active_orders or ())}",
            )

    def _direct_resolve_exchange(self) -> str:
        routes = list(getattr(self.store, "_sdk_exchanges", {}) or {})
        if len(routes) != 1:
            raise DirectModeError("direct_mode_requires_one_route", ",".join(routes))
        return routes[0]

    def _direct_account_reference(self) -> str:
        """Secret-free stable account reference (hash of the provider reference)."""
        provider = self._direct_api.direct_writes().provider(self._direct_exchange)
        reader = getattr(provider, "account_reference", None)
        reference = reader() if callable(reader) else None
        if not reference:
            raise DirectModeError("account_reference_unavailable")
        text = f"{self._direct_exchange}|{reference}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _direct_read_startup_facts(self):
        """Complete startup observation with bounded retries; fails closed."""
        attempts = max(int(self.p.direct_startup_facts_attempts or 1), 1)
        delay = max(float(self.p.direct_startup_facts_retry_delay or 0.0), 0.0)
        for attempt in range(1, attempts + 1):
            facts = self._direct_read_facts(trades=True, all_orders=True)
            if facts.complete:
                return facts
            blockers = ",".join(facts.blockers or ())
            if attempt == attempts:
                raise DirectModeError("startup_account_facts_incomplete", blockers)
            _log.warning(
                "direct startup facts incomplete (attempt %d/%d): %s", attempt, attempts, blockers
            )
            if delay:
                time.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _direct_read_facts(self, *, trades=False, all_orders=False, **sections):
        kwargs = dict(positions=True, active_orders=True, trades=trades, balance=True)
        kwargs.update(sections)
        if all_orders:
            kwargs["all_orders"] = True
        kwargs["timeout"] = float(self.p.direct_facts_timeout)
        symbols = sorted(str(name) for name in (getattr(self.store, "_sdk_routes", None) or {}))
        if symbols:
            # Venues whose order/trade reads are per symbol (Binance) need the
            # strategy's instruments to prove completeness; others ignore it.
            kwargs["symbols"] = symbols
        return self._direct_api.direct_account_facts(self._direct_exchange, **kwargs)

    # ------------------------------------------------------------------
    # reconciliation (D62-05/13/16/17/22; R-3)
    # ------------------------------------------------------------------
    def _direct_reconcile(self, facts: Any) -> None:
        state = self._direct_state
        snapshot = state.snapshot.read_for_live(
            self._direct_account_hash, self._direct_exchange, strategy_uuid=self._direct_uuid
        )
        snapshot = snapshot or {}
        local_positions = dict(snapshot.get("positions") or {})
        self._direct_applied = {
            day: list(keys) for day, keys in (snapshot.get("applied_trades") or {}).items()
        }
        prices = dict(snapshot.get("position_prices") or {})
        snapshot_day = snapshot.get("trading_day")
        self._direct_seed_configured_venues()
        venue: Dict[str, Dict[str, Any]] = {}
        for fact in facts.positions or ():
            fact = _leg_fact(fact)
            if fact is None:
                continue
            venue.setdefault(fact.symbol, {})[fact.side] = fact
            if fact.venue:
                self._direct_symbol_venue[fact.symbol] = fact.venue
        report: Dict[str, Any] = {
            "trading_day": facts.trading_day,
            "snapshot_trading_day": snapshot_day,
            "mismatches": [],
            "other_instruments": [],
            "unknown_markers": [],
            "restored_orders": 0,
            "applied_missing_trades": 0,
            "foreign_working_orders": 0,
        }
        self._direct_load_local(local_positions, prices, snapshot_day, facts.trading_day)
        orders_by_key: Dict[tuple, Any] = {}
        for event in tuple(getattr(facts, "orders", None) or ()) + tuple(facts.active_orders or ()):
            if event.identity is None:
                continue
            for key in identity_keys(dict(event.identity.fields), event.identity.client_order_id):
                orders_by_key[key] = event
        working: Dict[tuple, Any] = {}
        for event in facts.active_orders or ():
            if event.identity is None:
                continue
            for key in identity_keys(dict(event.identity.fields), event.identity.client_order_id):
                working[key] = event
        trades_by_order: Dict[tuple, List[Any]] = collections.defaultdict(list)
        for trade in facts.trades or ():
            fields = dict(trade.identity.fields) if trade.identity else {}
            venue_order_id = (
                trade.exchange_order_id
                or fields.get("order_sys_id")
                or fields.get("ord_id")
                or fields.get("order_id")
            )
            if venue_order_id:
                key = ("o", str(trade.symbol), str(venue_order_id).strip())
                trades_by_order[key].append(trade)
        claimed = set()
        for marker in state.pending.active():
            if marker.get("operation") != "place":
                self._direct_settle_marker_without_order(marker, facts)
                continue
            # live_state stores the SDK identity flat: ``native_identity`` is
            # the venue field mapping; client id / exchange are marker keys.
            fields = dict(marker.get("native_identity") or {})
            keys = identity_keys(fields, marker.get("client_order_id"))
            marker_day = fields.get("trading_day") or marker.get("trading_day")
            symbol = str(marker.get("symbol"))
            if marker.get("status") == "UNKNOWN" or (
                marker_day and marker_day != facts.trading_day
            ):
                # Older trading day or already UNKNOWN: the current session
                # cannot query it; keep it and block the instrument (R-3).
                if marker.get("status") != "UNKNOWN":
                    state.pending.mark(
                        marker["marker_id"], "UNKNOWN", reason="trading_day_not_queryable"
                    )
                report["unknown_markers"].append(marker["marker_id"])
                self._direct_blocked[symbol] = "pending_unknown"
                continue
            order_event = next((orders_by_key[k] for k in keys if k in orders_by_key), None)
            if order_event is None and getattr(facts, "orders", None) is None:
                # Without the complete same-day order list the absence of this
                # identity proves nothing: keep the marker and block the symbol.
                report["unknown_markers"].append(marker["marker_id"])
                self._direct_blocked[symbol] = "pending_unverified"
                continue
            if order_event is None:
                # A complete same-day order query without this identity: the
                # venue never held the order (not sent, or refused at the front).
                state.pending.mark(
                    marker["marker_id"],
                    "TERMINAL",
                    final_status="not_found_at_venue",
                    resolution_evidence="startup_complete_order_query",
                )
                continue
            if order_event.exchange_order_id:
                sys_key = (
                    "o",
                    str(order_event.symbol),
                    str(order_event.exchange_order_id).strip(),
                )
                for trade in trades_by_order.get(sys_key, ()):
                    if self._direct_trade_key(trade) not in self._direct_applied_set():
                        self._direct_apply_trade_to_legs(trade)
                        self._direct_remember_trade(trade)
                        report["applied_missing_trades"] += 1
            live_event = next((working[k] for k in keys if k in working), None)
            if live_event is not None:
                claimed.update(k for k in keys if k in working)
                if self._direct_restore_order(marker, live_event):
                    report["restored_orders"] += 1
                state.pending.mark(
                    marker["marker_id"],
                    "ACCEPTED",
                    resolution_evidence="startup_working_order",
                    order_sys_id=live_event.exchange_order_id,
                )
            else:
                final = order_event.status.value if order_event.status is not None else "terminal"
                state.pending.mark(
                    marker["marker_id"],
                    "TERMINAL",
                    final_status=str(final),
                    resolution_evidence="startup_complete_order_query",
                )
        self._direct_foreign_orders = [
            event
            for event in facts.active_orders or ()
            if event.identity is not None
            and not any(
                key in claimed
                for key in identity_keys(
                    dict(event.identity.fields), event.identity.client_order_id
                )
            )
        ]
        report["foreign_working_orders"] = len(self._direct_foreign_orders)
        # Instruments this strategy is configured to trade (Store symbol routes)
        # are reconciled even with a flat snapshot (D62-16); others are only
        # reported (D62-17).
        configured = {str(name) for name in (getattr(self.store, "_sdk_routes", None) or {})}
        symbols = (
            set(self.long_positions)
            | set(self.short_positions)
            | set(venue)
            | (configured & set(venue))
        )
        for symbol in sorted(symbols):
            local_long = abs(self.long_positions[symbol].size)
            local_short = abs(self.short_positions[symbol].size)
            if (
                not (local_long or local_short)
                and symbol not in local_positions
                and symbol not in configured
            ):
                if venue.get(symbol):
                    report["other_instruments"].append(symbol)  # D62-17: report only
                continue
            split = self._direct_split_of(symbol)
            for side, local_total in (("long", local_long), ("short", local_short)):
                fact = venue.get(symbol, {}).get(side)
                venue_total = fact.total if fact is not None else 0.0
                if abs(venue_total - local_total) > 1e-9:
                    report["mismatches"].append(
                        {"symbol": symbol, "side": side, "local": local_total, "venue": venue_total}
                    )
                    self._direct_blocked[symbol] = "startup_position_mismatch"
                    continue
                if fact is None:
                    continue
                local_today = split["today"][side]
                if fact.today is not None and local_today is not None:
                    if abs(fact.today - local_today) > 1e-9:
                        report["mismatches"].append(
                            {
                                "symbol": symbol,
                                "side": side,
                                "field": "today",
                                "local": local_today,
                                "venue": fact.today,
                            }
                        )
                        self._direct_blocked[symbol] = "startup_today_split_mismatch"
                        continue
                # Totals agree: the venue split is authoritative (D62-22).
                split["today"][side] = fact.today
                split["yesterday"][side] = fact.yesterday
        for symbol in list(self.long_positions):
            self._direct_sync_net(symbol)
        self._direct_report = report
        self._direct_write_snapshot()
        if report["mismatches"] or report["unknown_markers"]:
            _log.warning(
                "direct reconciliation blocked writes: mismatches=%d unknown=%d",
                len(report["mismatches"]),
                len(report["unknown_markers"]),
            )

    def _direct_settle_marker_without_order(self, marker: Dict[str, Any], facts: Any) -> None:
        """Cancel / settlement markers: the order state is the evidence."""
        if marker.get("status") == "UNKNOWN":
            self._direct_blocked["*"] = "pending_unknown"
            return
        final = "superseded_trading_day"
        if marker.get("trading_day") == facts.trading_day:
            final = "startup_rechecked"
        self._direct_state.pending.mark(
            marker["marker_id"],
            "TERMINAL",
            final_status=final,
            resolution_evidence="startup_complete_order_query",
        )

    def _direct_load_local(self, positions, prices, snapshot_day, trading_day) -> None:
        for symbol, entry in positions.items():
            split = self._direct_split_of(symbol)
            for side in ("long", "short"):
                leg_info = entry.get(side) or {}
                total = abs(_num(leg_info.get("total")))
                leg = (
                    self.long_positions[symbol] if side == "long" else self.short_positions[symbol]
                )
                price = _num((prices.get(symbol) or {}).get(side))
                leg.size = total
                leg.price = price if total else 0.0
                leg.price_orig = leg.price
                if snapshot_day and trading_day and snapshot_day != trading_day:
                    split["today"][side] = 0.0  # a new trading day: today -> history
                    split["yesterday"][side] = total
                else:
                    today, yesterday = leg_info.get("today"), leg_info.get("yesterday")
                    split["today"][side] = None if today is None else _num(today)
                    split["yesterday"][side] = None if yesterday is None else _num(yesterday)

    def _direct_split_of(self, symbol: str) -> Dict[str, Dict[str, Optional[float]]]:
        split = self._direct_split.get(symbol)
        if split is None:
            split = self._direct_split[symbol] = {
                "today": {"long": 0.0, "short": 0.0},
                "yesterday": {"long": 0.0, "short": 0.0},
            }
        return split

    def _direct_settle(self) -> None:
        """Confirm the settlement statement under admission (D62-20/29)."""
        if not self._direct_writes_enabled:
            return
        port = self._direct_state.pending.bind()
        try:
            status = self._direct_api.ensure_settlement_confirmed(
                self._direct_exchange, pre_dispatch_commit=port, host_scope=self._direct_uuid
            )
        except Exception as exc:
            self._direct_global_block = "settlement_unconfirmed"
            _log.warning("direct settlement confirmation failed: %s", type(exc).__name__)
            return
        value = getattr(status, "value", status)
        if value != "confirmed":
            self._direct_global_block = "settlement_unconfirmed"
        marker = getattr(port, "last_marker_id", None)
        if marker:
            self._direct_state.pending.mark(
                marker,
                "TERMINAL",
                final_status=str(value),
                resolution_evidence="settlement_readback",
            )

    # ------------------------------------------------------------------
    # strategy takeover of restored orders (R-6/7)
    # ------------------------------------------------------------------
    def take_over_restored_orders(self, strategy: Any) -> List[Order]:
        """Bind the strategy of this directory and hand over restored orders.

        Restored orders (working venue orders and waiting orders recovered at
        startup) are notified with ``order.info['restored'] = True`` once
        taken over.  While restored orders exist and no strategy took them
        over, new orders are refused (``restored_orders_not_taken_over``).
        """
        with self._direct_lock:
            if self._direct_strategy is not None and self._direct_strategy is not strategy:
                raise DirectModeError("strategy_already_bound")
            self._direct_strategy = strategy
            restored, self._direct_restored = list(self._direct_restored), []
            for order in restored:
                order.owner = strategy
                self.notify(order)
            return restored

    def get_restored_orders(self) -> List[Order]:
        return list(getattr(self, "_direct_restored", ()))

    def get_direct_reconcile_report(self) -> Dict[str, Any]:
        return dict(getattr(self, "_direct_report", {}) or {})

    def direct_writes_blocked(self) -> Dict[str, str]:
        blocked = dict(self._direct_blocked)
        if self._direct_global_block:
            blocked["*"] = self._direct_global_block
        if not self._direct_writes_enabled:
            blocked.setdefault("*", "write_admission_disabled")
        return blocked

    def get_direct_refresh_counts(self) -> Dict[str, Any]:
        counts: Dict[str, Any] = dict(self._direct_refresh_counts)
        catalog = self._direct_catalog_counters()
        if catalog is not None:
            counts["instrument_catalog"] = catalog
        return counts

    def _direct_catalog_counters(self) -> Optional[Dict[str, int]]:
        """Instrument-catalog query counters of the route's provider (D62-11), if any."""
        api = getattr(self, "_direct_api", None)
        if api is None or not self._direct_exchange:
            return None
        try:
            provider = api.direct_writes().provider(self._direct_exchange)
            counters = getattr(provider, "instrument_catalog_counters", None)
            return dict(counters()) if callable(counters) else None
        except Exception:  # report only; never fail a summary
            return None

    # ------------------------------------------------------------------
    # positions, closable view and account values
    # ------------------------------------------------------------------
    def _direct_symbol(self, data) -> str:
        cached = self._direct_data_symbol.get(id(data))
        if cached is not None:
            return cached
        params = getattr(data, "p", None)
        symbol = (
            getattr(params, "symbol", None)
            or getattr(params, "dataname", None)
            or getattr(data, "_dataname", None)
            or getattr(data, "_name", None)
        )
        symbol = str(symbol)
        self._direct_data_symbol[id(data)] = symbol
        return symbol

    def _direct_sync_net(self, symbol: str) -> Position:
        long_leg = self.long_positions[symbol]
        short_leg = self.short_positions[symbol]
        net = self.positions[symbol]
        size = abs(long_leg.size) - abs(short_leg.size)
        price = long_leg.price if size > 0 else (short_leg.price if size < 0 else 0.0)
        net.fix(size, price)
        return net

    def _direct_getposition(self, data, clone=True, side=None):
        symbol = self._direct_symbol(data)
        if side is not None:
            if side not in ("long", "short"):
                raise ValueError(f"Unsupported position_side {side!r}")
            leg = self.long_positions[symbol] if side == "long" else self.short_positions[symbol]
            return leg.clone() if clone else leg
        net = self._direct_sync_net(symbol)
        return net.clone() if clone else net

    def get_closable(self, data, side: str) -> Dict[str, Optional[float]]:
        """Closable view of one side (R-1); ``None`` means unknown, never zero."""
        if not self._direct_active():
            raise DirectModeError("closable_view_requires_direct_mode")
        return self._direct_closable(self._direct_symbol(data), side)

    def _direct_closable(
        self, symbol: str, side: str, exclude_ref: Optional[int] = None
    ) -> Dict[str, Optional[float]]:
        leg = self.long_positions[symbol] if side == "long" else self.short_positions[symbol]
        total = abs(leg.size)
        split = self._direct_split_of(symbol)
        today, yesterday = split["today"][side], split["yesterday"][side]
        frozen = {"close": 0.0, "close_today": 0.0, "close_yesterday": 0.0}
        for ref, meta in self._direct_meta.items():
            if ref == exclude_ref:
                continue  # the order being checked never freezes against itself
            order = self.orders.get(ref)
            if order is None or not order.alive() or meta.get("symbol") != symbol:
                continue
            offset = meta.get("offset")
            if offset in frozen and meta.get("close_side") == side:
                frozen[offset] += (
                    abs(order.executed.remsize) if order.executed.size else abs(order.size)
                )
        for event in self._direct_foreign_orders:
            if event.symbol != symbol or event.offset not in frozen:
                continue
            if ("long" if event.side == "sell" else "short") == side:
                frozen[event.offset] += _num(event.remaining_qty)
        all_frozen = sum(frozen.values())
        split_venue = self._direct_symbol_venue.get(symbol) in _SPLIT_VENUES
        closable_today = None
        if today is not None:
            closable_today = max(
                today - frozen["close_today"] - (0.0 if split_venue else frozen["close"]), 0.0
            )
        closable_yesterday = None
        if yesterday is not None:
            closable_yesterday = max(
                yesterday - frozen["close_yesterday"] - (frozen["close"] if split_venue else 0.0),
                0.0,
            )
        return {
            "total": total,
            "today": today,
            "yesterday": yesterday,
            "frozen_close": all_frozen,
            "closable": max(total - all_frozen, 0.0),
            "closable_today": closable_today,
            "closable_yesterday": closable_yesterday,
            # CTP ExchangeID (e.g. "SHFE"), None while unknown: SHFE/INE need
            # separate close_today / close_yesterday orders.
            "venue": self._direct_symbol_venue.get(symbol),
        }

    def _direct_apply_balance(self, balance: Any) -> None:
        if balance is None:
            return
        if balance.available is not None:
            self._cash = float(balance.available)
        if balance.balance is not None:
            self._value = float(balance.balance)

    # ------------------------------------------------------------------
    # order submission (R-10 order stage)
    # ------------------------------------------------------------------
    def _direct_tag_order(self, order: Order, valid: Any, offset: Any) -> None:
        if self._direct_selected():
            order.addinfo(
                valid_intent=capture_valid_intent(valid), offset_explicit=offset is not None
            )

    def _direct_submit(self, order: Order) -> Order:
        with self._direct_lock:
            symbol = self._direct_symbol(order.data)
            seq = self._direct_state.sequence.allocate(order.ref)
            meta = {
                "symbol": symbol,
                "local_seq": seq,
                "offset": order.info.get("offset"),
                "position_side": order.info.get("position_side"),
                "valid_intent": order.info.get("valid_intent")
                or {"kind": "unspecified", "value": None},
                "identity": None,
                "marker_id": None,
                "waiting_id": None,
                "trade_keys": set(),
            }
            order.addinfo(local_seq=seq)
            if getattr(order, "comminfo", None) is None:
                # BT trade bookkeeping reads the order's commission info on fills.
                order.addcomminfo(self.getcommissioninfo(order.data))
            self.orders[order.ref] = order
            self._direct_meta[order.ref] = meta
            reason = self._direct_precheck(order, meta)
            if reason is not None:
                return self._direct_reject(order, reason)
            route = self._direct_route(order)
            if route == "wait":
                return self._direct_enqueue_waiting(order, meta)
            if route != "dispatch":
                return self._direct_reject(order, route)
            return self._direct_dispatch(order, meta)

    def _direct_precheck(self, order: Order, meta: Dict[str, Any]) -> Optional[str]:
        if self._direct_stopping:
            return "broker_stopping"
        if not self._direct_writes_enabled:
            return "write_admission_disabled"
        if self._direct_global_block:
            return self._direct_global_block
        if "*" in self._direct_blocked:
            return self._direct_blocked["*"]
        if self._direct_restored and self._direct_strategy is None:
            return "restored_orders_not_taken_over"
        if self._direct_strategy is None and order.owner is not None:
            self._direct_strategy = order.owner  # one strategy per directory
        symbol = meta["symbol"]
        if symbol in self._direct_blocked:
            return self._direct_blocked[symbol]
        if order.exectype not in (Order.Limit, Order.Market):
            return "order_type_unrepresentable"
        if not _positive_finite(order.size, absolute=True):
            return "order_size_invalid"
        if order.exectype == Order.Limit and not _positive_finite(order.price):
            # e.g. a price computed from a feed line that is not written yet
            # (SimNow 2026-11-06: 0 + 2 ticks); refused here, never sent.
            return "limit_price_invalid"
        if meta["valid_intent"].get("kind") not in ("unspecified", "day"):
            return "order_validity_unrepresentable"
        offset = meta["offset"]
        if offset is None and self._direct_require_offset:
            return "explicit_offset_required"
        if offset is not None and offset not in OFFSETS:
            return "offset_invalid"
        if self._is_dual_side_mode() and meta["position_side"] not in ("long", "short"):
            return "position_side_required"
        if offset in _CLOSE_OFFSETS:
            side = "short" if order.isbuy() else "long"
            meta["close_side"] = side
            view = self._direct_closable(symbol, side, exclude_ref=order.ref)
            available = view[
                {
                    "close": "closable",
                    "close_today": "closable_today",
                    "close_yesterday": "closable_yesterday",
                }[offset]
            ]
            if available is None:
                return "closable_unknown"
            if abs(order.size) > available + 1e-9:
                return "insufficient_closable_position"
        return None

    def _direct_route(self, order: Order) -> str:
        """``dispatch``, ``wait`` (trusted closure, D62-30) or a reject reason."""
        data = order.data
        warming = getattr(data, "historical_warmup_active", None)
        if callable(warming) and warming():
            return "target_feed_warming_up"  # D62-15a: historical bars still replaying
        qualify = getattr(data, "trade_qualification", None)
        qualification = qualify() if callable(qualify) else None
        reasons = tuple(getattr(qualification, "reasons", ()) or ())
        phase = self._direct_phase(self._direct_symbol(data))
        if phase is not None and not phase.reason and phase.phase.value in ("closed", "auction"):
            # D62-30 / 5.3c: a real-time feed during a trusted closure creates a
            # durable waiting order; no fresh quote or LIVE status is required
            # now (both are rechecked before the actual dispatch).
            return "wait" if self.p.waiting_orders else "market_closed"
        if qualification is not None and "FEED_NOT_LIVE" in reasons:
            return "target_feed_not_live"  # D62-15a/15b: target not LIVE
        if qualification is not None and not getattr(qualification, "ok", False):
            return "target_data_not_tradable:" + ",".join(reasons[:3])
        return "dispatch"

    def _direct_phase(self, symbol: str, at: Optional[_dt.datetime] = None):
        if self._direct_schedule is None:
            return None
        try:
            return self._direct_schedule.session_state(symbol, at or _utc_now())
        except Exception:
            return None

    def _direct_reject(self, order: Order, reason: str) -> Order:
        meta = self._direct_meta.get(order.ref)
        if meta is not None:
            meta["rejected"] = reason
        self._reject_order(order, reason, f"direct mode refused the order: {reason}")
        return order

    def _direct_dispatch(self, order: Order, meta: Dict[str, Any]) -> Order:
        try:
            request = self._direct_request(order, meta)
        except (TypeError, ValueError) as exc:
            # The SDK request DTO refused a field: a local refusal, never an
            # exception into strategy code; nothing was reserved or sent.
            return self._direct_reject(order, f"request_unrepresentable:{str(exc)[:80]}")
        port = self._direct_state.pending.bind(local_seq=meta["local_seq"], bt_ref=order.ref)
        summary = {
            "local_seq": meta["local_seq"],
            "bt_ref": order.ref,
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(float(order.size)),
            "price": order.price,
            "offset": meta["offset"],
        }
        try:
            outcome = self._direct_api.make_order(
                self._direct_exchange,
                request,
                pre_dispatch_commit=port,
                host_scope=self._direct_uuid,
                request_summary=summary,
            )
        except Exception as exc:  # admission / mapping refused before any send
            code = getattr(exc, "code", None) or getattr(exc, "reason", None) or type(exc).__name__
            return self._direct_reject(order, f"direct_write_refused:{code}")
        meta["marker_id"] = outcome.marker_id
        meta["identity"] = outcome.identity
        if outcome.identity is not None:
            fields = dict(outcome.identity.fields)
            for key in identity_keys(fields, outcome.identity.client_order_id):
                self._direct_index[key] = order.ref
            if fields.get("exchange_id"):
                self._direct_symbol_venue.setdefault(meta["symbol"], str(fields["exchange_id"]))
        if outcome.sent is True:
            self._direct_mark(meta, "DISPATCHED")
            order.submit(self)
            self.notify(order)
            return order
        if outcome.sent is False:
            self._direct_mark(
                meta,
                "TERMINAL",
                final_status="not_sent",
                resolution_evidence=str(outcome.error_code or "not_sent"),
            )
            return self._direct_reject(order, f"not_sent:{outcome.error_code}")
        # Unknown send outcome: keep the marker DISPATCHED (to be verified by
        # identity-matched returns or at restart) and block the instrument.
        self._direct_mark(meta, "DISPATCHED", send_outcome="unknown", error=str(outcome.error_code))
        self._direct_blocked[meta["symbol"]] = "pending_unknown"
        meta["unknown"] = True
        order.addinfo(outcome_unknown=True)
        order.submit(self)
        self.notify(order)
        return order

    def _direct_request(self, order: Order, meta: Dict[str, Any]):
        from bt_api_py._contracts.models import OrderRequest, OrderType, Side

        is_limit = order.exectype == Order.Limit
        price = Decimal(str(order.price)) if is_limit and order.price is not None else None
        dual = self._is_dual_side_mode()
        return OrderRequest(
            symbol=meta["symbol"],
            side=Side.BUY if order.isbuy() else Side.SELL,
            order_type=OrderType.LIMIT if is_limit else OrderType.MARKET,
            quantity=Decimal(str(abs(float(order.size)))),
            account_id="direct",
            client_order_id=f"bt{(self._direct_uuid or '').replace('-', '')[:12]}s{meta['local_seq']}",
            price=price,
            # unspecified / DAY validity is the venue's trading-day order;
            # other validities were refused in the precheck (D62-31/33).
            time_in_force="GFD" if self._direct_require_offset else "GTC",
            offset=meta["offset"],
            position_side=meta["position_side"] if dual else None,
            position_mode="dual_side" if dual else None,
            exchange_id=(
                self._direct_symbol_venue.get(meta["symbol"])
                if self._direct_require_offset
                else None
            ),
            quantity_unit=self._direct_quantity_unit(meta["symbol"]),
        )

    def _direct_seed_configured_venues(self) -> None:
        """Start from the venues the host configured for its instruments.

        CTP orders carry an explicit ``ExchangeID``. A venue configured in the
        Store's ``contract_metadata`` (``instrument_key`` or ``exchange``) is
        used until the venue itself reports one (account facts and order
        identities overwrite it), so an order never waits for the provider's
        instrument-catalog lookup: on SimNow (2026-11-06) the full catalog
        query outlasted its order-path budget and a restored waiting order was
        refused ``ctp_direct_exchange_id_required``. A wrong configured venue
        is rejected by the venue, not trusted for anything else.
        """
        if not self._direct_require_offset:
            return  # only CTP-style routes send an exchange id
        metadata = getattr(self.store, "contract_metadata", None) or {}
        for symbol, entry in dict(metadata).items():
            if not isinstance(entry, Mapping):
                continue
            key = entry.get("instrument_key")
            venue = getattr(key, "venue", None) if key is not None else None
            venue = venue or entry.get("exchange_id") or entry.get("exchange")
            if isinstance(venue, str) and venue.strip():
                self._direct_symbol_venue.setdefault(str(symbol), venue.strip().upper())

    def _direct_quantity_unit(self, symbol: str) -> str:
        """Order quantity unit of ``symbol`` (``contract_metadata`` ``quantity_unit``).

        CTP lots and spot/USD-M base quantities use ``base``; OKX SWAP orders
        are contract counts and must be configured as ``contracts``.
        """
        metadata = getattr(self.store, "contract_metadata", None) or {}
        row = metadata.get(symbol) if isinstance(metadata, dict) else None
        unit = row.get("quantity_unit") if isinstance(row, dict) else None
        return str(unit) if unit in ("base", "contracts", "lots", "native") else "base"

    def _direct_mark(self, meta: Dict[str, Any], status: str, **facts: Any) -> None:
        marker = meta.get("marker_id")
        if marker:
            clean = {key: value for key, value in facts.items() if value is not None}
            self._direct_state.pending.mark(marker, status, **clean)

    # ------------------------------------------------------------------
    # cancel (local waiting orders, or venue orders by original identity)
    # ------------------------------------------------------------------
    def _direct_cancel(self, order: Order) -> Order:
        with self._direct_lock:
            order = self.orders.get(order.ref, order)
            meta = self._direct_meta.get(order.ref)
            if meta is None or not order.alive():
                return order
            if meta.get("waiting_id"):
                if self._direct_state.waiting.transition(
                    meta["waiting_id"], "WAITING", "CANCELLED", reason="strategy_cancel"
                ):
                    order.cancel()
                    self.notify(order)
                return order
            if meta.get("identity") is None or meta.get("cancel_requested"):
                return order
            port = self._direct_state.pending.bind(bt_ref=order.ref)
            try:
                outcome = self._direct_api.cancel_order(
                    self._direct_exchange,
                    meta["symbol"],
                    pre_dispatch_commit=port,
                    target_identity=self._direct_cancel_identity(meta),
                    host_scope=self._direct_uuid,
                )
            except Exception as exc:
                _log.warning("direct cancel refused for %s: %s", order.ref, type(exc).__name__)
                return order
            meta["cancel_requested"] = outcome.sent is not False
            if outcome.marker_id:
                if outcome.sent is False:
                    self._direct_state.pending.mark(
                        outcome.marker_id, "TERMINAL", final_status="not_sent"
                    )
                else:
                    self._direct_state.pending.mark(
                        outcome.marker_id,
                        "DISPATCHED",
                        **({"send_outcome": "unknown"} if outcome.sent is None else {}),
                    )
                meta.setdefault("cancel_markers", []).append(outcome.marker_id)
            return order

    def _direct_cancel_identity(self, meta: Dict[str, Any]):
        identity = meta["identity"]
        learned = meta.get("learned_fields") or {}
        if not learned:
            return identity
        from bt_api_base.direct_write_protocol import NativeOrderIdentity

        fields = dict(identity.fields)
        fields.update({key: value for key, value in learned.items() if value})
        return NativeOrderIdentity(
            exchange_name=identity.exchange_name,
            client_order_id=identity.client_order_id,
            fields=fields,
            session_generation=identity.session_generation,
        )

    # ------------------------------------------------------------------
    # event loop
    # ------------------------------------------------------------------
    def _direct_next(self) -> None:
        with self._direct_lock:
            if self._direct_awaiting_bar:
                self._direct_build_awaiting()
            if self._direct_deferred_restore:
                # Every feed of this run has started: a working order of ours
                # without a feed cannot be managed here.
                for marker, event in self._direct_deferred_restore:
                    self._direct_blocked[event.symbol] = "restored_order_without_data"
                self._direct_deferred_restore = []
            self._direct_drain_events()
            self._direct_consume_facts()
            self._direct_dispatch_waiting()

    def _direct_drain_events(self) -> None:
        try:
            items = self._direct_api.poll_direct_execution_events(
                self._direct_exchange, int(self.p.direct_max_events)
            )
        except Exception as exc:
            _log.warning("direct event poll failed: %s", type(exc).__name__)
            return
        for item in items:
            try:
                self._direct_process_event(item.event)
            except Exception:
                _log.exception("direct event projection failed")

    def _direct_order_for_event(self, event: Any) -> Optional[Order]:
        identity = event.identity
        if identity is None:
            return None
        fields = dict(identity.fields)
        for key in identity_keys(fields, identity.client_order_id):
            ref = self._direct_index.get(key)
            if ref is not None:
                return self.orders.get(ref)
        if event.exchange_order_id and fields.get("exchange_id"):
            key = ("x", str(fields["exchange_id"]), str(event.exchange_order_id))
            ref = self._direct_index.get(key)
            if ref is not None:
                return self.orders.get(ref)
        return None

    def _direct_process_event(self, event: Any) -> None:
        order = self._direct_order_for_event(event)
        if order is None:
            return  # another client's order: visible to audits, never adopted
        meta = self._direct_meta[order.ref]
        fields = dict(event.identity.fields) if event.identity is not None else {}
        if event.exchange_order_id and fields.get("exchange_id"):
            key = ("x", str(fields["exchange_id"]), str(event.exchange_order_id))
            self._direct_index.setdefault(key, order.ref)
            learned = meta.setdefault("learned_fields", {})
            learned["order_sys_id"] = str(event.exchange_order_id)
            if fields.get("order_sys_id_raw"):
                learned["order_sys_id_raw"] = fields["order_sys_id_raw"]
        kind = event.kind.value
        if kind == "trade":
            self._direct_apply_trade(order, meta, event)
            return
        if kind == "cancel_error":
            meta["cancel_requested"] = False
            order.addinfo(cancel_error=event.error_code, cancel_error_msg=event.error_message)
            for marker in meta.pop("cancel_markers", []):
                self._direct_state.pending.mark(marker, "TERMINAL", final_status="cancel_rejected")
            self.notify(order)
            return
        status = event.status.value if event.status is not None else None
        if kind == "order_error":
            status = "rejected"
        self._direct_resolve_unknown(meta, status)
        if status in ("accepted", "partially_filled", "filled") and order.status == Order.Submitted:
            order.accept(self)
            self.notify(order)
            self._direct_mark(meta, "ACCEPTED", order_sys_id=event.exchange_order_id)
        if status == "cancelled" and order.alive():
            # ``filled_qty`` is the venue's cumulative fill; a restored order
            # only executes fills after the restart.
            venue_filled = _num(event.filled_qty) - meta.get("venue_filled_before", 0.0)
            if venue_filled > abs(order.executed.size) + 1e-9:
                meta["pending_terminal"] = "cancelled"  # its trades are still to come
                meta["pending_filled"] = venue_filled
                return
            self._direct_finish(order, meta, "cancelled")
        elif status == "rejected" and order.alive():
            order.addinfo(
                error_code=str(event.error_code or "venue_rejected"),
                error_msg=str(event.error_message or ""),
            )
            if order.status == Order.Submitted or order.status == Order.Accepted:
                order.reject(self)
                self.notify(order)
            self._direct_mark(meta, "TERMINAL", final_status="rejected")

    def _direct_finish(self, order: Order, meta: Dict[str, Any], final: str) -> None:
        order.cancel()
        self.notify(order)
        self._direct_mark(meta, "TERMINAL", final_status=final)
        for marker in meta.pop("cancel_markers", []):
            self._direct_state.pending.mark(marker, "TERMINAL", final_status="order_cancelled")

    def _direct_resolve_unknown(self, meta: Dict[str, Any], status: Optional[str]) -> None:
        if not meta.get("unknown") or status is None:
            return
        meta["unknown"] = False
        symbol = meta["symbol"]
        if self._direct_blocked.get(symbol) == "pending_unknown" and not any(
            other.get("unknown") and other.get("symbol") == symbol
            for other in self._direct_meta.values()
        ):
            self._direct_blocked.pop(symbol, None)

    # ------------------------------------------------------------------
    # fills
    # ------------------------------------------------------------------
    @staticmethod
    def _direct_trade_key(event: Any) -> str:
        fields = dict(event.identity.fields) if event.identity is not None else {}
        parts = (
            fields.get("exchange_id") or "",
            event.trade_id or "",
            event.side or "",
            str(fields.get("order_sys_id") or event.exchange_order_id or "").strip(),
        )
        return "|".join(str(part) for part in parts)

    def _direct_applied_set(self) -> set:
        return set(self._direct_applied.get(self._direct_trading_day or "", ()))

    def _direct_remember_trade(self, event: Any) -> None:
        day = self._direct_trading_day or ""
        for other in [key for key in self._direct_applied if key != day]:
            self._direct_applied.pop(other, None)
        keys = self._direct_applied.setdefault(day, [])
        keys.append(self._direct_trade_key(event))
        if len(keys) > 5000:
            del keys[: len(keys) - 5000]

    def _direct_apply_trade_to_legs(self, event: Any):
        """Apply one venue trade to the long/short legs; return BT execution facts."""
        symbol = event.symbol
        qty = abs(_num(event.trade_qty))
        price = _num(event.trade_price)
        buy = event.side == "buy"
        offset = event.offset or "open"
        side = ("long" if buy else "short") if offset == "open" else ("short" if buy else "long")
        leg = self.long_positions[symbol] if side == "long" else self.short_positions[symbol]
        before_price = leg.price
        signed = self._make_signed_position(side, leg)
        size = qty if buy else -qty
        psize, pprice, opened, closed = signed.update(size, price)
        self._apply_signed_position(side, leg, signed)
        split = self._direct_split_of(symbol)
        venue = dict(event.identity.fields).get("exchange_id") if event.identity else None
        if venue:
            self._direct_symbol_venue.setdefault(symbol, str(venue))
        if offset == "open":
            if split["today"][side] is not None:
                split["today"][side] += qty
        elif offset == "close_today":
            if split["today"][side] is not None:
                split["today"][side] = max(split["today"][side] - qty, 0.0)
        elif offset == "close_yesterday" or venue in _SPLIT_VENUES:
            if split["yesterday"][side] is not None:
                split["yesterday"][side] = max(split["yesterday"][side] - qty, 0.0)
        else:
            # Which part a plain close consumes is venue specific: unknown
            # until the next venue observation (never assumed).
            split["today"][side] = None
            split["yesterday"][side] = None
        self._direct_sync_net(symbol)
        return size, price, psize, pprice, opened, closed, before_price

    def _direct_apply_trade(self, order: Order, meta: Dict[str, Any], event: Any) -> None:
        key = self._direct_trade_key(event)
        if key in meta["trade_keys"] or key in self._direct_applied_set():
            return  # duplicate return
        meta["trade_keys"].add(key)
        size, price, psize, pprice, opened, closed, before_price = self._direct_apply_trade_to_legs(
            event
        )
        self._direct_remember_trade(event)
        data = order.data
        comminfo = self.getcommissioninfo(data)
        closedvalue = comminfo.getoperationcost(closed, before_price) if closed else 0.0
        closedcomm = comminfo.getcommission(closed, price) if closed else 0.0
        openedvalue = comminfo.getoperationcost(opened, price) if opened else 0.0
        openedcomm = comminfo.getcommission(opened, price) if opened else 0.0
        pnl = comminfo.profitandloss(-closed, before_price, price) if closed else 0.0
        margin = comminfo.getvaluesize(size, price)
        dt = data.datetime[0] if len(data) else 0.0
        order.execute(
            dt,
            size,
            price,
            closed,
            closedvalue,
            closedcomm,
            opened,
            openedvalue,
            openedcomm,
            margin,
            pnl,
            psize,
            pprice,
        )
        if order.executed.remsize:
            order.partial()
            self.notify(order)
        else:
            order.completed()
            self.notify(order)
            self._direct_mark(meta, "TERMINAL", final_status="filled")
        if meta.get("pending_terminal") == "cancelled" and order.alive():
            filled = abs(order.executed.size)
            if filled + 1e-9 >= _num(meta.get("pending_filled", filled)):
                self._direct_finish(order, meta, "cancelled")
        self._direct_write_snapshot()

    # ------------------------------------------------------------------
    # snapshot: the stable reconciliation entry (logs/current_position.yaml)
    # ------------------------------------------------------------------
    def _direct_write_snapshot(self) -> None:
        state = self._direct_state
        if state is None:
            return
        positions: Dict[str, Any] = {}
        prices: Dict[str, Any] = {}
        for symbol in sorted(set(self.long_positions) | set(self.short_positions)):
            long_total = _snapshot_qty(abs(self.long_positions[symbol].size))
            short_total = _snapshot_qty(abs(self.short_positions[symbol].size))
            if not long_total and not short_total:
                continue
            split = self._direct_split_of(symbol)

            def _side(name: str, total: int) -> Dict[str, Any]:
                today = split["today"][name]
                yesterday = split["yesterday"][name]
                return {
                    "total": total,
                    "today": None if today is None else _snapshot_qty(today),
                    "yesterday": None if yesterday is None else _snapshot_qty(yesterday),
                }

            positions[symbol] = {
                "long": _side("long", long_total),
                "short": _side("short", short_total),
                "net": long_total - short_total,
            }
            prices[symbol] = {
                "long": float(self.long_positions[symbol].price or 0.0),
                "short": float(self.short_positions[symbol].price or 0.0),
            }
        state.snapshot.write(
            {
                "version": 2,
                "mode": "live",
                "strategy_uuid": self._direct_uuid,
                "account_hash": self._direct_account_hash,
                "exchange_name": self._direct_exchange,
                "trading_day": self._direct_trading_day,
                "positions": positions,
                "local_seq_high": int(state.sequence.local_seq),
                "applied_trades": {day: list(keys) for day, keys in self._direct_applied.items()},
                "position_prices": prices,
            }
        )

    # ------------------------------------------------------------------
    # waiting orders (D62-30/31/34/35/36; plan 5.3c)
    # ------------------------------------------------------------------
    def _direct_enqueue_waiting(self, order: Order, meta: Dict[str, Any]) -> Order:
        state = self._direct_phase(meta["symbol"])
        window = getattr(state, "next_continuous", None)
        if window is None:
            return self._direct_reject(order, "target_session_unknown")
        target = {
            "trading_day": str(window.trading_day).replace("-", ""),
            "continuous_start_utc": _utc_text(window.start_utc),
            "session_end_utc": _utc_text(window.end_utc),
        }
        record = {
            "local_seq": meta["local_seq"],
            "bt_ref": order.ref,
            "symbol": meta["symbol"],
            "exchange_name": self._direct_exchange,
            "side": "buy" if order.isbuy() else "sell",
            "size": abs(float(order.size)),
            "exectype": Order.ExecTypes[order.exectype],
            "price": order.price,
            "pricelimit": order.pricelimit,
            "offset": meta["offset"],
            "position_side": meta["position_side"],
            "valid_intent": meta["valid_intent"],
            "target_session": target,
            "created_at_utc": _utc_text(),
        }
        try:
            waiting_id = self._direct_state.waiting.add(record)
        except Exception as exc:
            code = getattr(exc, "code", None) or type(exc).__name__
            return self._direct_reject(order, f"waiting_persist_failed:{code}")
        meta["waiting_id"] = waiting_id
        meta["target_session"] = target
        order.addinfo(waiting_session=True, waiting_id=waiting_id, target_session=target)
        order.submit(self)
        self.notify(order)
        return order

    def _direct_restore_waiting(self) -> None:
        for record in sorted(self._direct_state.waiting.active(), key=lambda r: r["local_seq"]):
            data = self._direct_data_for_symbol(record["symbol"])
            if data is None:
                self._direct_deferred_waiting.append(record)
            else:
                self._direct_adopt_waiting(record, data)

    def _direct_data_started(self, data) -> None:
        symbol = self._direct_symbol(data)
        for item in [item for item in self._direct_deferred_restore if item[1].symbol == symbol]:
            self._direct_deferred_restore.remove(item)
            self._direct_restore_order(*item)
        for record in [r for r in self._direct_deferred_waiting if r["symbol"] == symbol]:
            self._direct_deferred_waiting.remove(record)
            self._direct_adopt_waiting(record, data)

    def _direct_adopt_waiting(self, record: Dict[str, Any], data) -> None:
        waiting_store = self._direct_state.waiting
        if record.get("status") == "DISPATCHING":
            markers = [
                marker
                for marker in self._direct_state.pending.active()
                + self._direct_state.pending.history()
                if marker.get("local_seq") == record["local_seq"]
                and marker.get("operation") == "place"
            ]
            proven_unsent = [
                marker
                for marker in markers
                if marker.get("status") == "TERMINAL"
                and (marker.get("facts") or {}).get("final_status") == "not_found_at_venue"
            ]
            if markers and len(proven_unsent) == len(markers):
                # Committed but proven never sent (complete same-day order list):
                # it may wait again inside its original target session.
                waiting_store.transition(
                    record["waiting_id"], "DISPATCHING", "WAITING", reason="restart_proven_unsent"
                )
                record = dict(record, status="WAITING")
                markers = []
            if markers:
                # A marker was committed: the pending path owns the outcome.
                waiting_store.transition(
                    record["waiting_id"],
                    "DISPATCHING",
                    "DISPATCHED",
                    marker_id=markers[-1]["marker_id"],
                    reason="restart_marker_found",
                )
                return
            waiting_store.transition(
                record["waiting_id"], "DISPATCHING", "WAITING", reason="restart_not_committed"
            )
            record = dict(record, status="WAITING")
        self._direct_build_waiting_order(record, data)

    def _direct_build_waiting_order(self, record: Dict[str, Any], data) -> None:
        if not len(data):
            # A BT Order needs the feed's current bar; build it on the first
            # broker ``next`` after the feed delivered one.
            self._direct_awaiting_bar.append(("waiting", record, data))
            return
        cls = BuyOrder if record["side"] == "buy" else SellOrder
        order = cls(
            owner=None,
            data=data,
            size=record["size"],
            price=record.get("price"),
            pricelimit=record.get("pricelimit"),
            exectype=Order.ExecTypes.index(record["exectype"]),
            valid=None,
        )
        order.addinfo(
            offset=record.get("offset"),
            position_side=record.get("position_side"),
            local_seq=record["local_seq"],
            restored=True,
            waiting_session=True,
            waiting_id=record["waiting_id"],
            original_ref=record.get("bt_ref"),
            target_session=record["target_session"],
            valid_intent=record["valid_intent"],
        )
        order.addcomminfo(self.getcommissioninfo(data))
        order.submit(self)
        self.orders[order.ref] = order
        self._direct_meta[order.ref] = {
            "symbol": record["symbol"],
            "local_seq": record["local_seq"],
            "offset": record.get("offset"),
            "position_side": record.get("position_side"),
            "valid_intent": record["valid_intent"],
            "identity": None,
            "marker_id": None,
            "waiting_id": record["waiting_id"],
            "target_session": record["target_session"],
            "trade_keys": set(),
        }
        self._direct_hand_over(order)

    def _direct_hand_over(self, order: Order) -> None:
        """Give a restored order to the bound strategy, or keep it for takeover."""
        strategy = self._direct_strategy
        if strategy is None:
            self._direct_restored.append(order)
            return
        order.owner = strategy
        self.notify(order)

    def _direct_build_awaiting(self) -> None:
        pending, self._direct_awaiting_bar = self._direct_awaiting_bar, []
        for item in pending:
            data = item[-1]
            if not len(data):
                self._direct_awaiting_bar.append(item)
            elif item[0] == "waiting":
                self._direct_build_waiting_order(item[1], data)
            else:
                self._direct_restore_order(item[1], item[2])

    def _direct_dispatch_waiting(self) -> None:
        if self._direct_stopping:
            return
        queue = sorted(
            (meta["local_seq"], ref)
            for ref, meta in self._direct_meta.items()
            if meta.get("waiting_id")
            and ref in self.orders
            and self.orders[ref].status == Order.Submitted
            and meta.get("identity") is None
        )
        now = _utc_now()
        for _seq, ref in queue:
            order = self.orders[ref]
            meta = self._direct_meta[ref]
            target = meta["target_session"]
            start = _parse_utc(target.get("continuous_start_utc"))
            end = _parse_utc(target.get("session_end_utc"))
            if end is not None and now >= end:
                if self._direct_state.waiting.transition(
                    meta["waiting_id"], "WAITING", "EXPIRED", reason="target_session_ended"
                ):
                    # ``Order.expire()`` only expires a passed ``valid``; a
                    # waiting order has none, so set the terminal status.
                    order.status = Order.Expired
                    self.notify(order)
                continue
            if start is None or now < start:
                return  # FIFO per strategy: later orders may not overtake (D62-35)
            if self._direct_restored and self._direct_strategy is None:
                return
            phase = self._direct_phase(meta["symbol"], now)
            if phase is None or phase.reason or phase.phase.value != "continuous":
                return  # auction / unknown: no dispatch (D62-34)
            qualify = getattr(order.data, "trade_qualification", None)
            qualification = qualify() if callable(qualify) else None
            if qualification is not None and not getattr(qualification, "ok", False):
                return  # wait for qualified real-time data in the target session
            reason = self._direct_precheck(order, meta)
            if reason is not None:
                if self._direct_state.waiting.transition(
                    meta["waiting_id"], "WAITING", "REJECTED", reason=reason
                ):
                    self._direct_reject(order, reason)
                continue
            if not self._direct_state.waiting.transition(
                meta["waiting_id"], "WAITING", "DISPATCHING"
            ):
                continue
            self._direct_dispatch_waiting_order(order, meta)

    def _direct_dispatch_waiting_order(self, order: Order, meta: Dict[str, Any]) -> None:
        waiting_id = meta["waiting_id"]
        order.status = Order.Created  # dispatch submits it to the venue now
        self._direct_dispatch(order, meta)
        if order.status == Order.Rejected:
            self._direct_state.waiting.transition(
                waiting_id, "DISPATCHING", "REJECTED", reason=order.info.get("error_code")
            )
        else:
            self._direct_state.waiting.transition(
                waiting_id, "DISPATCHING", "DISPATCHED", marker_id=meta.get("marker_id")
            )
            meta["waiting_id"] = None

    # ------------------------------------------------------------------
    # funds refresh and position audit (D62-06a/06b)
    # ------------------------------------------------------------------
    def _direct_start_facts_poller(self) -> None:
        if self._direct_facts_thread is not None:
            return
        self._direct_facts_stop.clear()
        thread = threading.Thread(
            target=self._direct_facts_loop, name="bt-direct-facts", daemon=True
        )
        self._direct_facts_thread = thread
        thread.start()

    def _direct_facts_loop(self) -> None:
        funds_every = max(float(self.p.direct_funds_refresh_interval or 0.0), 0.0)
        audit_every = max(float(self.p.direct_position_audit_interval or 0.0), 0.0)
        while not self._direct_facts_stop.wait(1.0):
            now = time.monotonic()
            want_audit = bool(audit_every) and now - self._direct_last_audit >= audit_every
            want_funds = bool(funds_every) and now - self._direct_last_funds >= funds_every
            if not (want_audit or want_funds):
                continue
            try:
                if want_audit:
                    facts = self._direct_read_facts()
                    self._direct_last_audit = self._direct_last_funds = time.monotonic()
                    self._direct_refresh_counts["audit"] += 1
                    self._direct_facts_results.append(("audit", facts))
                else:
                    facts = self._direct_read_facts(positions=False, active_orders=False)
                    self._direct_last_funds = time.monotonic()
                    self._direct_refresh_counts["funds"] += 1
                    self._direct_facts_results.append(("funds", facts))
            except Exception as exc:
                self._direct_refresh_counts["failed"] += 1
                self._direct_last_funds = time.monotonic()
                _log.warning("direct facts refresh failed: %s", type(exc).__name__)

    def _direct_consume_facts(self) -> None:
        while self._direct_facts_results:
            kind, facts = self._direct_facts_results.popleft()
            self._direct_apply_balance(facts.balance)
            if kind == "audit" and facts.positions is not None and facts.active_orders is not None:
                self._direct_audit(facts)

    def _direct_audit(self, facts: Any) -> None:
        if facts.trading_day and facts.trading_day != self._direct_trading_day:
            self._direct_roll_trading_day(facts.trading_day)
        busy = {
            meta["symbol"]
            for ref, meta in self._direct_meta.items()
            if ref in self.orders and self.orders[ref].alive() and meta.get("identity") is not None
        }
        remote: Dict[str, Dict[str, Any]] = {}
        for fact in facts.positions:
            fact = _leg_fact(fact)
            if fact is not None:
                remote.setdefault(fact.symbol, {})[fact.side] = fact
        self._direct_foreign_orders = [
            event for event in facts.active_orders if self._direct_order_for_event(event) is None
        ]
        for symbol in sorted(set(self.long_positions) | set(self.short_positions)):
            if symbol in busy:
                continue  # in-flight orders make the comparison racy
            split = self._direct_split_of(symbol)
            for side in ("long", "short"):
                leg = (
                    self.long_positions[symbol] if side == "long" else self.short_positions[symbol]
                )
                fact = remote.get(symbol, {}).get(side)
                venue_total = fact.total if fact is not None else 0.0
                if abs(venue_total - abs(leg.size)) > 1e-9:
                    self._direct_blocked[symbol] = "position_audit_mismatch"
                    _log.warning("direct position audit mismatch on %s %s", symbol, side)
                elif fact is not None:
                    split["today"][side] = fact.today
                    split["yesterday"][side] = fact.yesterday

    def _direct_roll_trading_day(self, trading_day: str) -> None:
        """R-3 (minimal): on a new trading day today's positions become history."""
        self._direct_trading_day = trading_day
        for symbol in set(self.long_positions) | set(self.short_positions):
            split = self._direct_split_of(symbol)
            for side in ("long", "short"):
                leg = (
                    self.long_positions[symbol] if side == "long" else self.short_positions[symbol]
                )
                split["today"][side] = 0.0
                split["yesterday"][side] = abs(leg.size)
        self._direct_write_snapshot()

    # ------------------------------------------------------------------
    # stop (D62-19: cancel own working orders, never flatten)
    # ------------------------------------------------------------------
    def _direct_stop(self) -> Dict[str, Any]:
        if self._direct_stopping:
            return dict(self._shutdown_summary)  # already stopped: idempotent
        self._direct_stopping = True
        self._direct_facts_stop.set()
        if not self._direct_on:
            return self._direct_stop_after_failed_start()
        timeout = max(float(self.p.stop_cancel_timeout or 0.0), 0.0)
        with self._direct_lock:
            working = [
                self.orders[ref]
                for ref, meta in self._direct_meta.items()
                if ref in self.orders
                and self.orders[ref].alive()
                and meta.get("identity") is not None
            ]
            for order in working:
                self._direct_cancel(order)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and any(order.alive() for order in working):
            with self._direct_lock:
                self._direct_drain_events()
            time.sleep(0.05)
        unresolved = [order.ref for order in working if order.alive()]
        with self._direct_lock:
            self._direct_write_snapshot()
        self._direct_release_lock()
        self._direct_on = False
        self._startup_ready = False
        self._live_started = False
        summary = {
            "status": "STOPPED" if not unresolved else "STOPPED_WITH_WORKING_ORDERS",
            "cancelled_requested": len(working),
            "unresolved_working_orders": len(unresolved),
            "waiting_orders_kept": len(self._direct_state.waiting.waiting()),
        }
        self._shutdown_summary = summary
        if unresolved:
            _log.warning("direct stop left %d working orders unresolved", len(unresolved))
        stop_store = getattr(self.store, "stop", None)
        if callable(stop_store):
            try:
                stop_store()
            except Exception as exc:
                _log.warning("direct store stop failed: %s", type(exc).__name__)
        return summary

    def _direct_stop_after_failed_start(self) -> Dict[str, Any]:
        """``stop()`` after ``_direct_start`` raised: local cleanup only.

        Writes were never enabled, so nothing is cancelled or written to the
        account; the run lock (if taken) is released and a Store the attempt
        started is stopped.
        """
        self._direct_release_lock()
        summary = {
            "status": "NOT_STARTED",
            "reason": "direct_start_failed",
            "cancelled_requested": 0,
            "unresolved_working_orders": 0,
        }
        self._shutdown_summary = summary
        self._startup_ready = False
        if self._live_started:
            self._live_started = False
            stop_store = getattr(self.store, "stop", None)
            if callable(stop_store):
                try:
                    stop_store()
                except Exception as exc:
                    _log.warning("direct store stop failed: %s", type(exc).__name__)
        return dict(summary)

    def _direct_release_lock(self) -> None:
        lock, self._direct_run_lock = self._direct_run_lock, None
        if lock is not None:
            try:
                lock.release()
            except Exception:
                _log.warning("direct run lock release failed")

    # ------------------------------------------------------------------
    # restored venue orders
    # ------------------------------------------------------------------
    def _direct_data_for_symbol(self, symbol: str):
        for data in list(getattr(self.store, "_data_feeds", []) or []):
            if self._direct_symbol(data) == symbol:
                return data
        return None

    def _direct_restore_order(self, marker: Dict[str, Any], event: Any) -> bool:
        data = self._direct_data_for_symbol(event.symbol)
        if data is None:
            # Feeds attach after the broker starts: restore when the feed of
            # this symbol starts (``data_started``); a symbol without a feed
            # in this run is blocked at the first ``next``.
            self._direct_deferred_restore.append((marker, event))
            return True
        if not len(data):
            self._direct_awaiting_bar.append(("restore", marker, event, data))
            return True
        from bt_api_base.direct_write_protocol import NativeOrderIdentity

        cls = BuyOrder if event.side == "buy" else SellOrder
        # Restore the still-working part: fills before the restart are already
        # in the position legs (applied above or in the snapshot).
        remaining = _num(event.remaining_qty)
        size = remaining or _num(event.order_qty)
        filled_before = _num(event.filled_qty) if remaining else 0.0
        order = cls(
            owner=None,
            data=data,
            size=size,
            price=event.limit_price,
            exectype=Order.Limit,
            valid=None,
        )
        identity = NativeOrderIdentity(  # live_state marker: flat native identity
            exchange_name=marker.get("exchange_name") or self._direct_exchange,
            client_order_id=marker.get("client_order_id") or None,
            fields=dict(marker.get("native_identity") or {}),
            session_generation=marker.get("session_generation"),
        )
        order.addinfo(
            offset=event.offset,
            restored=True,
            local_seq=marker.get("local_seq"),
            original_ref=marker.get("bt_ref"),
            venue_order_qty=_num(event.order_qty),
            venue_filled_before=filled_before,
        )
        position_side = None
        if self._is_dual_side_mode():
            # The leg follows from side + offset, as in the trade projection.
            buy = event.side == "buy"
            opening = (event.offset or "open") == "open"
            position_side = (
                ("long" if buy else "short") if opening else ("short" if buy else "long")
            )
            order.addinfo(position_side=position_side)
        order.addcomminfo(self.getcommissioninfo(data))
        order.submit(self)
        order.accept(self)
        self.orders[order.ref] = order
        meta = {
            "symbol": event.symbol,
            "local_seq": marker.get("local_seq"),
            "offset": event.offset,
            "position_side": position_side,
            "valid_intent": {"kind": "day", "value": None},
            "identity": identity,
            "marker_id": marker["marker_id"],
            "waiting_id": None,
            "trade_keys": set(),
            "learned_fields": (
                {"order_sys_id": event.exchange_order_id} if event.exchange_order_id else {}
            ),
            "venue_filled_before": filled_before,
        }
        if event.offset in _CLOSE_OFFSETS:
            meta["close_side"] = "long" if event.side == "sell" else "short"
        self._direct_meta[order.ref] = meta
        for key in identity_keys(dict(identity.fields), identity.client_order_id):
            self._direct_index[key] = order.ref
        if event.exchange_order_id and identity.fields.get("exchange_id"):
            # Trade returns carry only ExchangeID + OrderSysID (as learned in
            # ``_direct_process_event`` for live orders).
            venue_key = ("x", str(identity.fields["exchange_id"]), str(event.exchange_order_id))
            self._direct_index.setdefault(venue_key, order.ref)
        self._direct_hand_over(order)
        return True


def direct_params():
    """Params appended to ``BtApiBroker.params`` for direct mode."""
    return _DIRECT_PARAMS
