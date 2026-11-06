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
  position legs and notifications; nothing is inferred from silence;
* a provider trading-day change while running (R-3) freezes new orders until
  the new day is re-verified: session and account, the new day's settlement
  (D62-29), one complete account observation, old-day pending markers
  (verified or UNKNOWN, D62-14) and the venue's today/yesterday split (D62-22).

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
from ..utils.log_message import get_logger, throttled_warning

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
    # Trading-permission facts (D62-25): read once after the startup
    # reconciliation on routes that need an explicit offset (CTP); an order
    # is refused locally only on a complete, current, definitive negative.
    ("direct_permission_check", True),
    ("direct_permission_timeout", 5.0),
    ("direct_permission_max_duration", 60.0),
    # R-3: seconds between verification attempts of a pending trading-day
    # switch (new orders stay frozen until one attempt verifies everything).
    ("direct_day_switch_retry_interval", 15.0),
    # Seconds stop() waits for a settlement confirmation the facts poller
    # committed before stop() began (no poller write starts after it).  Must
    # exceed the provider's worst case after the commit (CTP: 15 s confirm wait
    # + 15 s readback, about 31 s); past it the run lock stays with the write.
    ("direct_stop_write_timeout", 35.0),
    # Automatic resolution attempts of an unclear settlement confirmation of
    # the current trading day (D62-29, user decision 2026-11-06).  Attempts are
    # spaced by ``direct_day_switch_retry_interval`` doubling up to 8x (15, 30,
    # 60, then 120 s: 10 attempts span about 15 minutes, enough for a CTP front
    # reconnect or query throttling; each costs one read-only readback, plus
    # one confirmation only after a readback proved the earlier one absent).
    # Then the block stays and the report says ``manual_required``.
    ("direct_settlement_resolution_attempts", 10),
    # Seconds a trade return that matches no own order is held for a re-match
    # after later order returns (decision 8 of the continuity analysis, user
    # decision 2026-11-06): a CTP fill can overtake the order return that
    # carries its OrderSysID when the SDK delivers them in one poll in the
    # wrong order or across polls.  Both are pushed on one private stream
    # milliseconds apart, so 5 s covers several event polls and a burst of
    # throttled returns while a foreign fill is still reported promptly.
    # Expiry is checked after each event poll, once that poll's returns were
    # processed; 0 keeps only the same poll.  Then the trade is not ours.
    ("direct_trade_match_window", 5.0),
)
_MAX_BUFFERED_TRADES = 256
_MAX_PERMISSION_REPORT_SYMBOLS = 32
_SETTLEMENT_BACKOFF_FACTOR_MAX = 8
_MAX_SETTLEMENT_READBACK_ENTRIES = 20
# Resolution results no later automatic attempt can change (operator needed).
_SETTLEMENT_MANUAL_RESULTS = frozenset(
    ("account_unverified", "readback_unavailable", "write_admission_disabled")
)
# Global blocks a trading-day switch cannot clear by itself (operator restart).
_DAY_SWITCH_TERMINAL_BLOCKS = frozenset(("trading_day_regressed", "account_binding_mismatch"))
# Main cause of a target-data refusal (iteration 62 decision 6): the first
# failed dimension in this order is reported in ``error_code``; every reason
# goes to ``order.info["refusal_reasons"]`` and the log.  Earlier groups make
# the later ones unmeasurable or are their cause:
#   1. invalid limits or clock domain: no age can be measured at all;
#   2. no admitted real-time tick (none yet, or the latest failed ingestion);
#   3. clock evidence: an unverified source/receive clock or freshness makes
#      every latency figure (and the SDK verdict) meaningless;
#   4. receive staleness: nothing arrived within receive_time_max_age, so the
#      last tick's receipt-time verdicts are old facts (quiet or stalled feed);
#   5. event staleness: the latest tick was already late when received (BT's
#      configured limit first, then the SDK's own FRESHNESS_STALE);
#   6. the SDK's execution verdict, the least specific (it also covers
#      continuity); unknown codes come after all known ones, in order.
# FEED_NOT_LIVE is reported separately as ``target_feed_not_live``.
_REFUSAL_REASON_PRIORITY = (
    "RECEIVE_TIME_MAX_AGE_INVALID",
    "EVENT_TIME_MAX_AGE_INVALID",
    "NOW_MONOTONIC_INVALID",
    "RECEIVE_AGE_INVALID",
    "REALTIME_TICK_UNAVAILABLE",
    "TICK_EVENT_TIME_UNAVAILABLE",
    "TICK_RECEIVE_TIME_UNAVAILABLE",
    "TICK_RECEIVE_MONOTONIC_UNAVAILABLE",
    "SOURCE_CLOCK_UNVERIFIED",
    "RECEIVE_CLOCK_UNVERIFIED",
    "EVENT_TIME_AFTER_RECEIVE",
    "FRESHNESS_UNAVAILABLE",
    "FRESHNESS_INVALID",
    "RECEIVE_TIME_STALE",
    "EVENT_TIME_STALE",
    "FRESHNESS_STALE",
    "UPSTREAM_EXECUTION_INELIGIBLE",
)
_REFUSAL_REASON_RANK = {code: rank for rank, code in enumerate(_REFUSAL_REASON_PRIORITY)}


class DirectModeError(RuntimeError):
    """A direct-mode precondition failed; ``code`` is a stable reason."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _monotonic() -> float:
    """Monotonic seconds of the trade re-match window (patched by tests)."""
    return time.monotonic()


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


def _valid_trading_day(value: Any) -> bool:
    """``YYYYMMDD`` text of a real date (the provider session trading-day form)."""
    if type(value) is not str or len(value) != 8 or not value.isdigit():
        return False
    try:
        _dt.datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _settlement_class(outcome: Optional[Dict[str, Any]]) -> str:
    """Classify one settlement step of a trading-day switch (D62-29).

    ``unclear`` means a confirmation was durably committed (so it may have been
    sent) without a confirmed result: it is never repeated automatically.
    ``unverified`` means nothing was committed, hence nothing was sent, and a
    later read-first attempt is allowed.
    """
    if not outcome:
        return "not_run"
    if outcome.get("skipped"):
        return "skipped"
    if outcome.get("error") is None and outcome.get("value") == "confirmed":
        return "confirmed"
    if outcome.get("marker_id"):
        return "unclear"
    return "unverified"


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


def main_refusal_reason(reasons: Any) -> str:
    """The main cause among a refused qualification's ``reasons`` (decision 6).

    The highest-priority known code (see ``_REFUSAL_REASON_PRIORITY``), else
    the first reported code, else ``UNSPECIFIED``.
    """
    reasons = tuple(str(reason) for reason in reasons or ())
    known = [reason for reason in reasons if reason in _REFUSAL_REASON_RANK]
    if known:
        return min(known, key=_REFUSAL_REASON_RANK.__getitem__)
    return reasons[0] if reasons else "UNSPECIFIED"


def _trade_qualification_reader(data: Any) -> Any:
    """The ``trade_qualification`` of ``data``, or of the feed it was cloned from.

    A resampled/replayed clone (``DataClone``) keeps its source feed in
    ``.data`` but has no qualification of its own; the source feed's is the
    one that proves LIVE status and clock quality. Anything else without the
    contract (e.g. a strategy placeholder) yields ``None``.
    """
    for candidate in (data, getattr(data, "data", None)):
        reader = getattr(candidate, "trade_qualification", None) if candidate is not None else None
        if callable(reader):
            return reader
    return None


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


class _StopFencedPort:
    """Pre-dispatch commit port that refuses the commit once ``stop()`` began.

    The SDK commits the host marker immediately before the native send and
    sends nothing when the commit is refused, so no settlement confirmation
    can start after ``stop()`` set ``_direct_stopping`` (checked under the
    gate ``_direct_stop`` takes).  Everything else is the wrapped port's.
    """

    __slots__ = ("_port", "_broker")

    def __init__(self, port: Any, broker: Any) -> None:
        self._port = port
        self._broker = broker

    @property
    def store(self) -> Any:
        return self._port.store

    @property
    def last_marker_id(self) -> Optional[str]:
        return self._port.last_marker_id

    def commit(self, record: Any) -> Optional[str]:
        broker = self._broker
        with broker._direct_write_gate:
            if broker._direct_stopping:
                return None
            marker_id = self._port.commit(record)
            if broker._direct_poller_write is not None:
                broker._direct_poller_write["marker_id"] = marker_id
            return marker_id


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
        # Trade returns waiting for their order return (decision 8): key
        # (trading day, trade key) -> {"event", "deadline"}; strategy thread.
        self._direct_trade_buffer: "collections.OrderedDict[tuple, Dict[str, Any]]" = (
            collections.OrderedDict()
        )
        self._direct_restored: List[Order] = []
        self._direct_deferred_waiting: List[Dict[str, Any]] = []
        self._direct_deferred_restore: List[Any] = []
        self._direct_awaiting_bar: List[Any] = []
        self._direct_strategy: Any = None
        self._direct_report: Dict[str, Any] = {}
        self._direct_permissions: Any = None
        self._direct_permission_denials: Dict[str, str] = {}
        self._direct_schedule: Any = None
        self._direct_facts_thread: Optional[threading.Thread] = None
        self._direct_facts_stop = threading.Event()
        self._direct_facts_results: collections.deque = collections.deque(maxlen=8)
        self._direct_last_funds = 0.0
        self._direct_last_audit = 0.0
        self._direct_refresh_counts = {
            "funds": 0,
            "audit": 0,
            "failed": 0,
            "day_switch": 0,
            "settlement_resolution": 0,
        }
        self._direct_lock = threading.RLock()
        # R-3 trading-day switch: state owned by the strategy thread; the
        # request (target day, run settlement) is handed to the facts poller.
        self._direct_session_generation: Optional[int] = None
        self._direct_day_switch: Optional[Dict[str, Any]] = None
        self._direct_day_switch_lock = threading.Lock()
        self._direct_day_switch_request: Optional[tuple] = None
        self._direct_day_switch_inflight = False
        self._direct_day_switch_due = 0.0
        # The facts poller's only venue write (a switch settlement) is fenced
        # against stop(): ``_direct_stopping`` is set and checked under this
        # gate; stop() waits on it for a write already in flight.
        self._direct_write_gate = threading.Condition(threading.Lock())
        self._direct_poller_write: Optional[Dict[str, Any]] = None  # in flight
        self._direct_poller_outcome: Optional[Dict[str, Any]] = None  # last ended
        self._direct_poller_handoff = False  # stop() returned first: the poller finishes
        # Resolution of an unclear settlement confirmation (D62-29): the state
        # (also the report's ``settlement_resolution``) is owned by the strategy
        # thread; the trading day under resolution is handed to the facts
        # poller (request/due/inflight under ``_direct_day_switch_lock``).
        self._direct_settlement: Optional[Dict[str, Any]] = None
        self._direct_settlement_request: Optional[str] = None
        self._direct_settlement_due = 0.0
        self._direct_settlement_inflight = False

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
        window = self.p.direct_trade_match_window
        if (
            isinstance(window, bool)
            or not isinstance(window, (int, float))
            or not math.isfinite(window)
            or window < 0
        ):
            raise DirectModeError("direct_trade_match_window_invalid")
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
        self._direct_session_generation = facts.session_generation
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
            self._direct_read_permissions()
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
                self._direct_settle_marker_without_order(marker, facts, report)
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

    def _direct_settle_marker_without_order(
        self, marker: Dict[str, Any], facts: Any, report: Optional[Dict[str, Any]] = None
    ) -> None:
        """Cancel / settlement markers: the order state is the evidence."""
        if marker.get("status") == "UNKNOWN":
            if not self._direct_settlement_resolvable(marker, facts.trading_day):
                self._direct_blocked["*"] = "pending_unknown"
            # else: resolved by the startup settlement step (_direct_settle).
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

    # ------------------------------------------------------------------
    # resolution of an unclear settlement confirmation (D62-29; user
    # decision 2026-11-06: read first, then decide, also while running)
    # ------------------------------------------------------------------
    # An unclear confirmation (committed, so possibly sent, without a clear
    # result) of the verified current route and trading day leaves its marker
    # UNKNOWN and blocks writes (``settlement_unconfirmed``), whether the
    # startup step or a running switch made it.  Each resolution attempt (the
    # first one synchronously at startup, later ones on the facts poller with
    # backoff) reads the provider's settlement state read-only on a session
    # whose generation and trading day are unchanged across the read, with the
    # account reference re-checked:
    #   confirmed    -> the markers TERMINAL (``settlement_readback``), unblocked;
    #   unconfirmed  -> (complete and definitive: the confirmation did not take
    #                   effect) the markers TERMINAL
    #                   (``settlement_readback_unconfirmed``), then the normal SDK
    #                   settlement step under admission; an unclear result again
    #                   leaves a new UNKNOWN marker and the loop continues;
    #   otherwise    -> still blocked, retried after the backoff.
    # After ``direct_settlement_resolution_attempts`` the loop stops
    # (``manual_required``, block kept).  Markers of other days, routes or
    # operations are never touched here (manual resolution).
    def _direct_settlement_resolvable(self, marker: Dict[str, Any], day: Any) -> bool:
        """An UNKNOWN settlement confirmation of this route and of trading day ``day``.

        The strategy directory is bound to this account (a rebind needs an
        empty pending set), so the route and day identify the account's
        settlement the marker stands for.
        """
        return (
            marker.get("operation") == "settlement_confirm"
            and marker.get("status") == "UNKNOWN"
            and _valid_trading_day(day)
            and marker.get("trading_day") == day
            and marker.get("exchange_name") == self._direct_exchange
        )

    def _direct_resolvable_settlement_markers(self, day: Any) -> List[Dict[str, Any]]:
        return [
            marker
            for marker in self._direct_state.pending.active()
            if self._direct_settlement_resolvable(marker, day)
        ]

    def _direct_begin_settlement_resolution(
        self, day: Any, source: str, *, schedule: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Block writes and start (or keep) the resolution loop of ``day``."""
        if self._direct_global_block not in _DAY_SWITCH_TERMINAL_BLOCKS:
            self._direct_global_block = "settlement_unconfirmed"
        if not _valid_trading_day(day):
            return None  # no verifiable day: the block stays for manual resolution
        current = self._direct_settlement
        if current is not None and current["status"] == "pending":
            if current["trading_day"] == day:
                return current
            self._direct_end_settlement_resolution(current, "superseded", "trading_day_changed")
        resolution: Dict[str, Any] = {
            "status": "pending",
            "trading_day": day,
            "source": source,
            "attempts": 0,
            "max_attempts": max(int(self.p.direct_settlement_resolution_attempts or 0), 0),
            "last_result": None,
            "last_settlement": None,
            "reconfirmations": 0,
            "started_at_utc": _utc_text(),
            "updated_at_utc": None,
        }
        self._direct_settlement = resolution
        self._direct_report["settlement_resolution"] = resolution
        if not resolution["max_attempts"]:
            self._direct_end_settlement_resolution(resolution, "manual_required", "disabled")
        elif schedule:
            self._direct_schedule_settlement_attempt(resolution)
        return resolution

    def _direct_schedule_settlement_attempt(self, resolution: Dict[str, Any]) -> None:
        base = max(float(self.p.direct_day_switch_retry_interval or 0.0), 0.0)
        delay = base * min(2 ** resolution["attempts"], _SETTLEMENT_BACKOFF_FACTOR_MAX)
        with self._direct_day_switch_lock:
            self._direct_settlement_request = resolution["trading_day"]
            self._direct_settlement_due = time.monotonic() + delay

    def _direct_end_settlement_resolution(
        self, resolution: Dict[str, Any], status: str, reason: Optional[str] = None
    ) -> None:
        resolution["status"] = status
        if reason is not None:
            resolution["last_result"] = reason
        resolution["updated_at_utc"] = _utc_text()
        if self._direct_settlement is resolution:
            with self._direct_day_switch_lock:
                self._direct_settlement_request = None
        if status == "resolved":
            if self._direct_global_block == "settlement_unconfirmed":
                self._direct_global_block = None
            _log.info(
                "direct settlement of %s verified after %d attempt(s): %s",
                resolution["trading_day"],
                resolution["attempts"],
                resolution["last_result"],
            )
        elif status == "manual_required":
            _log.warning(
                "direct settlement of %s still unverified after %d attempt(s) (%s): writes "
                "stay blocked, manual resolution required",
                resolution["trading_day"],
                resolution["attempts"],
                resolution["last_result"],
            )

    def _direct_close_settlement_marker(
        self, marker_id: str, day: str, generation: int, outcome: str
    ) -> bool:
        """Audited live_state close of one marker by a readback; never after ``stop()`` began.

        Checked under the F3 write gate, so no marker changes once ``stop()``
        set ``_direct_stopping`` (it writes the final snapshot and releases
        the run lock afterwards).
        """
        with self._direct_write_gate:
            if self._direct_stopping:
                return False
            return self._direct_state.pending.resolve_settlement_readback(
                marker_id,
                exchange_name=self._direct_exchange,
                trading_day=day,
                session_generation=generation,
                outcome=outcome,
            )

    def _direct_settlement_attempt(
        self, day: str, settle, *, generation: Optional[int] = None
    ) -> Dict[str, Any]:
        """One resolution attempt (facts poller, or startup); no Broker state changes.

        ``settle`` runs the SDK settlement step (``_direct_settle_call`` at
        startup, the stop-fenced ``_direct_poller_settle`` on the poller);
        ``generation`` additionally pins the session generation (startup:
        the reconciled one).  Marker transitions are audited live_state
        operations and never run once ``stop()`` began.
        """
        payload: Dict[str, Any] = {
            "day": day,
            "result": None,
            "markers": [],
            "resolved": [],
            "closed": [],
            "settlement": None,
        }
        if self._direct_stopping:
            payload["result"] = "broker_stopping"
            return payload
        try:
            markers = self._direct_resolvable_settlement_markers(day)
            payload["markers"] = [marker["marker_id"] for marker in markers]
            session = self._direct_session_probe()
            if (
                type(session[0]) is not int
                or session[1] != day
                or day != self._direct_trading_day
                or (generation is not None and session[0] != generation)
            ):
                payload["result"] = "session_unverified"
                return payload
            if self._direct_account_reference() != self._direct_account_hash:
                payload["result"] = "account_unverified"
                return payload
            if not markers:
                # Proven unconfirmed earlier and no confirmation outstanding (the
                # last one committed nothing): the SDK step reads first again.
                payload["result"] = "confirm"
            else:
                provider = self._direct_api.direct_writes().provider(self._direct_exchange)
                reader = getattr(provider, "settlement_status", None)
                if not callable(reader):
                    payload["result"] = "readback_unavailable"
                    return payload
                status = reader()
                payload["result"] = str(getattr(status, "value", status))
                if self._direct_session_probe() != session:
                    payload["result"] = "session_changed"
                    return payload
            if self._direct_stopping:
                # stop() began during the read: nothing changes (the marker
                # transitions are also fenced); the next start reads again.
                payload["result"] = "broker_stopping"
                return payload
            if payload["result"] == "confirmed":
                for marker_id in payload["markers"]:
                    if self._direct_close_settlement_marker(
                        marker_id, day, session[0], "confirmed"
                    ):
                        payload["resolved"].append(marker_id)
                return payload
            if payload["result"] not in ("unconfirmed", "confirm"):
                return payload
            if not self._direct_writes_enabled:
                payload["result"] = "write_admission_disabled"
                return payload
            for marker_id in payload["markers"]:
                if self._direct_close_settlement_marker(marker_id, day, session[0], "unconfirmed"):
                    payload["closed"].append(marker_id)
            if len(payload["closed"]) != len(payload["markers"]):
                payload["result"] = "close_failed"
                return payload
            # D62-29: not a blind retry, the readback proved the earlier
            # confirmation absent (CTP's confirmation is idempotent per day).
            outcome = settle()
            if outcome is None:
                payload["result"] = "broker_stopping"
            payload["settlement"] = outcome
        except Exception as exc:
            payload["result"] = f"readback_failed:{type(exc).__name__}"
        return payload

    def _direct_apply_settlement_attempt(self, payload: Dict[str, Any]) -> None:
        """Strategy thread (or startup): record one resolution attempt and decide."""
        with self._direct_day_switch_lock:
            self._direct_settlement_inflight = False
        outcome = payload.get("settlement")
        resolution = self._direct_settlement
        if (
            resolution is None
            or resolution["status"] != "pending"
            or resolution["trading_day"] != payload.get("day")
        ):
            if outcome:  # stale attempt: a confirmation it committed is still recorded
                self._direct_day_switch_settlement(outcome)
            return
        resolution["attempts"] += 1
        resolution["last_result"] = payload["result"]
        resolution["updated_at_utc"] = _utc_text()
        entries = self._direct_report.setdefault("settlement_readbacks", [])
        for marker_id in payload["markers"]:
            entries.append(
                {
                    "marker_id": marker_id,
                    "trading_day": payload["day"],
                    "status": payload["result"],
                    "resolved": marker_id in payload["resolved"],
                }
            )
        del entries[:-_MAX_SETTLEMENT_READBACK_ENTRIES]
        kind = None
        if outcome:
            resolution["reconfirmations"] += 1
            kind = self._direct_day_switch_settlement(outcome)
            resolution["last_settlement"] = kind
        day = resolution["trading_day"]
        if (payload["result"] == "confirmed" or kind == "confirmed") and not (
            self._direct_resolvable_settlement_markers(day)
        ):
            self._direct_end_settlement_resolution(resolution, "resolved")
            return
        if payload["result"] in _SETTLEMENT_MANUAL_RESULTS:
            self._direct_end_settlement_resolution(resolution, "manual_required")
            return
        if resolution["attempts"] >= resolution["max_attempts"]:
            self._direct_end_settlement_resolution(resolution, "manual_required")
            return
        if payload["result"] != "broker_stopping":
            _log.warning(
                "direct settlement of %s not verified yet (attempt %d/%d: %s%s); writes "
                "blocked, retrying",
                day,
                resolution["attempts"],
                resolution["max_attempts"],
                payload["result"],
                f", confirmation {kind}" if kind else "",
            )
        self._direct_schedule_settlement_attempt(resolution)

    def _direct_settlement_poll(self) -> bool:
        """Facts poller: run one due resolution attempt (not re-entrant); True if it ran."""
        with self._direct_day_switch_lock:
            day = self._direct_settlement_request
            if (
                day is None
                or self._direct_settlement_inflight
                or time.monotonic() < self._direct_settlement_due
            ):
                return False
            self._direct_settlement_inflight = True
        payload = self._direct_settlement_attempt(day, self._direct_poller_settle)
        # Publish before counting: whoever sees the count finds the payload.
        self._direct_facts_results.append(("settlement_resolution", payload))
        self._direct_refresh_counts["settlement_resolution"] += 1
        return True

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
        """Startup settlement step under admission (D62-20/29): read first, then decide.

        An unclear confirmation of today (an earlier run or switch) gets its
        first resolution attempt now, before the Broker reports started, and
        never a second confirmation while its outcome is unclear.  Otherwise
        the SDK step runs; its unclear outcome leaves the marker UNKNOWN and
        starts the resolution loop.
        """
        day = self._direct_trading_day
        if self._direct_resolvable_settlement_markers(day):
            resolution = self._direct_begin_settlement_resolution(day, "restart", schedule=False)
            if resolution is not None and resolution["status"] == "pending":
                payload = self._direct_settlement_attempt(
                    day, self._direct_settle_call, generation=self._direct_session_generation
                )
                self._direct_apply_settlement_attempt(payload)
            return
        outcome = self._direct_settle_call()
        if outcome is None:
            return
        kind = self._direct_day_switch_settlement(outcome)
        if kind == "unverified":
            # Nothing was committed, hence nothing sent: blocked for this run.
            if self._direct_global_block not in _DAY_SWITCH_TERMINAL_BLOCKS:
                self._direct_global_block = "settlement_unconfirmed"
            _log.warning(
                "direct settlement not confirmed: %s", outcome["error"] or outcome["value"]
            )

    def _direct_settle_call(self) -> Optional[Dict[str, Any]]:
        """One SDK settlement step (read first, confirm under admission); no Broker state.

        ``None`` when writes are disabled (nothing to confirm).  Otherwise the
        status ``value``, the exception type as ``error`` and the marker id of
        a confirmation the SDK committed through the host port.
        """
        if not self._direct_writes_enabled:
            return None
        port = _StopFencedPort(self._direct_state.pending.bind(), self)
        try:
            status = self._direct_api.ensure_settlement_confirmed(
                self._direct_exchange, pre_dispatch_commit=port, host_scope=self._direct_uuid
            )
        except Exception as exc:
            return {
                "value": None,
                "error": type(exc).__name__,
                "marker_id": getattr(port, "last_marker_id", None),
            }
        return {
            "value": getattr(status, "value", status),
            "error": None,
            "marker_id": getattr(port, "last_marker_id", None),
        }

    # ------------------------------------------------------------------
    # trading-permission facts (D62-25, N-1/2, 62.03)
    # ------------------------------------------------------------------
    def _direct_read_permissions(self) -> None:
        """Read the strategy instruments' trading-permission facts once.

        Only on routes that send an explicit offset (CTP); facades or
        providers without the read leave the Broker unchanged.  The SDK/
        provider own the facts; the Broker keeps only the definitive
        negatives of a complete result for :meth:`_direct_precheck` and a
        bounded, value-free summary under ``report["permissions"]``.  Unknown
        or incomplete facts never refuse an order (the venue stays
        authoritative), and they are never treated as a permission either.
        The BT ``net``/``dual_side`` projection plays no part here.
        """
        self._direct_permissions = None
        self._direct_permission_denials = {}
        if not self._direct_require_offset or not self.p.direct_permission_check:
            return
        reader = getattr(self._direct_api, "direct_trading_permissions", None)
        if not callable(reader):
            return
        symbols = sorted(str(name) for name in (getattr(self.store, "_sdk_routes", None) or {}))
        if not symbols:
            return
        venues = {
            symbol: self._direct_symbol_venue[symbol]
            for symbol in symbols
            if self._direct_symbol_venue.get(symbol)
        }
        try:
            facts = reader(
                self._direct_exchange,
                symbols,
                exchange_ids=venues or None,
                timeout=float(self.p.direct_permission_timeout),
                max_duration=float(self.p.direct_permission_max_duration),
            )
        except Exception as exc:
            code = str(getattr(exc, "code", None) or type(exc).__name__)[:80]
            if code != "capability_not_supported":
                self._direct_report["permissions"] = {"status": "read_failed", "reason": code}
                _log.warning("direct trading-permission read failed: %s", code)
            return
        try:
            report = self._direct_permission_report(facts)
            denials: Dict[str, str] = {}
            if facts.complete is True and facts.session_consistent is True:
                for entry in facts.instruments:
                    reasons = tuple(entry.denial_reasons or ())
                    if entry.outcome == "known_negative" and reasons:
                        denials[str(entry.symbol)] = str(reasons[0])
        except Exception as exc:  # an unreadable result proves nothing
            self._direct_report["permissions"] = {
                "status": "unreadable",
                "reason": type(exc).__name__,
            }
            return
        self._direct_permissions = facts
        self._direct_permission_denials = denials
        self._direct_report["permissions"] = report
        for symbol, reason in sorted(denials.items()):
            _log.warning("direct orders for %s will be refused: %s", symbol, reason)

    @staticmethod
    def _direct_permission_report(facts: Any) -> Dict[str, Any]:
        instruments: Dict[str, Any] = {}
        for entry in tuple(facts.instruments)[:_MAX_PERMISSION_REPORT_SYMBOLS]:
            instruments[str(entry.symbol)] = {
                "venue": entry.venue,
                "outcome": str(entry.outcome),
                "denial_reasons": [str(reason) for reason in entry.denial_reasons][:5],
                "facts": {str(fact.name): f"{fact.status}:{fact.reason}" for fact in entry.facts},
                "trading_code_kinds": [
                    str(kind) for kind in getattr(entry, "trading_code_kinds", ())
                ][:5],
            }
        return {
            "status": "complete" if facts.complete is True else "incomplete",
            "current": True,
            "trading_day": facts.trading_day,
            "session_generation": facts.session_generation,
            "native_queries": int(getattr(facts, "native_queries", 0) or 0),
            # Codes only: the bracketed native detail is dropped.
            "blockers": [str(item).split("[", 1)[0] for item in facts.blockers][:8],
            "proves_permission": False,
            "instruments": instruments,
        }

    def _direct_permissions_current(self) -> bool:
        """The stored facts belong to the provider's current session and day."""
        facts = self._direct_permissions
        if facts is None:
            return False
        try:
            provider = self._direct_api.direct_writes().provider(self._direct_exchange)
            generation = provider.session_generation()
            trading_day = provider.trading_day()
        except Exception:
            return False
        return (
            generation is not None
            and generation == facts.session_generation
            and trading_day is not None
            and str(trading_day) == str(facts.trading_day)
        )

    def _direct_permission_denial(self, symbol: str) -> Optional[str]:
        """A definitive negative for ``symbol`` that still applies, else ``None``."""
        reason = self._direct_permission_denials.get(symbol)
        if reason is None:
            return None
        if not self._direct_permissions_current():
            # Facts of another session or trading day are unknown now (D62-25).
            self._direct_permission_denials = {}
            report = self._direct_report.get("permissions")
            if isinstance(report, dict):
                report["current"] = False
            _log.info("direct trading-permission facts expired with their session")
            return None
        return reason

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
        if getattr(self, "_direct_day_switch", None) is not None:
            blocked.setdefault("*", "trading_day_switch_pending")
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
            reason = self._direct_precheck(order, meta, switch_may_wait=True)
            if reason is not None:
                return self._direct_reject(order, reason)
            route = self._direct_route(order)
            if route == "wait":
                # D62-30: a trusted closure keeps the order local and durable,
                # also during a pending switch (the queue is held until then).
                return self._direct_enqueue_waiting(order, meta)
            if self._direct_day_switch is not None:
                return self._direct_reject(order, "trading_day_switch_pending")
            if route != "dispatch":
                return self._direct_reject(order, route)
            return self._direct_dispatch(order, meta)

    def _direct_precheck(
        self, order: Order, meta: Dict[str, Any], *, switch_may_wait: bool = False
    ) -> Optional[str]:
        if self._direct_stopping:
            return "broker_stopping"
        if not self._direct_writes_enabled:
            return "write_admission_disabled"
        # R-3: a provider trading day other than the reconciled one freezes
        # every new venue write of the route until the new day is re-verified;
        # ``switch_may_wait`` leaves the decision to the route (D62-30 wait).
        switching = self._direct_day_switch_active()
        if self._direct_global_block:
            return self._direct_global_block
        if "*" in self._direct_blocked:
            return self._direct_blocked["*"]
        if switching and not switch_may_wait:
            return "trading_day_switch_pending"
        if self._direct_restored and self._direct_strategy is None:
            return "restored_orders_not_taken_over"
        if self._direct_strategy is None and order.owner is not None:
            self._direct_strategy = order.owner  # one strategy per directory
        symbol = meta["symbol"]
        if symbol in self._direct_blocked:
            return self._direct_blocked[symbol]
        denial = self._direct_permission_denial(symbol)
        if denial is not None:
            return f"trading_permission_denied:{denial}"
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
        qualify = _trade_qualification_reader(data)
        if qualify is None:
            # No BtApiFeed trade-qualification contract (e.g. a placeholder
            # data object of a strategy): nothing proves LIVE status or clock
            # quality, now or at a later dispatch, so nothing is sent unchecked.
            return "target_data_unqualified"
        qualification = qualify()
        reasons = tuple(getattr(qualification, "reasons", ()) or ())
        phase = self._direct_phase(self._direct_symbol(data))
        if phase is not None and not phase.reason and phase.phase.value in ("closed", "auction"):
            # D62-30 / 5.3c: a real-time feed during a trusted closure creates a
            # durable waiting order; no fresh quote or LIVE status is required
            # now (both are rechecked before the actual dispatch).
            return "wait" if self.p.waiting_orders else "market_closed"
        if qualification is None:
            return "target_data_unqualified"
        if "FEED_NOT_LIVE" in reasons:
            # D62-15a/15b: target not LIVE
            return self._direct_note_refusal(order, "target_feed_not_live", reasons)
        if not getattr(qualification, "ok", False):
            # Decision 6: the main cause only; the prefix stays for log consumers.
            code = "target_data_not_tradable:" + main_refusal_reason(reasons)
            return self._direct_note_refusal(order, code, reasons)
        return "dispatch"

    def _direct_note_refusal(self, order: Order, code: str, reasons: tuple) -> str:
        """Keep every reason of a target-data refusal on the order and in the log."""
        reasons = tuple(str(reason) for reason in reasons)
        order.addinfo(refusal_reasons=reasons)
        throttled_warning(
            _log,
            "direct_order_refused:" + code,
            "direct order refused for %s: %s (all reasons: %s)",
            self._direct_symbol(order.data),
            code,
            ",".join(reasons) or "-",
            exc_info=False,
        )
        return code

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
        message = f"direct mode refused the order: {reason}"
        reasons = order.info.get("refusal_reasons")
        if reasons and (
            reason == "target_feed_not_live" or reason.startswith("target_data_not_tradable:")
        ):
            message += " (all reasons: " + ",".join(reasons) + ")"
        self._reject_order(order, reason, message)
        return order

    def _direct_dispatch(self, order: Order, meta: Dict[str, Any]) -> Order:
        try:
            request = self._direct_request(order, meta)
        except (TypeError, ValueError, ArithmeticError) as exc:
            # The SDK request DTO refused a field: a local refusal, never an
            # exception into strategy code; nothing was reserved or sent.
            # ``ArithmeticError`` covers ``decimal.InvalidOperation``: a price
            # ``float()`` accepts whose text is no decimal literal (e.g. a
            # one-element numpy array) fails the ``Decimal`` conversion.
            detail = str(exc)[:80] or type(exc).__name__
            return self._direct_reject(order, f"request_unrepresentable:{detail}")
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
            keys = identity_keys(fields, outcome.identity.client_order_id)
            self._direct_index_order(keys, order.ref, fields.get("trading_day"))
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
        used until the venue itself reports one (account position facts
        overwrite it; order identities and trades only fill a missing venue,
        since their exchange id echoes the request), so an order never waits for the provider's
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
            refusal = self._direct_cancel_refusal(meta)
            if refusal is not None:
                order.addinfo(cancel_error=refusal)
                _log.warning("direct cancel of %s refused: %s", order.ref, refusal)
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

    def _direct_cancel_refusal(self, meta: Dict[str, Any]) -> Optional[str]:
        """Why a venue cancel of this order takes no automatic write (R-3), else ``None``.

        CTP session and venue order ids are unique within one trading day
        only and may be reused on a later day's session.  An unresolved order
        of a previous day (``day_unknown``, after a switch was applied) is
        refused; so is, while a switch is pending, an order whose identity's
        trading day is not the provider session's current one (unreadable
        days prove nothing either).  Same-day orders and routes without venue
        offsets (no switch state) are unaffected.
        """
        if meta.get("day_unknown"):
            return "previous_day_pending_unknown"
        if not self._direct_require_offset or not self._direct_day_switch_active():
            return None
        identity = meta.get("identity")
        own_day = dict(identity.fields).get("trading_day") if identity is not None else None
        try:
            _generation, provider_day = self._direct_session_probe()
        except Exception:
            provider_day = None
        own_day = None if own_day is None else str(own_day)
        if provider_day is None or not _valid_trading_day(own_day):
            return "trading_day_switch_pending"
        if own_day != provider_day:
            return "previous_day_pending_unknown"
        return None

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
            items = ()
        for item in items:
            try:
                self._direct_process_event(item.event)
            except Exception:
                _log.exception("direct event projection failed")
        if self._direct_trade_buffer:
            # The poll's order returns may have taught the venue order id of a
            # held fill: re-match first, then release what is past its window.
            self._direct_expire_buffered_trades()

    def _direct_event_keys(self, event: Any) -> tuple:
        """``(fields, keys)`` of a return: identity keys plus its venue order id."""
        identity = event.identity
        fields = dict(identity.fields)
        keys = identity_keys(fields, identity.client_order_id)
        if event.exchange_order_id and fields.get("exchange_id"):
            keys.append(("x", str(fields["exchange_id"]), str(event.exchange_order_id)))
        return fields, keys

    def _direct_day_keys(self, keys: List[tuple], day: Any) -> List[tuple]:
        """Index entries binding the day-scoped ``keys`` to trading day ``day`` (R-3).

        On routes with explicit offsets (CTP) the session triple and
        ``ExchangeID``/``OrderSysID`` restart every trading day: the entry
        ``("d", day, *key)`` keeps own orders of different days with reused
        ids apart.  Client order ids, unknown days and routes without offsets
        (OKX/Binance) have none; they use the plain key only.
        """
        if not self._direct_require_offset or not day:
            return []
        return [("d", str(day)) + key for key in keys if key[0] != "c"]

    def _direct_index_order(
        self, keys: List[tuple], ref: int, day: Any, *, replace: bool = True
    ) -> None:
        """Index ``ref`` under ``keys`` and their day-bound entries (same write mode)."""
        for key in list(keys) + self._direct_day_keys(keys, day):
            if replace:
                self._direct_index[key] = ref
            else:
                self._direct_index.setdefault(key, ref)

    def _direct_order_day(self, ref: Optional[int]) -> Optional[str]:
        """Trading day of an own order's native identity, if known."""
        meta = self._direct_meta.get(ref) if ref is not None else None
        identity = meta.get("identity") if meta is not None else None
        day = dict(identity.fields).get("trading_day") if identity is not None else None
        return str(day) if day else None

    def _direct_order_for_event(self, event: Any) -> Optional[Order]:
        if event.identity is None:
            return None
        fields, keys = self._direct_event_keys(event)
        # R-3: a return of a known trading day resolves to the own order of
        # that day; the plain keys below never bind a known other day.
        for key in self._direct_day_keys(keys, fields.get("trading_day")):
            ref = self._direct_index.get(key)
            if ref is not None:
                return self.orders.get(ref)
        for key in keys:
            ref = self._direct_index.get(key)
            if ref is not None and self._direct_same_trading_day(ref, key, fields):
                return self.orders.get(ref)
        return None

    def _direct_note_other_day_return(self, event: Any) -> None:
        """R-3: a day-scoped return that names only an own order of another day.

        The venue reused the ids on a new day, so it is not booked there.
        Like any return without an own order of its day it stays unmatched
        (a fill is first held for ``direct_trade_match_window`` in case its
        order return follows), but it is never silent: it is counted under
        ``other_day_returns`` in the reconcile report and logged.
        """
        if not self._direct_require_offset or event.identity is None:
            return
        fields, keys = self._direct_event_keys(event)
        day = fields.get("trading_day")
        if not day:
            return
        for key in keys:
            ref = self._direct_index.get(key) if key[0] != "c" else None
            own_day = self._direct_order_day(ref)
            if own_day is not None and own_day != str(day):
                break
        else:
            return
        entry = self._direct_report.setdefault("other_day_returns", {"count": 0, "last": None})
        entry["count"] += 1
        entry["last"] = {
            "kind": event.kind.value,
            "symbol": event.symbol,
            "exchange_order_id": event.exchange_order_id,
            "trade_id": getattr(event, "trade_id", None),
            "trading_day": str(day),
            "order_trading_day": own_day,
            "order_local_seq": (self._direct_meta.get(ref) or {}).get("local_seq"),
        }
        throttled_warning(
            _log,
            "direct_other_day_return",
            "direct %s return of trading day %s names only an own order of %s "
            "(ids reused by the venue): not booked",
            event.kind.value,
            day,
            own_day,
            exc_info=False,
        )

    def _direct_same_trading_day(self, ref: int, key: tuple, fields: Dict[str, Any]) -> bool:
        """A day-scoped key matches only an order of the same trading day (R-3).

        CTP ``FrontID``/``SessionID``/``OrderRef`` and ``ExchangeID``/
        ``OrderSysID`` are unique within one trading day only; a return of a
        later day carrying a reused value is another order.  Client order ids
        (``c`` keys) are not day-scoped.  Unknown days keep the match.  Routes
        without venue offsets (OKX/Binance GTC orders span UTC days) never
        bind a match to the day.
        """
        if key[0] == "c" or not self._direct_require_offset:
            return True
        event_day = fields.get("trading_day")
        meta = self._direct_meta.get(ref)
        identity = meta.get("identity") if meta is not None else None
        own_day = dict(identity.fields).get("trading_day") if identity is not None else None
        return not (event_day and own_day and str(event_day) != str(own_day))

    def _direct_process_event(self, event: Any) -> None:
        order = self._direct_order_for_event(event)
        if order is None:
            if event.kind.value == "trade":
                # Possibly ahead of its order return: re-matched for a short
                # window, then not ours (decision 8).
                self._direct_buffer_trade(event)
                return
            self._direct_note_other_day_return(event)
            return  # another client's order: visible to audits, never adopted
        self._direct_process_matched(order, event)

    # ------------------------------------------------------------------
    # trade returns ahead of their order return (decision 8, 2026-11-06)
    # ------------------------------------------------------------------
    def _direct_trade_buffer_stats(self) -> Dict[str, Any]:
        return self._direct_report.setdefault(
            "trade_match_buffer", {"buffered": 0, "matched_late": 0, "expired": 0, "pending": 0}
        )

    def _direct_buffer_trade(self, event: Any) -> None:
        """Hold one unmatched trade return; bounded, de-duplicated by trade key."""
        if event.identity is None:
            self._direct_unmatched_trade(event, "no_identity")
            return
        day = getattr(event, "trading_day", None) or dict(event.identity.fields).get("trading_day")
        trade_key = self._direct_trade_key(event)
        key = (str(day or ""), trade_key)
        if key in self._direct_trade_buffer or trade_key in self._direct_applied_set():
            return  # a repeated return of a held or already applied fill
        while len(self._direct_trade_buffer) >= _MAX_BUFFERED_TRADES:
            _old_key, entry = self._direct_trade_buffer.popitem(last=False)
            self._direct_unmatched_trade(entry["event"], "buffer_full")
        window = float(self.p.direct_trade_match_window)
        self._direct_trade_buffer[key] = {"event": event, "deadline": _monotonic() + window}
        stats = self._direct_trade_buffer_stats()
        stats["buffered"] += 1
        stats["pending"] = len(self._direct_trade_buffer)

    def _direct_retry_buffered_trades(self) -> None:
        """Apply every held trade that now matches an own order (exactly once)."""
        for key in list(self._direct_trade_buffer):
            entry = self._direct_trade_buffer.get(key)
            if entry is None:
                continue
            order = self._direct_order_for_event(entry["event"])
            if order is None:
                continue
            del self._direct_trade_buffer[key]
            stats = self._direct_trade_buffer_stats()
            stats["matched_late"] += 1
            stats["pending"] = len(self._direct_trade_buffer)
            self._direct_process_matched(order, entry["event"])

    def _direct_expire_buffered_trades(self, *, reason: Optional[str] = None) -> None:
        """Retry, then release held trades past their window (all, with ``reason``)."""
        if reason is None:
            self._direct_retry_buffered_trades()
        now = _monotonic()
        for key in list(self._direct_trade_buffer):
            entry = self._direct_trade_buffer[key]
            if reason is not None or entry["deadline"] <= now:
                del self._direct_trade_buffer[key]
                self._direct_unmatched_trade(entry["event"], reason or "window_expired")

    def _direct_unmatched_trade(self, event: Any, reason: str) -> None:
        """Today's handling of a fill that is not ours, now counted and logged."""
        self._direct_note_other_day_return(event)
        stats = self._direct_trade_buffer_stats()
        if reason != "no_identity":
            stats["expired"] += 1
        stats["pending"] = len(self._direct_trade_buffer)
        entry = self._direct_report.setdefault(
            "unmatched_trade_returns", {"count": 0, "reasons": {}, "last": None}
        )
        entry["count"] += 1
        entry["reasons"][reason] = entry["reasons"].get(reason, 0) + 1
        entry["last"] = {
            "symbol": event.symbol,
            "trade_id": getattr(event, "trade_id", None),
            "exchange_order_id": event.exchange_order_id,
            "trading_day": getattr(event, "trading_day", None),
            "reason": reason,
        }
        throttled_warning(
            _log,
            "direct_unmatched_trade_return",
            "direct trade return on %s matched no own order (%s): not booked",
            event.symbol,
            reason,
            exc_info=False,
        )

    def _direct_process_matched(self, order: Order, event: Any) -> None:
        """Project one return identity-matched to an own order."""
        meta = self._direct_meta[order.ref]
        fields = dict(event.identity.fields) if event.identity is not None else {}
        if event.exchange_order_id and fields.get("exchange_id"):
            key = ("x", str(fields["exchange_id"]), str(event.exchange_order_id))
            day = self._direct_order_day(order.ref)
            self._direct_index_order([key], order.ref, day, replace=False)
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
            if self._direct_day_switch_active():
                return  # R-3: hold the FIFO queue (not rejected) until the new day is verified
            phase = self._direct_phase(meta["symbol"], now)
            if phase is None or phase.reason or phase.phase.value != "continuous":
                return  # auction / unknown: no dispatch (D62-34)
            qualify = _trade_qualification_reader(order.data)
            qualification = qualify() if qualify is not None else None
            if qualification is None or not getattr(qualification, "ok", False):
                # Wait for qualified real-time data in the target session; a
                # missing qualification is never treated as qualified.
                return
            reason = self._direct_precheck(order, meta)
            if reason == "trading_day_switch_pending":
                return  # R-3: a switch detected just now holds the FIFO queue too
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
            if self._direct_day_switch_request is not None:
                # R-3: the switch verification replaces funds/audit reads (one
                # query stream per session) until the switch is applied.
                try:
                    self._direct_day_switch_poll()
                except Exception as exc:
                    self._direct_refresh_counts["failed"] += 1
                    _log.warning("direct day-switch reads failed: %s", type(exc).__name__)
                continue
            if self._direct_settlement_request is not None:
                # D62-29: a due resolution attempt of an unclear settlement
                # confirmation replaces this round's funds/audit reads.
                try:
                    if self._direct_settlement_poll():
                        continue
                except Exception as exc:
                    self._direct_refresh_counts["failed"] += 1
                    _log.warning("direct settlement resolution failed: %s", type(exc).__name__)
                    continue
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
            if kind == "day_switch":
                self._direct_apply_day_switch(facts)
                continue
            if kind == "settlement_resolution":
                self._direct_apply_settlement_attempt(facts)
                continue
            self._direct_apply_balance(facts.balance)
            if self._direct_require_offset:
                self._direct_note_trading_day(facts.trading_day, kind)
                if self._direct_day_switch is not None:
                    continue  # R-3: the switch reconciliation replaces this audit
            if kind == "audit" and facts.positions is not None and facts.active_orders is not None:
                self._direct_audit(facts)

    def _direct_audit(self, facts: Any) -> None:
        if (
            not self._direct_require_offset
            and facts.trading_day
            and facts.trading_day != self._direct_trading_day
        ):
            # Routes without venue offsets (OKX/Binance: the UTC date; GTC
            # orders span days) only adopt the new day; R-3 is CTP-style only.
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
    # trading-day switch while running (R-3; D62-14/22/29), CTP-style
    # routes only (``_direct_require_offset``)
    # ------------------------------------------------------------------
    # State machine (strategy thread owns ``_direct_day_switch``):
    #   entry   a trusted provider trading day (facts read or the provider
    #           session) other than the reconciled one -> new orders refused
    #           ``trading_day_switch_pending``; returns, own cancels and the
    #           waiting-order expiry keep running, the waiting queue is held;
    #   verify  facts poller: session + trading day, account reference, one
    #           complete account observation of the new day, the new day's
    #           settlement via the SDK (D62-29), session again;
    #   apply   strategy thread: settlement result, old-day pending markers
    #           (verified working/terminal or UNKNOWN + instrument block),
    #           positions with the venue's today/yesterday split, foreign
    #           orders, applied trades, then the new day and one snapshot;
    #   exit    only after an attempt verified everything; transient failures
    #           keep the freeze and retry, terminal ones keep a global block.
    def _direct_session_probe(self) -> tuple:
        """``(session generation, trading day)`` of the provider session (local reads)."""
        provider = self._direct_api.direct_writes().provider(self._direct_exchange)
        read_generation = getattr(provider, "session_generation", None)
        read_day = getattr(provider, "trading_day", None)
        generation = read_generation() if callable(read_generation) else None
        day = read_day() if callable(read_day) else None
        return (
            generation if type(generation) is int else None,
            day if _valid_trading_day(day) else None,
        )

    def _direct_day_switch_active(self) -> bool:
        """A switch is pending; a provider session day other than ours starts one.

        Only routes that send an explicit offset (CTP) probe the provider day.
        """
        if self._direct_day_switch is None and self._direct_on and self._direct_require_offset:
            try:
                _generation, day = self._direct_session_probe()
            except Exception:
                day = None  # an unreadable session proves no change
            if day is not None:
                self._direct_note_trading_day(day, "provider_session")
        return self._direct_day_switch is not None

    def _direct_note_trading_day(self, day: Any, source: str) -> None:
        """Enter (or retarget) the switch when a trusted provider day differs."""
        if not self._direct_require_offset:
            return  # R-3 applies to CTP-style routes only (see ``_direct_audit``)
        current = self._direct_trading_day
        if not _valid_trading_day(current) or not _valid_trading_day(day):
            return
        if self._direct_global_block in _DAY_SWITCH_TERMINAL_BLOCKS:
            return  # already refused for good; an operator restart reconciles
        switch = self._direct_day_switch
        if switch is None:
            if day != current:
                self._direct_enter_day_switch(day, source)
            return
        if day < current:
            self._direct_global_block = "trading_day_regressed"
            self._direct_finish_day_switch(switch, "failed", "trading_day_regressed")
            return
        if day not in (switch["to_trading_day"], switch["from_trading_day"]):
            # A further change before the first was verified: verify the newest.
            _log.warning(
                "direct trading-day switch retargeted %s -> %s (%s)",
                switch["to_trading_day"],
                day,
                source,
            )
            switch["to_trading_day"] = day
            switch["retargeted"] += 1
            self._direct_request_day_switch(day, settle=True)

    def _direct_enter_day_switch(self, day: str, source: str) -> None:
        current = self._direct_trading_day
        switch: Dict[str, Any] = {
            "status": "pending",
            "from_trading_day": current,
            "to_trading_day": day,
            "detected_by": source,
            "detected_at_utc": _utc_text(),
            "attempts": 0,
            "retargeted": 0,
            "last_reason": None,
            "session_generation": None,
            "reconnected": None,
            "settlement": None,
            "verified_markers": [],
            "resolved_markers": [],
            "superseded_markers": [],
            "unknown_markers": [],
            "mismatches": [],
            "unverified_positions": [],
            "split_sources": {},
            "calendar": {},
            "blocked": {},
            "completed_at_utc": None,
        }
        self._direct_report["trading_day_switch"] = switch
        if day < current:
            # The venue day never moves backwards in a normal switch.
            self._direct_global_block = "trading_day_regressed"
            switch.update(status="failed", last_reason="trading_day_regressed")
            switch["blocked"] = {"*": "trading_day_regressed"}
            _log.error("direct trading day regressed %s -> %s: writes blocked", current, day)
            return
        self._direct_day_switch = switch
        self._direct_request_day_switch(day, settle=True)
        _log.warning(
            "direct trading-day switch %s -> %s detected (%s): new orders frozen "
            "until the new day is re-verified",
            current,
            day,
            source,
        )

    def _direct_request_day_switch(self, day: Optional[str], *, settle: bool = True) -> None:
        with self._direct_day_switch_lock:
            self._direct_day_switch_request = None if day is None else (day, bool(settle))
            self._direct_day_switch_due = 0.0

    def _direct_day_switch_poll(self) -> None:
        """Facts poller: run one verification attempt when one is due (not re-entrant)."""
        with self._direct_day_switch_lock:
            request = self._direct_day_switch_request
            if (
                request is None
                or self._direct_day_switch_inflight
                or time.monotonic() < self._direct_day_switch_due
            ):
                return
            self._direct_day_switch_inflight = True
        target, settle = request
        payload = self._direct_day_switch_reads(target, settle=settle)
        # Publish before counting: whoever sees the count finds the payload.
        self._direct_facts_results.append(("day_switch", payload))
        self._direct_refresh_counts["day_switch"] += 1

    def _direct_day_switch_reads(self, target: str, *, settle: bool = True) -> Dict[str, Any]:
        """Verification reads of a pending switch (facts poller thread).

        Read-only except the settlement step, which runs only after account,
        trading day and session were verified (D62-29) and goes through the
        SDK (read first, confirm under admission, durable marker first).
        Nothing here changes Broker state; the strategy thread applies it.
        """
        payload: Dict[str, Any] = {
            "target": target,
            "ok": False,
            "reason": None,
            "facts": None,
            "settlement": None,
            "generation": None,
            "observed_day": None,
        }
        try:
            generation, day = self._direct_session_probe()
            payload.update(generation=generation, observed_day=day)
            if generation is None:
                payload["reason"] = "session_unavailable"
                return payload
            if day != target:
                payload["reason"] = "trading_day_unverified"
                return payload
            try:
                account_hash = self._direct_account_reference()
            except DirectModeError:
                payload["reason"] = "account_reference_unavailable"
                return payload
            if account_hash != self._direct_account_hash:
                payload["reason"] = "account_binding_mismatch"
                return payload
            facts = self._direct_read_facts(trades=True, all_orders=True)
            payload["facts"] = facts
            if not facts.complete:
                payload["reason"] = "account_facts_incomplete"
                payload["blockers"] = [
                    str(item).split("[", 1)[0] for item in (facts.blockers or ())
                ][:8]
                return payload
            if facts.trading_day != target:
                payload.update(reason="trading_day_unverified", observed_day=facts.trading_day)
                return payload
            if facts.session_generation is None or facts.session_generation != generation:
                payload["reason"] = "session_changed"
                return payload
            if settle:
                outstanding = [
                    marker
                    for marker in self._direct_state.pending.active()
                    if marker.get("operation") == "settlement_confirm"
                    and marker.get("status") == "UNKNOWN"
                    and marker.get("trading_day") == target
                    and marker.get("exchange_name") == self._direct_exchange
                ]
                if outstanding:
                    # An unclear confirmation of the new day is outstanding: no
                    # second one (D62-29); the resolution loop reads it back.
                    payload["settlement"] = {
                        "value": None,
                        "error": None,
                        "marker_id": outstanding[0]["marker_id"],
                        "outstanding": True,
                    }
                elif self._direct_writes_enabled:
                    outcome = self._direct_poller_settle()
                    if outcome is None:  # stop() began: it owns any outcome (F3)
                        payload["reason"] = "broker_stopping"
                        return payload
                    payload["settlement"] = outcome
                    if _settlement_class(outcome) == "unclear":
                        # Never repeat a confirmation that may have been sent.
                        with self._direct_day_switch_lock:
                            if self._direct_day_switch_request == (target, True):
                                self._direct_day_switch_request = (target, False)
                else:
                    payload["settlement"] = {"skipped": True}
            if self._direct_session_probe() != (generation, day):
                payload["reason"] = "session_changed"
                return payload
            payload["ok"] = True
        except Exception as exc:
            payload["reason"] = f"verification_failed:{type(exc).__name__}"
        return payload

    def _direct_day_switch_settlement(self, outcome: Dict[str, Any]) -> str:
        """Record one settlement step (marker and block); return its class.

        Used by every settlement step (startup, switch, resolution, stop).
        An ``outstanding`` step sent nothing: it found an unclear confirmation
        the resolution loop owns (marker and block already recorded).
        """
        kind = _settlement_class(outcome)
        if outcome.get("outstanding"):
            return kind
        marker = outcome.get("marker_id")
        if kind == "confirmed" and marker:
            self._direct_state.pending.mark(
                marker,
                "TERMINAL",
                final_status="confirmed",
                resolution_evidence="settlement_readback",
            )
        elif kind == "unclear":
            # D62-29: an unclear confirmation keeps its identity and is never
            # retried blindly; writes stay blocked until a readback decides.
            pending = self._direct_state.pending
            pending.mark(marker, "UNKNOWN", reason="settlement_outcome_unknown")
            if self._direct_global_block not in _DAY_SWITCH_TERMINAL_BLOCKS:
                self._direct_global_block = "settlement_unconfirmed"
            _log.warning("direct settlement outcome unclear: writes blocked")
            record = pending.get(marker)
            if record is not None and not self._direct_stopping:
                # Only an UNKNOWN marker of this route is resolved automatically.
                day = record.get("trading_day")
                if self._direct_settlement_resolvable(record, day):
                    self._direct_begin_settlement_resolution(day, "unclear_outcome")
        return kind

    def _direct_apply_day_switch(self, payload: Dict[str, Any]) -> None:
        """Strategy thread: apply one verification attempt of the pending switch."""
        retry = max(float(self.p.direct_day_switch_retry_interval or 0.0), 0.0)
        switch = self._direct_day_switch
        outcome = payload.get("settlement")
        if switch is None or payload.get("target") != switch["to_trading_day"]:
            # Stale attempt (retargeted or already finished): a settlement it
            # committed is still recorded; nothing else is applied.
            if outcome:
                self._direct_day_switch_settlement(outcome)
            with self._direct_day_switch_lock:
                self._direct_day_switch_inflight = False
            return
        switch["attempts"] += 1
        reason = payload.get("reason")
        if outcome:
            kind = self._direct_day_switch_settlement(outcome)
            if switch["settlement"] != "unclear":
                switch["settlement"] = kind
        if reason == "account_binding_mismatch":
            self._direct_global_block = "account_binding_mismatch"
            self._direct_finish_day_switch(switch, "failed", reason)
            return
        observed = payload.get("observed_day")
        if reason == "trading_day_unverified" and _valid_trading_day(observed):
            if observed < self._direct_trading_day:
                self._direct_global_block = "trading_day_regressed"
                self._direct_finish_day_switch(switch, "failed", "trading_day_regressed")
                return
            self._direct_note_trading_day(observed, "verification")
        if not payload.get("ok") or switch["settlement"] not in ("confirmed", "skipped", "unclear"):
            reason = reason or "settlement_unverified"
            if reason != switch["last_reason"]:
                _log.warning(
                    "direct trading-day switch to %s not verified yet: %s",
                    switch["to_trading_day"],
                    reason,
                )
            switch["last_reason"] = reason
            if payload.get("blockers"):
                switch["blockers"] = list(payload["blockers"])
            retargeted = switch["to_trading_day"] != payload.get("target")
            with self._direct_day_switch_lock:
                self._direct_day_switch_inflight = False
                self._direct_day_switch_due = 0.0 if retargeted else time.monotonic() + retry
            return
        self._direct_complete_day_switch(switch, payload)

    def _direct_complete_day_switch(self, switch: Dict[str, Any], payload: Dict[str, Any]) -> None:
        facts = payload["facts"]
        to_day = switch["to_trading_day"]
        generation = payload["generation"]
        switch["session_generation"] = generation
        switch["reconnected"] = (
            self._direct_session_generation is not None
            and generation != self._direct_session_generation
        )
        # Durable marker decisions first; the snapshot is written last.  A
        # crash in between restarts into the startup reconciliation, which
        # re-derives both from the venue (old-day markers -> UNKNOWN).
        self._direct_day_switch_markers(facts, to_day, switch)
        self._direct_day_switch_positions(facts, to_day, switch)
        self._direct_foreign_orders = [
            event
            for event in facts.active_orders or ()
            if event.identity is not None and self._direct_order_for_event(event) is None
        ]
        self._direct_report["foreign_working_orders"] = len(self._direct_foreign_orders)
        self._direct_day_switch_trades(facts, to_day)
        self._direct_trading_day = to_day
        self._direct_session_generation = generation
        self._direct_report["trading_day"] = to_day
        resolution = self._direct_settlement
        if (
            resolution is not None
            and resolution["status"] == "pending"
            and resolution["trading_day"] != to_day
        ):
            # Another day's unclear confirmation is never resolved automatically:
            # its UNKNOWN markers stay for manual resolution (pending_unknown).
            self._direct_end_settlement_resolution(resolution, "superseded", "trading_day_changed")
        if switch["settlement"] == "confirmed" and self._direct_global_block == (
            "settlement_unconfirmed"
        ):
            # The previous day's unconfirmed settlement is superseded by the
            # verified confirmation of the new day.
            self._direct_global_block = None
        self._direct_apply_balance(facts.balance)
        self._direct_write_snapshot()
        self._direct_last_audit = time.monotonic()
        self._direct_finish_day_switch(switch, "completed", None)

    def _direct_finish_day_switch(
        self, switch: Dict[str, Any], status: str, reason: Optional[str]
    ) -> None:
        self._direct_day_switch = None
        self._direct_request_day_switch(None)
        with self._direct_day_switch_lock:
            self._direct_day_switch_inflight = False
        switch["status"] = status
        if reason is not None:
            switch["last_reason"] = reason
        switch["completed_at_utc"] = _utc_text()
        switch["blocked"] = self.direct_writes_blocked()
        log = _log.warning if switch["blocked"] or status != "completed" else _log.info
        log(
            "direct trading-day switch %s -> %s %s: attempts=%d reconnected=%s settlement=%s "
            "unknown=%d mismatches=%d blocked=%s",
            switch["from_trading_day"],
            switch["to_trading_day"],
            status,
            switch["attempts"],
            switch["reconnected"],
            switch["settlement"],
            len(switch["unknown_markers"]),
            len(switch["mismatches"]),
            ",".join(f"{key}:{value}" for key, value in sorted(switch["blocked"].items())) or "-",
        )

    @staticmethod
    def _direct_day_bound_event(events: Any, keys: List[tuple], day: Any) -> Any:
        """The event with one of ``keys`` that belongs to trading day ``day``.

        Day-scoped keys (session triple, venue order id) need the event's own
        trading day to equal ``day``; client order ids only must not conflict.
        """
        if not day or not keys:
            return None
        wanted = set(keys)
        for event in events:
            if event.identity is None:
                continue
            fields = dict(event.identity.fields)
            matched = set(identity_keys(fields, event.identity.client_order_id)) & wanted
            if not matched:
                continue
            event_day = fields.get("trading_day") or event.trading_day
            if event_day is not None and str(event_day) != str(day):
                continue
            if event_day is None and any(key[0] != "c" for key in matched):
                continue
            return event
        return None

    def _direct_day_switch_markers(self, facts: Any, to_day: str, switch: Dict[str, Any]) -> None:
        """Old-day pending markers: verified by original identity and day, else UNKNOWN.

        A complete order list of the new day does not cover an older day:
        absence (or a GFD expiry) proves neither an end nor a non-send.
        """
        state = self._direct_state
        working = tuple(facts.active_orders or ())
        every = tuple(getattr(facts, "orders", None) or ()) + working
        by_marker = {
            meta.get("marker_id"): ref
            for ref, meta in self._direct_meta.items()
            if meta.get("marker_id")
        }
        for marker in state.pending.active():
            marker_id = marker["marker_id"]
            fields = dict(marker.get("native_identity") or {})
            day = fields.get("trading_day") or marker.get("trading_day")
            operation = marker.get("operation")
            if operation == "settlement_confirm":
                if day == to_day:
                    continue  # this switch's own settlement step
                if marker.get("status") == "UNKNOWN":
                    self._direct_blocked["*"] = "pending_unknown"
                    switch["unknown_markers"].append(marker_id)
                elif state.pending.mark(
                    marker_id,
                    "TERMINAL",
                    final_status="superseded_trading_day",
                    resolution_evidence="trading_day_switch",
                ):
                    switch["superseded_markers"].append(marker_id)
                continue
            if operation != "place" or day == to_day:
                continue  # cancels follow their order; same-day orders their returns
            symbol = str(marker.get("symbol"))
            ref = by_marker.get(marker_id)
            order = self.orders.get(ref) if ref is not None else None
            meta = self._direct_meta.get(ref) if ref is not None else None
            if marker.get("status") == "UNKNOWN":
                self._direct_blocked.setdefault(symbol, "pending_unknown")
                switch["unknown_markers"].append(marker_id)
                continue
            keys = identity_keys(fields, marker.get("client_order_id"))
            live = self._direct_day_bound_event(working, keys, day)
            if live is not None and state.pending.mark(
                marker_id,
                "ACCEPTED",
                resolution_evidence="trading_day_switch_working_order",
                **({"order_sys_id": live.exchange_order_id} if live.exchange_order_id else {}),
            ):
                switch["verified_markers"].append(marker_id)
                continue
            ended = self._direct_day_bound_event(every, keys, day)
            if (
                ended is not None
                and live is None
                and order is not None
                and meta is not None
                and order.alive()
                and self._direct_switch_terminal(order, meta, ended)
            ):
                switch["resolved_markers"].append(marker_id)
                continue
            state.pending.mark(marker_id, "UNKNOWN", reason="previous_trading_day_unresolved")
            self._direct_blocked[symbol] = "previous_day_pending_unknown"
            switch["unknown_markers"].append(marker_id)
            if meta is not None:
                meta["day_unknown"] = True
            if order is not None:
                order.addinfo(outcome_unknown=True, unresolved_trading_day=day)
            # A restore still waiting for its feed must not become a live order.
            self._direct_deferred_restore = [
                item for item in self._direct_deferred_restore if item[0]["marker_id"] != marker_id
            ]
            self._direct_awaiting_bar = [
                item
                for item in self._direct_awaiting_bar
                if not (item[0] == "restore" and item[1]["marker_id"] == marker_id)
            ]

    def _direct_switch_terminal(self, order: Order, meta: Dict[str, Any], event: Any) -> bool:
        """Project a verified terminal old-day order whose fills are all applied."""
        status = event.status.value if event.status is not None else None
        if status not in ("cancelled", "rejected"):
            return False
        if status == "rejected" and order.status not in (Order.Submitted, Order.Accepted):
            return False
        known = abs(order.executed.size) + _num(meta.get("venue_filled_before"))
        if abs(_num(event.filled_qty) - known) > 1e-9:
            return False  # fills still missing: only a trade record could prove them
        if status == "cancelled":
            order.cancel()
        else:
            order.addinfo(error_code=str(event.error_code or "venue_rejected"))
            order.reject(self)
        self.notify(order)
        self._direct_mark(
            meta,
            "TERMINAL",
            final_status=status,
            resolution_evidence="trading_day_switch_order_query",
        )
        for marker in meta.pop("cancel_markers", []):
            self._direct_state.pending.mark(marker, "TERMINAL", final_status="order_" + status)
        return True

    def _direct_calendar_check(self, symbol: str, to_day: str) -> str:
        """``match``/``mismatch`` of the venue calendar's trading day now, else ``unknown``."""
        state = self._direct_phase(symbol)
        day = getattr(state, "trading_day", None) if state is not None else None
        if state is None or getattr(state, "reason", None) or not isinstance(day, _dt.date):
            return "unknown"
        return "match" if day.strftime("%Y%m%d") == to_day else "mismatch"

    def _direct_day_switch_positions(self, facts: Any, to_day: str, switch: Dict[str, Any]) -> None:
        """New-day positions: totals per side, then the venue's today/yesterday split (D62-22).

        The venue split is authoritative when reported.  Without it the local
        conversion (everything becomes yesterday's) is used unless the venue
        calendar contradicts the new day; otherwise the split stays unknown.
        """
        venue: Dict[str, Dict[str, Any]] = {}
        for fact in facts.positions or ():
            fact = _leg_fact(fact)
            if fact is None:
                continue
            venue.setdefault(fact.symbol, {})[fact.side] = fact
            if fact.venue:
                self._direct_symbol_venue[fact.symbol] = fact.venue
        busy = {
            meta["symbol"]
            for ref, meta in self._direct_meta.items()
            if ref in self.orders and self.orders[ref].alive() and meta.get("identity") is not None
        }
        configured = {str(name) for name in (getattr(self.store, "_sdk_routes", None) or {})}
        symbols = set(self.long_positions) | set(self.short_positions) | (configured & set(venue))
        for symbol in sorted(symbols):
            split = self._direct_split_of(symbol)
            calendar = self._direct_calendar_check(symbol, to_day)
            sources: Dict[str, str] = {}
            for side in ("long", "short"):
                leg = (
                    self.long_positions[symbol] if side == "long" else self.short_positions[symbol]
                )
                local_total = abs(leg.size)
                fact = venue.get(symbol, {}).get(side)
                venue_total = fact.total if fact is not None else 0.0
                if abs(venue_total - local_total) > 1e-9:
                    split["today"][side] = None
                    split["yesterday"][side] = None
                    entry = {"symbol": symbol, "side": side, "local": local_total}
                    entry["venue"] = venue_total
                    if symbol in busy:
                        # An in-flight fill may race the read: unknown until
                        # the next audit, never adopted nor blocked here.
                        switch["unverified_positions"].append(entry)
                        sources[side] = "unknown_in_flight"
                    else:
                        switch["mismatches"].append(entry)
                        self._direct_blocked[symbol] = "trading_day_switch_position_mismatch"
                        sources[side] = "mismatch"
                    continue
                if fact is not None and (fact.today is not None or fact.yesterday is not None):
                    split["today"][side] = fact.today
                    split["yesterday"][side] = fact.yesterday
                    sources[side] = "venue"
                elif not local_total:
                    split["today"][side] = 0.0
                    split["yesterday"][side] = 0.0
                    sources[side] = "flat"
                elif calendar != "mismatch":
                    split["today"][side] = 0.0
                    split["yesterday"][side] = local_total
                    sources[side] = "local_conversion"
                else:
                    split["today"][side] = None
                    split["yesterday"][side] = None
                    sources[side] = "unknown"
            switch["split_sources"][symbol] = sources
            switch["calendar"][symbol] = calendar
            self._direct_sync_net(symbol)

    def _direct_day_switch_trades(self, facts: Any, to_day: str) -> None:
        """Keep the applied-trade keys of the new day's confirmed trades.

        Trades applied before the switch was verified were keyed under the old
        day; those the venue lists for the new day stay de-duplicated.
        """
        applied: set = set()
        for keys in self._direct_applied.values():
            applied.update(keys)
        for meta in self._direct_meta.values():
            applied.update(meta.get("trade_keys") or ())
        carried: List[str] = []
        for trade in facts.trades or ():
            key = self._direct_trade_key(trade)
            if key in applied and key not in carried:
                carried.append(key)
        self._direct_applied = {to_day: carried}

    # ------------------------------------------------------------------
    # stop (D62-19: cancel own working orders, never flatten)
    # ------------------------------------------------------------------
    def _direct_stop(self) -> Dict[str, Any]:
        if self._direct_stopping:
            return dict(self._shutdown_summary)  # already stopped: idempotent
        with self._direct_write_gate:
            # No facts-poller venue write starts from here (checked under this gate).
            self._direct_stopping = True
        self._direct_facts_stop.set()
        if not self._direct_on:
            return self._direct_stop_after_failed_start()
        started = time.monotonic()
        timeout = max(float(self.p.stop_cancel_timeout or 0.0), 0.0)
        with self._direct_lock:
            working: List[Order] = []
            # R-3: an order of another trading day than the provider's (unresolved
            # after a switch, or while one is pending) is never cancelled
            # automatically; it stays with its original identity (D62-19).
            refused: Dict[int, str] = {}
            for ref, meta in self._direct_meta.items():
                order = self.orders.get(ref)
                if order is None or not order.alive():
                    continue
                if meta.get("identity") is None and not meta.get("day_unknown"):
                    continue  # local waiting orders are kept
                refusal = self._direct_cancel_refusal(meta)
                if refusal is None:
                    working.append(order)
                else:
                    refused[ref] = refusal
                    order.addinfo(cancel_error=refusal)
            for order in working:
                self._direct_cancel(order)
        deadline = started + timeout
        while time.monotonic() < deadline and any(order.alive() for order in working):
            with self._direct_lock:
                self._direct_drain_events()
            time.sleep(0.05)
        unresolved = [order.ref for order in working if order.alive()] + list(refused)
        with self._direct_lock:
            # Nothing held is applied after stop: still unmatched fills are
            # reported (a restart books ours from the day's trade query).
            self._direct_expire_buffered_trades(reason="stopped")
        in_flight = self._direct_stop_poller_write(started)
        self._direct_on = False
        self._startup_ready = False
        self._live_started = False
        summary = {
            "status": "STOPPED" if not unresolved else "STOPPED_WITH_WORKING_ORDERS",
            "cancelled_requested": len(working),
            "unresolved_working_orders": len(unresolved),
            "waiting_orders_kept": len(self._direct_state.waiting.waiting()),
        }
        if refused:
            summary["cancel_refused"] = dict(collections.Counter(refused.values()))
        if in_flight is not None:
            # Not completed: the write's outcome is unknown yet and the run lock
            # stays held until it ends (then the poller records it, F3).
            summary["status"] = "STOPPED_WITH_WRITE_IN_FLIGHT"
            summary["write_in_flight"] = in_flight
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
    # the facts poller's venue write versus stop()
    # ------------------------------------------------------------------
    def _direct_poller_settle(self) -> Optional[Dict[str, Any]]:
        """The facts poller's only venue write (a switch settlement step), fenced by stop().

        ``None`` when ``stop()`` began before the step (nothing committed or
        sent) or while it ran: then ``_direct_stop``, or this thread once the
        stop bound passed, records a committed outcome, not the strategy thread.
        """
        gate = self._direct_write_gate
        with gate:
            if self._direct_stopping:
                return None
            self._direct_poller_write = {"operation": "settlement_confirm", "marker_id": None}
        outcome: Optional[Dict[str, Any]] = None
        stopping = True
        try:
            outcome = self._direct_settle_call()
        finally:
            with gate:
                self._direct_poller_write = None
                self._direct_poller_outcome = outcome
                stopping = self._direct_stopping
                handoff, self._direct_poller_handoff = self._direct_poller_handoff, False
                gate.notify_all()
            if handoff:
                self._direct_finish_handoff()
        return None if stopping else outcome

    def _direct_stop_poller_write(self, started: float) -> Optional[Dict[str, Any]]:
        """stop(): bounded wait for a poller write in flight; final snapshot; run lock.

        Only a committed write is waited for: an uncommitted step can no
        longer commit (``_StopFencedPort``), so it can send nothing.  A
        committed write still in flight after ``direct_stop_write_timeout``
        keeps its marker as committed (non-terminal) and the run lock: no other
        owner may start while it may still reach the venue.  The poller then
        records the outcome and releases the lock when the write ends; a
        process exit before that leaves the marker to the next start's
        reconciliation.  Returns that write (operation, marker id) or ``None``.
        """
        bound = max(float(self.p.direct_stop_write_timeout or 0.0), 0.0)
        gate = self._direct_write_gate

        def committed() -> Optional[Dict[str, Any]]:
            write = self._direct_poller_write
            return write if write is not None and write.get("marker_id") else None

        with gate:
            gate.wait_for(
                lambda: committed() is None,
                timeout=max(started + bound - time.monotonic(), 0.0),
            )
        with self._direct_lock:
            self._direct_write_snapshot()
        with gate:
            write = committed()
            in_flight = None if write is None else dict(write)
            self._direct_poller_handoff = in_flight is not None
        if in_flight is not None:
            in_flight["run_lock_held"] = True
            _log.warning(
                "direct stop: %s still in flight after %.1f s; the run lock stays held "
                "until it ends",
                in_flight["operation"],
                bound,
            )
            return in_flight
        with self._direct_lock:
            self._direct_record_poller_outcome()
        self._direct_release_lock()
        return None

    def _direct_record_poller_outcome(self) -> Optional[str]:
        """Record a poller settlement outcome the strategy thread never applied.

        Only a committed marker still undecided is recorded, by the rule of a
        switch attempt (confirmed: TERMINAL; unclear: UNKNOWN, writes blocked).
        """
        with self._direct_write_gate:
            outcome, self._direct_poller_outcome = self._direct_poller_outcome, None
        marker_id = (outcome or {}).get("marker_id")
        if not marker_id:
            return None  # nothing was committed, hence nothing was sent
        marker = self._direct_state.pending.get(marker_id)
        if marker is None or marker.get("status") in ("TERMINAL", "UNKNOWN"):
            return None  # already recorded
        return self._direct_day_switch_settlement(outcome)

    def _direct_finish_handoff(self) -> None:
        """Poller thread: the write stop() left in flight ended; record it, release the lock.

        The shutdown summary stays the report of the moment ``stop()`` returned.
        """
        kind: Optional[str] = None
        try:
            with self._direct_lock:
                kind = self._direct_record_poller_outcome()
        finally:
            self._direct_release_lock()
            _log.warning("direct stop: the in-flight write ended (%s); run lock released", kind)

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
        day = self._direct_order_day(order.ref)
        keys = identity_keys(dict(identity.fields), identity.client_order_id)
        self._direct_index_order(keys, order.ref, day)
        if event.exchange_order_id and identity.fields.get("exchange_id"):
            # Trade returns carry only ExchangeID + OrderSysID (as learned in
            # ``_direct_process_event`` for live orders).
            venue_key = ("x", str(identity.fields["exchange_id"]), str(event.exchange_order_id))
            self._direct_index_order([venue_key], order.ref, day, replace=False)
        self._direct_hand_over(order)
        return True


def direct_params():
    """Params appended to ``BtApiBroker.params`` for direct mode."""
    return _DIRECT_PARAMS
