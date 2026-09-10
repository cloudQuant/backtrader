"""Native Backtrader SA mid-frequency strategy for replay/shadow/SimNow.

The strategy owns SA-specific signals and policy only.  CTP protocol, durable
order identity, complete queries, and recovery remain Store/SDK responsibilities.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import backtrader as bt

try:
    from .features import QuoteFeatureWindow, normalize_quote, quote_window_span
    from .risk import DailyRiskStore, FillTimeBounds, GFDOrderDeadline, potential_exposure_lots
    from .signal_model import ConfirmationTracker, CostInputs, FusionDecision, fuse, minute_features
except ImportError:  # Direct execution via run.py.
    from features import QuoteFeatureWindow, normalize_quote, quote_window_span
    from risk import DailyRiskStore, FillTimeBounds, GFDOrderDeadline, potential_exposure_lots
    from signal_model import ConfirmationTracker, CostInputs, FusionDecision, fuse, minute_features


BEIJING = ZoneInfo("Asia/Shanghai")
DEFAULT_SESSIONS = (
    ("09:00", "10:15"),
    ("10:30", "11:30"),
    ("13:30", "15:00"),
    ("21:00", "23:00"),
)


def _epoch(value: Any) -> float:
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).timestamp()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    result = float(value)
    return result / 1000.0 if result > 10_000_000_000 else result


class SystemClock:
    def utc_now(self) -> float:
        return time.time()

    def monotonic_now(self) -> float:
        return time.monotonic()


def _event_value(event: Any, *names: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        for name in names:
            if event.get(name) is not None:
                return event[name]
        return default
    for name in names:
        value = getattr(event, name, None)
        if value is not None:
            return value
    return default


def _event_present(event: Any, *names: str) -> bool:
    if isinstance(event, dict):
        return any(name in event and event[name] is not None for name in names)
    return any(hasattr(event, name) and getattr(event, name) is not None for name in names)


def _account_core(value: Any) -> str:
    text = str(value or "")
    return text[5:] if text.startswith("acct_") else text


def _session_for_epoch(epoch: float, sessions=DEFAULT_SESSIONS) -> tuple[str, float] | None:
    moment = datetime.fromtimestamp(float(epoch), timezone.utc).astimezone(BEIJING)
    for start_text, end_text in sessions:
        start_hour, start_minute = map(int, start_text.split(":"))
        end_hour, end_minute = map(int, end_text.split(":"))
        start = moment.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        end = moment.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
        if start <= moment < end:
            return (
                f"{moment.date()}T{start_text}-{end_text}",
                end.astimezone(timezone.utc).timestamp(),
            )
    return None


class RuntimeControl:
    """Signal-safe shared request inspected from strategy callbacks."""

    def __init__(self) -> None:
        self.stop_reason = ""

    def request_stop(self, reason: str) -> None:
        if not self.stop_reason:
            self.stop_reason = str(reason)


def _publish_trade_logger_context_if_ready(strategy: Any, *, force: bool = False) -> bool:
    """Publish only for a fully initialized strategy, not bare test holders."""
    if not hasattr(strategy, "_trade_logger_context_dirty"):
        return False
    strategy._mark_trade_logger_context_dirty()
    return strategy._publish_trade_logger_context(force=force)


class SAMidFrequencyStrategy(bt.Strategy):
    """Frozen v0 candidate using native EMA/ATR and level-one snapshots."""

    params = (
        ("mode", "shadow"),
        ("purpose", "observation"),
        ("candidate_id", "iter22-sa-v0"),
        ("instrument", ""),
        ("trading_day", ""),
        ("connection_generation", 0),
        ("account_fingerprint", ""),
        ("environment_profile", ""),
        ("tick_size", 1.0),
        ("multiplier", 20.0),
        ("lots", 1),
        ("entry_score", 0.35),
        ("exit_score", 0.10),
        ("confirm_seconds", 2.0),
        ("confirm_quotes", 3),
        ("warmup_bars", 60),
        ("warmup_quote_seconds", 60.0),
        ("max_bar_age_seconds", 90.0),
        ("max_quote_age_seconds", 2.0),
        ("exit_quote_age_seconds", 5.0),
        ("watermark_milliseconds", 500.0),
        ("minimum_depth_lots", 5),
        ("maximum_spread_ticks", 2.0),
        ("minimum_hold_seconds", 60.0),
        ("maximum_hold_seconds", 900.0),
        ("cooldown_seconds", 60.0),
        ("entry_timeout_seconds", 3.0),
        ("cancel_timeout_seconds", 5.0),
        ("maximum_intent_age_seconds", 1.0),
        ("drain_timeout_seconds", 120.0),
        ("entry_protection_ticks", 1.0),
        ("max_exit_requotes", 2),
        ("maximum_entry_attempts", 30),
        ("entry_budget_key", "all"),
        ("maximum_write_requests", 100),
        ("emergency_write_reserve", 20),
        ("daily_loss_cny", 500.0),
        ("daily_loss_equity_fraction", 0.005),
        ("admitted", False),
        ("preflight_ready", False),
        ("hypothetical_fills", False),
        ("fee", None),
        ("price_limits", None),
        ("risk_store", None),
        ("reporter", None),
        ("runtime_control", None),
        ("clock", None),
        ("run_deadline_monotonic", None),
        ("reconciliation_request_interval", 2.0),
        ("reconciliation_timeout_seconds", 30.0),
        ("maximum_unknown_reconciliation_rounds", 2),
        ("sessions", DEFAULT_SESSIONS),
        ("session_calendar_sha256", ""),
        ("research_status", "RESEARCH_NOT_ESTABLISHED"),
        ("engineering_trigger", None),
        ("session_state_provider", None),
        ("execution_recovery", None),
    )

    def __init__(self) -> None:
        self.ema5 = bt.indicators.EMA(self.data.close, period=5)
        self.ema20 = bt.indicators.EMA(self.data.close, period=20)
        self.atr14 = bt.indicators.ATR(self.data, period=14)
        self.quote_window = QuoteFeatureWindow(self.p.tick_size)
        self.confirmation = ConfirmationTracker(self.p.confirm_seconds, self.p.confirm_quotes)
        self.deadline = GFDOrderDeadline(
            self.p.entry_timeout_seconds, self.p.cancel_timeout_seconds
        )
        self.closed_bars: deque[tuple[float, float]] = deque(maxlen=64)
        self.valid_volumes: deque[tuple[str, float]] = deque(maxlen=20)
        self.state = "STARTING"
        self.state_reason = ""
        self.last_quote = None
        self.last_fast = None
        self.last_minute = None
        self.last_fusion: Optional[FusionDecision] = None
        self._latest_bar_event = None
        self._last_bar_sequence = 0
        self._last_bar_ingest_seq = 0
        self._current_session_id = ""
        self._current_session_end = 0.0
        self._session_has_new_bar = False
        self._decision_versions: set[str] = set()
        self._active_order = None
        self._order_roles: dict[int, str] = {}
        self._order_terminal_refs: set[int] = set()
        self._entry_sent_monotonic: float | None = None
        self._cycle_sequence = 0
        self._active_cycle_id: str | None = None
        self._order_cycles: dict[int, str] = {}
        self._fill_bounds: FillTimeBounds | None = None
        self._entry_price: float | None = None
        self._stop_distance: float | None = None
        self._position_direction = 0
        self._cooldown_started: float | None = None
        self._drain_started: float | None = None
        self._reconciliation_hash = ""
        self._reconciliation_count = 0
        self._reconciliation_phase = ""
        self._reconciliation_request_id = ""
        self._reconciliation_request_ids_seen: set[str] = set()
        self._reconciliation_round_request_ids: list[str] = []
        self._reconciliation_proofs: list[dict[str, Any]] = []
        self._reconciliation_identity: tuple[str, str, str] | None = None
        self._reconciliation_started: float | None = None
        self._last_reconciliation_requested: float | None = None
        self._reconciliation_requests_issued = 0
        self._invalid_quotes = 0
        self._block_counts: dict[str, int] = {}
        self._orders: list[dict[str, Any]] = []
        self._trades: list[dict[str, Any]] = []
        self._state_history: list[dict[str, Any]] = []
        self._observation_first_event: float | None = None
        self._observation_last_event: float | None = None
        self._observation_last_key: tuple[str, str, int] | None = None
        self._observation_last_contiguous_event: float | None = None
        self._observation_seconds_by_session: dict[str, float] = {}
        self._observation_generations: set[int] = set()
        self._qualified_quotes = 0
        self._qualified_bars = 0
        self._first_bar_end: float | None = None
        self._last_bar_end: float | None = None
        self._terminal_session_state: dict[str, Any] = {}
        self._evidence_failure_count = 0
        self._evidence_failure_reason = ""
        self._evidence_recording_failed = False
        self._risk_failure_count = 0
        self._risk_failure_reason = ""
        self._exit_requotes_used = 0
        self._unknown_intents = 0
        self._unknown_origin_was_draining = False
        self._engineering_trigger_fired = False
        self._recovery_only = False
        self._recovery_plan: dict[str, Any] | None = None
        self._recovery_allowed_close: dict[str, Any] | None = None
        self._recovery_completion: dict[str, Any] | None = None
        self._clock = self.p.clock or SystemClock()
        # The generic observer owns the report envelope.  Keep the SA
        # extension live on meaningful transitions and at a bounded quote
        # cadence; never serialize it once per market-data callback.
        self._trade_logger_context_dirty = True
        self._trade_logger_context_revision = 0
        self._trade_logger_last_attempted_quotes = 0
        self._trade_logger_last_attempted_revision = -1
        self._trade_logger_context_published = False
        self._trade_logger_context_failed_since_success = False
        self._trade_logger_context_failure_count = 0
        self._trade_logger_context_last_error = None
        self._trade_logger_context_last_failure_recorded = None

    @property
    def reporter(self):
        return self.p.reporter

    @property
    def risk_store(self) -> Optional[DailyRiskStore]:
        return self.p.risk_store

    def _position_legs(self) -> tuple[int, int]:
        get_param = getattr(self.broker, "get_param", None)
        mode = str(get_param("position_mode", "net") if callable(get_param) else "net").lower()
        if mode == "dual_side":
            try:
                long_lots = abs(int(self.getposition(self.data, self.broker, side="long").size))
                short_lots = abs(int(self.getposition(self.data, self.broker, side="short").size))
            except (AttributeError, TypeError):
                return max(int(self.position.size), 0), max(-int(self.position.size), 0)
            return long_lots, short_lots
        size = int(self.position.size)
        return max(size, 0), max(-size, 0)

    def _gross_position_lots(self) -> int:
        long_lots, short_lots = self._position_legs()
        return long_lots + short_lots

    def _signed_position_lots(self) -> int:
        long_lots, short_lots = self._position_legs()
        return long_lots - short_lots

    def _record(self, stream: str, payload: dict[str, Any]) -> None:
        if self.reporter is None or self._evidence_recording_failed:
            return
        try:
            self.reporter.append(stream, payload)
        except Exception as exc:
            # Evidence failure closes admission immediately.  It must not
            # escape a Strategy callback or recursively attempt another audit
            # append while a position may still need controlled drainage.
            self._evidence_recording_failed = True
            self._evidence_failure_count += 1
            self._evidence_failure_reason = type(exc).__name__
            now = self._clock.monotonic_now()
            if self._active_order is not None or self._gross_position_lots() != 0:
                self.request_drain("evidence_write_failed", now)
            elif self.state not in {"STOPPED_FLAT", "MANUAL_INTERVENTION"}:
                self.state = "HALTED"
                self.state_reason = "evidence_write_failed"

    def _transition(self, state: str, reason: str, now: Optional[float] = None) -> None:
        recovery_only = bool(getattr(self, "_recovery_only", False))
        completion = getattr(self, "_recovery_completion", None)
        recovery_completed = bool(
            isinstance(completion, dict)
            and set(completion) == {"completed", "status", "error_code"}
            and completion.get("completed") is True
            and completion.get("status") == "completed"
            and completion.get("error_code") is None
        )
        if recovery_only and state == "STOPPED_FLAT" and not recovery_completed:
            state = "MANUAL_INTERVENTION"
            reason = "sdk_recovery_completion_required"
        if recovery_only and state == "MANUAL_INTERVENTION":
            abort = getattr(getattr(self, "broker", None), "abort_execution_recovery", None)
            if callable(abort):
                try:
                    abort(f"strategy_{reason}")
                except Exception:
                    pass
        self.state = state
        self.state_reason = reason
        event = {"state": state, "reason": reason, "monotonic": now}
        self._state_history.append(event)
        self._record("risk_events", {"event": "state_transition", **event})
        _publish_trade_logger_context_if_ready(self)

    def _bind_startup_recovery(self, initial_position: int) -> bool:
        """Accept only the exact recovery close issued by the managed SDK."""

        supplied = getattr(self.p, "execution_recovery", None)
        getter = getattr(self.broker, "get_execution_recovery", None)
        current = getter() if callable(getter) else None
        if not isinstance(supplied, dict) or current != supplied:
            return False
        closes = supplied.get("allowed_closes")
        if (
            supplied.get("status") != "RECOVERABLE"
            or supplied.get("can_arm_recovery") is not True
            or supplied.get("allowed_actions") != ["close"]
            or supplied.get("allowed_cancels") != []
            or type(closes) is not list
            or len(closes) != 1
            or initial_position != 1
        ):
            return False
        action = dict(closes[0]) if isinstance(closes[0], dict) else {}
        cycle_id = str(supplied.get("execution_cycle_id") or "")
        token = str(supplied.get("recovery_token_sha256") or "")
        instrument = str(getattr(self.p, "instrument", "") or self.data._name).upper()
        action_instrument = str(action.get("symbol") or "").upper()
        long_lots, short_lots = self._position_legs()
        expected_position_side = "long" if long_lots else "short" if short_lots else ""
        expected_side = "sell" if expected_position_side == "long" else "buy"
        try:
            quantity = int(action.get("quantity"))
        except (TypeError, ValueError):
            quantity = 0
        if not (
            cycle_id
            and len(cycle_id) <= 128
            and re.fullmatch(r"[0-9a-f]{64}", token)
            and action.get("execution_cycle_id") == cycle_id
            and action_instrument == instrument
            and str(action.get("exchange_id") or "").upper() in {"CZCE", "ZCE"}
            and str(action.get("position_side") or "").lower() == expected_position_side
            and str(action.get("side") or "").lower() == expected_side
            and str(action.get("offset") or "").lower() == "close"
            and action.get("quantity") == str(quantity)
            and quantity == initial_position
            and action.get("quantity_unit") == "contracts"
        ):
            return False
        self._recovery_only = True
        self._recovery_plan = dict(supplied)
        self._recovery_allowed_close = action
        self._active_cycle_id = cycle_id
        return True

    def start(self) -> None:
        if self.p.mode not in {"replay", "shadow", "simnow"}:
            self._transition("HALTED", "invalid_mode")
            return
        if self.p.lots != 1:
            self._transition("HALTED", "v0_requires_one_lot")
            return
        if self.p.mode == "simnow" and self.p.research_status == "RESEARCH_REJECTED":
            self._transition("HALTED", "research_rejected")
            return
        if (
            self.p.mode == "simnow"
            and self.p.purpose == "natural_signal"
            and self.p.research_status != "RESEARCH_ADMITTED"
        ):
            self._transition("HALTED", "natural_signal_research_not_admitted")
            return
        initial_position = self._gross_position_lots()
        if initial_position != 0:
            if not self._bind_startup_recovery(initial_position):
                self._transition("MANUAL_INTERVENTION", "startup_position_ownership_unproven")
                return
            self.request_drain("sdk_owned_startup_recovery")
            return
        if self.p.mode in {"shadow", "replay"}:
            reason = "shadow_read_only" if self.p.mode == "shadow" else "replay_read_only"
            self._transition("OBSERVING", reason)
        elif not self.p.admitted or not self.p.preflight_ready:
            self._transition("HALTED", "execution_admission_missing")
        else:
            summary_method = getattr(self.broker, "get_execution_summary", None)
            try:
                durable = summary_method() if callable(summary_method) else None
            except Exception as exc:
                durable = None
                self._block(f"durable_intent_read_failed:{type(exc).__name__}")
            now = self._clock.monotonic_now()
            if not isinstance(durable, dict) or (
                durable.get("session_enabled") is not True
                or durable.get("trading_blocked") is not False
                or durable.get("evidence_errors") != []
                or type(durable.get("unknown_ids")) is not list
                or type(durable.get("active_orders")) is not int
                or int(durable.get("active_orders", -1)) < 0
            ):
                self._unknown_intents = 1
                self._unknown_origin_was_draining = True
                self._begin_reconciliation(
                    "unknown_resolution", "durable_intent_evidence_incomplete", now
                )
                return
            unknown = list(durable["unknown_ids"])
            active_count = int(durable["active_orders"])
            if active_count or unknown:
                self._unknown_intents = max(active_count + len(unknown), 1)
                self._unknown_origin_was_draining = True
                self._begin_reconciliation("unknown_resolution", "durable_intent_recovery", now)
                return
            self._transition("WARMING", "warmup_not_complete")

    def notify_bar(self, bar: Any) -> None:
        self._latest_bar_event = bar

    def _bar_identity(self, fallback_start: float) -> tuple[str, float, float, str, bool, str]:
        event = self._latest_bar_event
        required = (
            "symbol",
            "exchange",
            "asset_type",
            "bucket_start",
            "bucket_end",
            "available_at",
            "bar_id",
            "complete",
            "quality",
            "quality_flags",
            "volume_complete",
            "trading_day",
            "action_day",
            "connection_generation",
            "first_ingest_seq",
            "last_ingest_seq",
            "bar_sequence",
            "closure_reason",
        )
        missing = [name for name in required if not _event_present(event, name)]
        if missing:
            return (
                "",
                fallback_start,
                fallback_start,
                "",
                False,
                "bar_schema_missing:" + ",".join(missing),
            )
        try:
            start = _epoch(_event_value(event, "bucket_start"))
            end = _epoch(_event_value(event, "bucket_end"))
            available = _epoch(_event_value(event, "available_at"))
            generation = int(_event_value(event, "connection_generation"))
            first_sequence = int(_event_value(event, "first_ingest_seq"))
            last_sequence = int(_event_value(event, "last_ingest_seq"))
            bar_sequence = int(_event_value(event, "bar_sequence"))
        except (TypeError, ValueError, OverflowError):
            return "", fallback_start, fallback_start, "", False, "bar_schema_value_invalid"
        bar_id = str(_event_value(event, "bar_id") or "")
        symbol = str(_event_value(event, "symbol") or "").upper()
        exchange = str(_event_value(event, "exchange") or "").upper()
        asset_type = str(_event_value(event, "asset_type") or "").lower()
        complete = _event_value(event, "complete") is True
        volume_complete = _event_value(event, "volume_complete") is True
        trading_day = str(_event_value(event, "trading_day") or "")
        action_day = str(_event_value(event, "action_day") or "")
        flags_value = _event_value(event, "quality_flags")
        flags = (
            tuple(flags_value)
            if isinstance(flags_value, (tuple, list, set, frozenset))
            else ("invalid_quality_flags",)
        )
        quality = str(_event_value(event, "quality") or "").upper()
        closure_reason = str(_event_value(event, "closure_reason") or "")
        minimum_available = end + float(self.p.watermark_milliseconds) / 1000.0
        valid = (
            complete
            and volume_complete
            and not flags
            and quality == "GOOD"
            and symbol == str(self.p.instrument or self.data._name).upper()
            and exchange in {"CZCE", "ZCE"}
            and asset_type in {"future", "futures"}
            and closure_reason in {"load", "idle", "tick", "source_exhausted"}
            and bool(bar_id and trading_day and action_day)
            and generation > 0
            and first_sequence > 0
            and last_sequence >= first_sequence
            and bar_sequence > 0
            and bar_sequence > int(getattr(self, "_last_bar_sequence", 0))
            and first_sequence > int(getattr(self, "_last_bar_ingest_seq", 0))
            and math.isclose(end - start, 60.0, rel_tol=0.0, abs_tol=1e-6)
            and available + 1e-9 >= minimum_available
        )
        if not valid and not flags:
            flags = ("bar_contract_invalid",)
        if self.p.connection_generation and generation != int(self.p.connection_generation):
            valid = False
            flags = (*flags, "bar_generation_mismatch")
        if self.p.trading_day and trading_day != str(self.p.trading_day):
            valid = False
            flags = (*flags, "bar_trading_day_mismatch")
        if len(action_day) != 8 or not action_day.isdigit():
            valid = False
            flags = (*flags, "bar_action_day_invalid")
        elif action_day != datetime.fromtimestamp(start, timezone.utc).astimezone(BEIJING).strftime(
            "%Y%m%d"
        ):
            valid = False
            flags = (*flags, "bar_action_day_mismatch")
        if valid:
            self._last_bar_sequence = bar_sequence
            self._last_bar_ingest_seq = last_sequence
        return bar_id, end, available, trading_day, valid, ",".join(map(str, flags))

    def next(self) -> None:
        start = bt.num2date(self.data.datetime[0]).replace(tzinfo=timezone.utc).timestamp()
        bar_id, bar_end, available, trading_day, valid, invalid_reason = self._bar_identity(start)
        if not valid:
            self._block("invalid_completed_bar:" + (invalid_reason or "quality"))
            self.last_minute = None
            self.confirmation.reset()
            # Live feeds may call ``next`` for each still-open minute.  The
            # invalid-bar counter is sampled by the bounded quote cadence;
            # publishing it here would serialize context once per tick.
            return
        current_close = float(self.data.close[0])
        current_volume = float(self.data.volume[0])
        prior_volumes = tuple(self.valid_volumes)
        self.closed_bars.append((bar_end, current_close))
        try:
            ema5 = float(self.ema5[0])
            ema20 = float(self.ema20[0])
            atr14 = float(self.atr14[0])
        except (IndexError, TypeError, ValueError):
            ema5 = ema20 = atr14 = math.nan
        self.last_minute = minute_features(
            closes=tuple(self.closed_bars)[-6:],
            current_volume=current_volume,
            previous_volumes=prior_volumes,
            trading_day=trading_day,
            ema5=ema5,
            ema20=ema20,
            atr14=atr14,
            tick_size=self.p.tick_size,
            bar_id=bar_id,
            bar_end=bar_end,
            available_at=available,
        )
        self._record(
            "bars",
            {
                "bar_id": bar_id,
                "bar_end": bar_end,
                "available_at": available,
                "trading_day": trading_day,
                "open": float(self.data.open[0]),
                "high": float(self.data.high[0]),
                "low": float(self.data.low[0]),
                "close": current_close,
                "volume": current_volume,
                "minute_features": self.last_minute.as_dict(),
            },
        )
        self.valid_volumes.append((trading_day, current_volume))
        self._qualified_bars += 1
        self._first_bar_end = bar_end if self._first_bar_end is None else self._first_bar_end
        self._last_bar_end = bar_end
        if self._current_session_id:
            self._session_has_new_bar = True
        if len(self.closed_bars) < self.p.warmup_bars:
            self._block("warmup_bars")
        self.confirmation.reset()
        _publish_trade_logger_context_if_ready(self)

    def notify_tick(self, tick: Any) -> None:
        raw_event_time = _event_value(tick, "event_time_utc", "timestamp", default=None)
        try:
            _epoch(raw_event_time)
        except (TypeError, ValueError):
            self._reject_quote("invalid_event_time")
            return
        recv_ns = _event_value(tick, "recv_monotonic_ns", "received_monotonic_ns", default=None)
        recv_seconds = _event_value(tick, "recv_monotonic", "received_monotonic", default=None)
        recv_mono = float(recv_ns) / 1e9 if recv_ns is not None else float(recv_seconds or 0.0)
        if recv_mono <= 0:
            self._reject_quote("missing_recv_monotonic")
            return
        validation = normalize_quote(
            tick,
            tick_size=self.p.tick_size,
            now_wall_utc=self._clock.utc_now(),
            now_monotonic=self._clock.monotonic_now(),
            max_receive_age=float(self.p.max_quote_age_seconds),
            max_event_age=float(self.p.max_quote_age_seconds),
        )
        if not validation.valid or validation.quote is None:
            self._reject_quote(validation.reason)
            return
        quote = validation.quote
        if self.p.trading_day and quote.trading_day != str(self.p.trading_day):
            self._reject_quote("trading_day_mismatch")
            return
        if self.p.connection_generation and quote.connection_generation != int(
            self.p.connection_generation
        ):
            self._reject_quote("connection_generation_mismatch")
            return
        local_day = datetime.fromtimestamp(quote.event_time, timezone.utc).astimezone(BEIJING)
        if quote.action_day != local_day.strftime("%Y%m%d"):
            self._reject_quote("action_day_event_time_mismatch")
            return
        if self.p.mode == "simnow" and not self.p.session_calendar_sha256:
            self._reject_quote("session_calendar_binding_missing")
            return
        session = _session_for_epoch(quote.event_time, self.p.sessions)
        session_id = session[0] if session else ""
        if session_id != self._current_session_id:
            self.quote_window.clear()
            self.confirmation.reset()
            self._current_session_id = session_id
            self._current_session_end = session[1] if session else 0.0
            self._session_has_new_bar = False
        if not self.quote_window.add(quote):
            self._reject_quote(self.quote_window.last_invalid_reason)
            return
        self.last_quote = quote
        if session is not None:
            self._observe_valid_quote(quote, session_id)
        self._record(
            "quotes",
            {
                "event_time": quote.event_time,
                "recv_time_utc": quote.recv_time_utc,
                "recv_monotonic": quote.recv_monotonic,
                "ingest_seq": quote.ingest_seq,
                "bid": quote.bid,
                "ask": quote.ask,
                "bid_size": quote.bid_size,
                "ask_size": quote.ask_size,
                "last": quote.last,
                "cum_volume": quote.cum_volume,
                "delta_volume": quote.delta_volume,
                "trading_day": quote.trading_day,
                "action_day": quote.action_day,
                "connection_generation": quote.connection_generation,
                "lower_limit": quote.lower_limit,
                "upper_limit": quote.upper_limit,
                "source": quote.source,
                "schema_version": quote.schema_version,
                "volume_quality": quote.volume_quality,
                "event_time_source": quote.event_time_source,
                "continuity_status": quote.continuity_status,
                "volume_complete": quote.volume_complete,
            },
        )
        self.last_fast = self.quote_window.calculate()
        self._advance_time(recv_mono, quote.event_time)
        self._evaluate_entry(quote)
        if self._qualified_quotes - getattr(self, "_trade_logger_last_attempted_quotes", 0) >= 128:
            _publish_trade_logger_context_if_ready(self)

    def _reject_quote(self, reason: str) -> None:
        self._invalid_quotes += 1
        self._block("quote:" + reason)
        self.confirmation.reset()
        self._observation_last_key = None
        self._observation_last_contiguous_event = None

    def _observe_valid_quote(self, quote, session_id: str) -> None:
        key = (session_id, quote.trading_day, quote.connection_generation)
        if (
            key == self._observation_last_key
            and self._observation_last_contiguous_event is not None
        ):
            elapsed = quote.event_time - self._observation_last_contiguous_event
            if 0.0 <= elapsed <= 2.0:
                self._observation_seconds_by_session[session_id] = (
                    self._observation_seconds_by_session.get(session_id, 0.0) + elapsed
                )
            else:
                self._observation_last_key = None
        self._observation_first_event = (
            quote.event_time
            if self._observation_first_event is None
            else min(self._observation_first_event, quote.event_time)
        )
        self._observation_last_event = quote.event_time
        self._observation_last_key = key
        self._observation_last_contiguous_event = quote.event_time
        self._observation_generations.add(quote.connection_generation)
        self._qualified_quotes += 1

    def _block(self, reason: str) -> None:
        self._block_counts[reason] = self._block_counts.get(reason, 0) + 1

    def _cost_inputs(self, quote) -> CostInputs:
        fee = dict(self.p.fee or {})
        close_money = max(
            float(fee.get("close_money_rate", 0.0)),
            float(fee.get("close_today_money_rate", 0.0)),
        )
        close_volume = max(
            float(fee.get("close_volume_rate", 0.0)),
            float(fee.get("close_today_volume_rate", 0.0)),
        )
        return CostInputs(
            tick_size=float(self.p.tick_size),
            multiplier=float(self.p.multiplier),
            lots=1,
            entry_price=float(quote.ask if quote else 0.0),
            exit_price=float(quote.bid if quote else 0.0),
            open_money_rate=float(fee.get("open_money_rate", 0.0)),
            open_volume_rate=float(fee.get("open_volume_rate", 0.0)),
            close_money_rate=close_money,
            close_volume_rate=close_volume,
            entry_slip_ticks=float(fee.get("entry_slip_ticks", 1.0)),
            exit_slip_ticks=float(fee.get("exit_slip_ticks", 1.0)),
            edge_buffer_ticks=float(fee.get("edge_buffer_ticks", 1.0)),
            verified=bool(fee.get("verified", False)),
            source=str(fee.get("source", "")),
        )

    def _unrealized_pnl(self) -> Optional[float]:
        size = self._signed_position_lots()
        if size == 0:
            return 0.0
        if self.last_quote is None or self._entry_price is None:
            return None
        price = self.last_quote.bid if size > 0 else self.last_quote.ask
        return (price - self._entry_price) * self.p.multiplier * size

    def _risk_admission(self) -> tuple[bool, str]:
        store = self.p.risk_store
        if store is None or store.record is None:
            return False, "daily_risk_state_unavailable"
        admitted, reason, _threshold = store.admission(
            unrealized_pnl=self._unrealized_pnl(),
            daily_loss_cny=self.p.daily_loss_cny,
            daily_loss_fraction=self.p.daily_loss_equity_fraction,
        )
        if self.reporter is not None and not self.reporter.opening_allowed:
            return False, self.reporter.failure_reason or "evidence_unavailable"
        return admitted, reason

    def _evaluate_entry(self, quote) -> None:
        if self.p.mode in {"shadow", "replay"}:
            reason = "shadow_read_only" if self.p.mode == "shadow" else "replay_read_only"
            self._observe_signal(quote, executable=False, base_reason=reason)
            return
        if self.state not in {"WARMING", "FLAT"}:
            return
        if not self.p.admitted or not self.p.preflight_ready:
            self._block("execution_admission_missing")
            return
        if len(self.closed_bars) < self.p.warmup_bars:
            self._block("warmup_bars")
            return
        if quote_window_span(self.quote_window.quotes) < self.p.warmup_quote_seconds:
            self._block("warmup_quote_seconds")
            return
        if not self._session_has_new_bar or not self._current_session_id:
            self._block("session_not_ready")
            return
        if self._current_session_end - quote.event_time <= 930.0:
            self._block("session_entry_cutoff")
            return
        if self.last_fast is None or self.last_minute is None:
            self._block("features_not_ready")
            return
        if quote.event_time - self.last_minute.bar_end > self.p.max_bar_age_seconds:
            self.confirmation.reset()
            self._block("bar_stale")
            return
        if self.last_minute.available_at > quote.event_time:
            self.confirmation.reset()
            self._block("bar_not_yet_available")
            return
        if (
            self.last_fast.spread_ticks is None
            or self.last_fast.spread_ticks > self.p.maximum_spread_ticks
        ):
            self.confirmation.reset()
            self._block("spread_gate")
            return
        if min(quote.bid_size, quote.ask_size) < self.p.minimum_depth_lots:
            self.confirmation.reset()
            self._block("depth_gate")
            return
        risk_ok, risk_reason = self._risk_admission()
        if not risk_ok:
            self.confirmation.reset()
            self._block(risk_reason)
            return
        if potential_exposure_lots(self._gross_position_lots(), 1 if self._active_order else 0) > 1:
            self.confirmation.reset()
            self._block("potential_exposure_gt_one")
            return
        if self.p.purpose == "engineering_smoke":
            direction = self._engineering_trigger_direction(quote)
            if direction == 0:
                self._block("engineering_trigger_not_reached")
                return
            version = f"engineering:{self.p.engineering_trigger['trigger_id']}:{quote.ingest_seq}"
            self._record(
                "signals",
                {
                    "event_time": quote.event_time,
                    "tick_seq": quote.ingest_seq,
                    "bar_id": self.last_minute.bar_id,
                    "engineering_trigger": dict(self.p.engineering_trigger),
                    "decision_version": version,
                    "confirmed": True,
                    "mode": self.p.mode,
                },
            )
            self._engineering_trigger_fired = True
            self._decision_versions.add(version)
            self._submit_entry(direction, quote, version)
            return
        try:
            decision = fuse(
                self.last_fast,
                self.last_minute,
                self._cost_inputs(quote),
                entry_score=self.p.entry_score,
            )
        except ValueError as exc:
            self.confirmation.reset()
            self._block("cost_input_invalid:" + str(exc))
            return
        self.last_fusion = decision
        eligible = decision.ready
        confirmed = self.confirmation.observe(
            direction=decision.direction,
            bar_id=self.last_minute.bar_id,
            quote_time=quote.event_time,
            eligible=eligible,
        )
        signal_record = {
            "event_time_utc": datetime.fromtimestamp(quote.event_time, timezone.utc).isoformat(),
            "tick_seq": quote.ingest_seq,
            "bar_id": self.last_minute.bar_id,
            "bar_available_at": self.last_minute.available_at,
            "decision": decision.as_dict(),
            "confirmed": confirmed,
            "confirmation_count": self.confirmation.count,
            "mode": self.p.mode,
        }
        self._record("signals", signal_record)
        if not confirmed:
            if decision.reasons:
                self._block(decision.reasons[0])
            return
        version = f"{self.last_minute.bar_id}:{decision.direction}:{quote.ingest_seq}"
        if version in self._decision_versions:
            self._block("duplicate_decision_version")
            return
        self._decision_versions.add(version)
        self._submit_entry(decision.direction, quote, version)

    def _engineering_trigger_direction(self, quote) -> int:
        trigger = self.p.engineering_trigger
        if self._engineering_trigger_fired or not isinstance(trigger, dict):
            return 0
        if (
            str(trigger.get("instrument") or "").upper() != str(self.p.instrument).upper()
            or str(trigger.get("trading_day") or "") != str(self.p.trading_day)
            or quote.ingest_seq < int(trigger.get("minimum_ingest_seq") or 0)
        ):
            return 0
        try:
            start = _epoch(trigger["not_before_utc"])
            end = _epoch(trigger["not_after_utc"])
        except (KeyError, TypeError, ValueError):
            return 0
        if not start <= quote.event_time <= end:
            return 0
        return 1 if trigger.get("side") == "long" else -1 if trigger.get("side") == "short" else 0

    def _observe_signal(self, quote, *, executable: bool, base_reason: str) -> None:
        decision = None
        if self.last_fast is not None and self.last_minute is not None:
            try:
                decision = fuse(
                    self.last_fast,
                    self.last_minute,
                    self._cost_inputs(quote),
                    entry_score=self.p.entry_score,
                )
            except ValueError:
                decision = None
        self._record(
            "signals",
            {
                "event_time": quote.event_time,
                "tick_seq": quote.ingest_seq,
                "bar_id": self.last_minute.bar_id if self.last_minute else None,
                "decision": decision.as_dict() if decision else None,
                "executable": executable,
                "blocked_by": base_reason,
                "mode": self.p.mode,
            },
        )
        self._block(base_reason)

    def _aligned_limit(self, side: str, quote) -> float:
        raw = (
            quote.ask + self.p.entry_protection_ticks * self.p.tick_size
            if side == "buy"
            else quote.bid - self.p.entry_protection_ticks * self.p.tick_size
        )
        units = (
            math.ceil(raw / self.p.tick_size)
            if side == "buy"
            else math.floor(raw / self.p.tick_size)
        )
        price = units * self.p.tick_size
        lower = float(quote.lower_limit)
        upper = float(quote.upper_limit)
        if not (math.isfinite(lower) and math.isfinite(upper) and 0 < lower <= upper):
            raise ValueError("price limits are unavailable")
        return min(max(price, lower), upper)

    def _latch_risk_failure(self, exc: BaseException | None = None) -> None:
        self._risk_failure_count += 1
        self._risk_failure_reason = (
            type(exc).__name__ if exc is not None else "risk_persistence_unavailable"
        )
        if self._active_order is not None or self._gross_position_lots() != 0:
            if self.state not in {"DRAINING", "EXIT_PENDING", "RECOVERING"}:
                now = self._clock.monotonic_now()
                self._drain_started = self._drain_started or now
                self._transition("DRAINING", "risk_persistence_unavailable", now)
        elif self.state in {"STARTING", "WARMING", "FLAT", "COOLDOWN", "OBSERVING"}:
            self._transition("HALTED", "risk_persistence_unavailable")

    def _reserve(
        self,
        *,
        entry: bool,
        emergency: bool = False,
        emergency_key: str = "",
    ) -> bool:
        store = self.p.risk_store
        if store is None:
            return False
        try:
            if entry and not store.reserve_entry(
                self.p.maximum_entry_attempts, budget_key=self.p.entry_budget_key
            ):
                return False
            reserved = store.reserve_write(
                emergency=emergency,
                normal_limit=self.p.maximum_write_requests,
                reserve=self.p.emergency_write_reserve,
                allow_unpersisted_emergency=(
                    emergency
                    and self.p.mode == "simnow"
                    and self.p.admitted
                    and self.p.preflight_ready
                ),
                emergency_key=emergency_key,
            )
        except Exception as exc:
            self._latch_risk_failure(exc)
            return False
        if not store.persistence_ok:
            self._latch_risk_failure()
        return reserved

    def _submit_entry(self, direction: int, quote, version: str) -> None:
        if self.state not in {"WARMING", "FLAT"} or self._active_order is not None:
            return
        submission_age = self._clock.monotonic_now() - float(quote.recv_monotonic)
        if submission_age < 0 or submission_age > float(self.p.maximum_intent_age_seconds):
            self._transition("HALTED", "entry_intent_expired", quote.recv_monotonic)
            return
        if not self._reserve(entry=True):
            self._transition("HALTED", "entry_or_write_budget_exhausted", quote.recv_monotonic)
            return
        side = "buy" if direction > 0 else "sell"
        try:
            price = self._aligned_limit(side, quote)
        except ValueError as exc:
            self._transition("HALTED", str(exc), quote.recv_monotonic)
            return
        submission_age = self._clock.monotonic_now() - float(quote.recv_monotonic)
        if submission_age < 0 or submission_age > float(self.p.maximum_intent_age_seconds):
            self._transition("HALTED", "entry_intent_expired", quote.recv_monotonic)
            return
        submitted_at = self._clock.monotonic_now()
        submission_age = submitted_at - float(quote.recv_monotonic)
        if submission_age < 0 or submission_age > float(self.p.maximum_intent_age_seconds):
            self._transition("HALTED", "entry_intent_expired", submitted_at)
            return
        self._cycle_sequence = int(getattr(self, "_cycle_sequence", 0)) + 1
        cycle_material = "|".join(
            (
                str(getattr(self.p, "account_fingerprint", "") or ""),
                str(getattr(self.p, "trading_day", "") or ""),
                str(getattr(self.p, "connection_generation", 0) or 0),
                str(getattr(self.p, "instrument", "") or getattr(self.data, "_name", "")),
                str(self._cycle_sequence),
                format(float(submitted_at), ".9f"),
            )
        )
        cycle_id = hashlib.sha256(cycle_material.encode("utf-8")).hexdigest()
        submit = self.buy if direction > 0 else self.sell
        order = submit(
            data=self.data,
            size=1,
            price=price,
            exectype=bt.Order.Limit,
            time_in_force="GFD",
            position_side="long" if direction > 0 else "short",
            offset="open",
            candidate_id=self.p.candidate_id,
            decision_version=version,
            execution_cycle_id=cycle_id,
            execution_role="entry",
        )
        if order is None:
            self._enter_unknown("broker_returned_no_order", submitted_at)
            return
        self._active_order = order
        self._active_cycle_id = cycle_id
        if not hasattr(self, "_order_cycles"):
            self._order_cycles = {}
        self._order_cycles[order.ref] = cycle_id
        self._order_roles[order.ref] = "entry"
        self._entry_sent_monotonic = submitted_at
        self.deadline.submitted(submitted_at)
        self._transition("ENTRY_PENDING", "entry_gfd_submitted", submitted_at)

    def _request_exit(self, reason: str, now: float, *, emergency: bool) -> None:
        if self._active_order is not None:
            return
        broker_mode = str(
            getattr(self.broker, "get_param", lambda *_args, **_kwargs: "net")(
                "position_mode", "net"
            )
        ).lower()
        position_side = None
        if broker_mode == "dual_side":
            long_lots = abs(int(self.getposition(self.data, self.broker, side="long").size))
            short_lots = abs(int(self.getposition(self.data, self.broker, side="short").size))
            if long_lots and short_lots:
                self._transition("MANUAL_INTERVENTION", "simultaneous_dual_side_legs", now)
                return
            if long_lots:
                position_side, position_lots, side = "long", long_lots, "sell"
            elif short_lots:
                position_side, position_lots, side = "short", short_lots, "buy"
            else:
                return
        else:
            position_lots = self._gross_position_lots()
            if position_lots == 0:
                return
            side = "sell" if self._signed_position_lots() > 0 else "buy"
        recovery_only = bool(getattr(self, "_recovery_only", False))
        if self.last_quote is None:
            if recovery_only:
                self._block("recovery_exit_quote_unavailable")
                return
            self._transition("MANUAL_INTERVENTION", "exit_quote_unavailable", now)
            return
        cycle_id = getattr(self, "_active_cycle_id", None)
        if not cycle_id:
            self._transition("MANUAL_INTERVENTION", "position_cycle_identity_missing", now)
            return
        recovery_action = getattr(self, "_recovery_allowed_close", None)
        if recovery_only:
            if not isinstance(recovery_action, dict) or not (
                recovery_action.get("execution_cycle_id") == cycle_id
                and recovery_action.get("position_side") == position_side
                and recovery_action.get("side") == side
                and recovery_action.get("quantity") == str(position_lots)
                and recovery_action.get("quantity_unit") == "contracts"
            ):
                self._transition("MANUAL_INTERVENTION", "recovery_close_proof_mismatch", now)
                return
        if not self._reserve(entry=False, emergency=emergency, emergency_key="exit"):
            self._transition("MANUAL_INTERVENTION", "exit_write_budget_exhausted", now)
            return
        try:
            price = self._aligned_limit(side, self.last_quote)
        except ValueError:
            if recovery_only:
                self._block("recovery_exit_price_unavailable")
                return
            self._transition("MANUAL_INTERVENTION", "exit_price_unavailable", now)
            return
        close_kwargs = {
            "data": self.data,
            "size": position_lots,
            "price": price,
            "exectype": bt.Order.Limit,
            "time_in_force": "GFD",
            "offset": recovery_action["offset"] if recovery_only else "close",
            "exit_reason": reason,
            "execution_cycle_id": cycle_id,
            "execution_role": "recovery_exit" if recovery_only else "exit",
        }
        if position_side is not None:
            close_kwargs["position_side"] = position_side
        if recovery_only:
            close_kwargs["quantity_unit"] = recovery_action["quantity_unit"]
            close_kwargs["exchange_id"] = recovery_action["exchange_id"]
            submit = self.buy if side == "buy" else self.sell
            order = submit(**close_kwargs)
        else:
            order = self.close(**close_kwargs)
        if order is None:
            self._enter_unknown("broker_returned_no_exit_order", now)
            return
        self._active_order = order
        if not hasattr(self, "_order_cycles"):
            self._order_cycles = {}
        self._order_cycles[order.ref] = cycle_id
        self._order_roles[order.ref] = "recovery_exit" if recovery_only else "exit"
        self.deadline.submitted(now)
        self._transition("EXIT_PENDING", reason, now)

    def _enter_unknown(self, reason: str, now: float) -> None:
        self._unknown_intents = max(self._unknown_intents, 1)
        if bool(getattr(self, "_recovery_only", False)):
            self._enter_manual_monitor(f"recovery_{reason}", now)
            return
        self._unknown_origin_was_draining = (
            self.state == "DRAINING" or self._drain_started is not None
        )
        self._begin_reconciliation("unknown_resolution", reason, now)

    def _enter_manual_monitor(self, reason: str, now: float) -> None:
        self._reconciliation_phase = "manual_monitor"
        self._reconciliation_started = now
        self._last_reconciliation_requested = None
        self._transition("MANUAL_INTERVENTION", reason, now)
        self._request_reconciliation(now)

    def _advance_time(self, now: float, event_epoch: Optional[float] = None) -> None:
        control = self.p.runtime_control
        if (
            control is not None
            and control.stop_reason
            and self.state
            not in {
                "DRAINING",
                "STOPPED_FLAT",
                "MANUAL_INTERVENTION",
            }
        ):
            self.request_drain(control.stop_reason, now)
        if self.p.run_deadline_monotonic is not None and now >= self.p.run_deadline_monotonic:
            self.request_drain("run_duration_elapsed", now)
        if self._active_order is not None and self.state not in {
            "RECOVERING",
            "MANUAL_INTERVENTION",
        }:
            action = self.deadline.action(now)
            recovery_exit = bool(
                getattr(self, "_recovery_only", False)
                and self._order_roles.get(self._active_order.ref) == "recovery_exit"
            )
            if recovery_exit and action in {"cancel", "unknown"}:
                self._enter_manual_monitor("recovery_exit_deadline_requires_new_plan", now)
                return
            if action == "cancel":
                if self._reserve(
                    entry=False,
                    emergency=self.state in {"EXIT_PENDING", "DRAINING"},
                    emergency_key=f"cancel:{self._active_order.ref}",
                ):
                    self.cancel(self._active_order)
                    self.deadline.cancel_requested(now)
                    self._record(
                        "orders", {"event": "cancel_requested", "ref": self._active_order.ref}
                    )
                else:
                    self._transition("MANUAL_INTERVENTION", "cancel_budget_exhausted", now)
            elif action == "unknown":
                self._enter_unknown("cancel_confirmation_timeout", now)
        if self.state == "OPEN" and self._fill_bounds is not None:
            unrealized = self._unrealized_pnl()
            risk_ok, risk_reason = self._risk_admission()
            stop_hit = False
            take_profit = False
            if unrealized is not None and self._stop_distance is not None:
                price_pnl = unrealized / (self.p.multiplier * max(self._gross_position_lots(), 1))
                stop_hit = price_pnl <= -self._stop_distance
                take_profit = price_pnl >= 1.5 * self._stop_distance
            if not risk_ok:
                self._request_exit(risk_reason, now, emergency=True)
            elif stop_hit:
                self._request_exit("stop_loss", now, emergency=True)
            elif self._fill_bounds.maximum_expired(now, self.p.maximum_hold_seconds):
                self._request_exit("maximum_hold", now, emergency=True)
            elif event_epoch is not None and self._current_session_end - event_epoch <= 30.0:
                self._request_exit("session_end", now, emergency=True)
            elif self._fill_bounds.normal_exit_allowed(now, self.p.minimum_hold_seconds):
                if self.p.purpose == "engineering_smoke":
                    self._request_exit(
                        "engineering_smoke_minimum_hold_complete", now, emergency=False
                    )
                else:
                    normal_exit = take_profit
                    if self.last_fusion is not None and self.last_fusion.score is not None:
                        normal_exit = normal_exit or abs(self.last_fusion.score) < self.p.exit_score
                        normal_exit = (
                            normal_exit or self.last_fusion.direction == -self._position_direction
                        )
                    if normal_exit:
                        self._request_exit("normal_signal", now, emergency=False)
        if self.state == "COOLDOWN" and self._cooldown_started is not None:
            if now - self._cooldown_started >= self.p.cooldown_seconds:
                if self.p.mode == "simnow":
                    self._begin_reconciliation(
                        "flat_release", "second_reconciliation_required", now
                    )
                else:
                    self._transition("FLAT", "cooldown_complete", now)
        if self.state == "DRAINING":
            if self._active_order is None and self._gross_position_lots() == 0:
                if self.p.mode == "simnow":
                    self._begin_reconciliation("drain_flat", "drain_reconciliation_required", now)
                else:
                    self._transition("STOPPED_FLAT", "drain_reconciled_flat", now)
                    if self.state == "STOPPED_FLAT":
                        self.env.runstop()
            elif self._active_order is None and self._gross_position_lots() != 0:
                self._request_exit("controlled_drain", now, emergency=True)
            elif (
                self._drain_started is not None
                and now - self._drain_started >= self.p.drain_timeout_seconds
            ):
                self._transition("MANUAL_INTERVENTION", "drain_timeout_with_residual", now)

    def notify_idle(self) -> None:
        now = self._clock.monotonic_now()
        self._advance_time(now, self._clock.utc_now())
        if self.state == "RECOVERING":
            if self._reconciliation_phase != "execution_recovery_complete":
                self._request_reconciliation(now)
            if (
                self._reconciliation_started is not None
                and now - self._reconciliation_started >= self.p.reconciliation_timeout_seconds
            ):
                self._enter_manual_monitor("reconciliation_timeout", now)
        elif self.state == "MANUAL_INTERVENTION":
            self._request_reconciliation(now)
        if self.last_quote is not None and self._current_session_id:
            quote_age = now - self.last_quote.recv_monotonic
            if quote_age > float(self.p.max_quote_age_seconds):
                self.confirmation.reset()
                self._block("quote_receive_age_gt_2s")
            if (
                quote_age > float(self.p.exit_quote_age_seconds)
                and self._gross_position_lots() != 0
            ):
                self._request_exit("market_data_stale", now, emergency=True)

    def request_drain(self, reason: str, now: Optional[float] = None) -> None:
        now = self._clock.monotonic_now() if now is None else float(now)
        if self.state in {"STOPPED_FLAT", "MANUAL_INTERVENTION"}:
            return
        self._drain_started = self._drain_started or now
        self._transition("DRAINING", reason, now)
        if (
            self._active_order is not None
            and self._order_roles.get(self._active_order.ref) == "entry"
        ):
            if self.deadline.cancel_requested_at is None and self._reserve(
                entry=False,
                emergency=True,
                emergency_key=f"cancel:{self._active_order.ref}",
            ):
                self.cancel(self._active_order)
                self.deadline.cancel_requested(now)

    def notify_order(self, order) -> None:
        role = self._order_roles.get(order.ref, "unknown")
        status = order.getstatusname()
        cycle_id = getattr(self, "_order_cycles", {}).get(order.ref) or order.info.get(
            "execution_cycle_id"
        )
        external_order_id = order.info.get("external_order_id")
        order_sys_id = (
            order.info.get("order_sys_id")
            or order.info.get("ctp_order_sys_id")
            or order.info.get("venue_order_id")
            or external_order_id
        )
        record = {
            "ref": order.ref,
            "cycle_id": cycle_id,
            "account_fingerprint": self.p.account_fingerprint or None,
            "trading_day": self.p.trading_day or None,
            "connection_generation": self.p.connection_generation or None,
            "instrument": self.p.instrument or self.data._name,
            "exchange": "CZCE" if self.p.mode == "simnow" else None,
            "role": role,
            "normal_cycle": role in {"entry", "exit"},
            "status": status,
            "size": abs(float(order.size)),
            "executed_size": abs(float(order.executed.size)),
            "executed_price": float(order.executed.price or 0.0),
            "commission": float(order.executed.comm or 0.0),
            "time_in_force": order.info.get("time_in_force", "GFD"),
            "offset": order.info.get("offset"),
            "external_order_id": external_order_id,
            "ctp_order_sys_id": order_sys_id,
            "ctp_order_ref": order.info.get("ctp_order_ref"),
            "ctp_front_id": order.info.get("ctp_front_id", order.info.get("front_id")),
            "ctp_session_id": order.info.get("ctp_session_id", order.info.get("session_id")),
            "ctp_exchange_id": order.info.get("ctp_exchange_id", order.info.get("exchange_id")),
            "ctp_instrument_id": self.p.instrument or self.data._name,
        }
        record["ctp_identity_complete"] = all(
            record.get(name) not in {None, ""}
            for name in (
                "cycle_id",
                "ctp_order_sys_id",
                "ctp_order_ref",
                "ctp_front_id",
                "ctp_session_id",
                "ctp_exchange_id",
                "ctp_instrument_id",
            )
        )
        self._orders.append(record)
        self._record("orders", record)
        _publish_trade_logger_context_if_ready(self)
        executed = abs(float(order.executed.size))
        now = float(self._clock.monotonic_now())
        if role == "recovery_exit" and bool(order.info.get("execution_unknown")):
            self._enter_manual_monitor("recovery_exit_execution_unknown", now)
            return
        if role == "entry" and executed > 0 and self._fill_bounds is None:
            earliest = self._entry_sent_monotonic
            if (
                earliest is None
                or not math.isfinite(float(earliest))
                or not math.isfinite(now)
                or now < float(earliest)
            ):
                self._enter_unknown("entry_fill_time_unproven", now)
                return
            self._fill_bounds = FillTimeBounds(earliest, now, "send_to_callback_bounds", False)
            self._entry_price = float(order.executed.price)
            atr = self.last_minute.atr14 if self.last_minute is not None else None
            self._stop_distance = max(3.0 * self.p.tick_size, float(atr or 0.0))
            self._position_direction = 1 if order.isbuy() else -1
        if (
            order.status == order.Partial
            and role == "entry"
            and self.deadline.cancel_requested_at is None
        ):
            if self._reserve(
                entry=False,
                emergency=True,
                emergency_key=f"cancel:{order.ref}",
            ):
                self.cancel(order)
                self.deadline.cancel_requested(now)
            return
        if order.alive() or order.ref in self._order_terminal_refs:
            return
        self._order_terminal_refs.add(order.ref)
        self.deadline.confirmed_terminal()
        if self._active_order is not None and self._active_order.ref == order.ref:
            self._active_order = None
        if role == "entry":
            if executed > 0:
                self._exit_requotes_used = 0
                self._transition("OPEN", "entry_fill_confirmed", now)
            elif self.state == "DRAINING":
                pass
            else:
                self._cooldown_started = now
                self._transition("COOLDOWN", "entry_terminal_without_fill", now)
        elif role in {"exit", "recovery_exit"}:
            residual = self._gross_position_lots()
            if residual == 0:
                if role == "recovery_exit":
                    self._begin_execution_recovery_completion(now)
                elif self.p.mode == "simnow":
                    self._begin_reconciliation("closed", "post_close_reconciliation_required", now)
                else:
                    self._cooldown_started = now
                    self._transition("COOLDOWN", "exit_fill_confirmed", now)
            elif role == "recovery_exit":
                self._enter_manual_monitor("recovery_exit_terminal_with_residual", now)
            elif self._exit_requotes_used < int(self.p.max_exit_requotes):
                self._exit_requotes_used += 1
                self._transition(
                    "DRAINING",
                    f"residual_exit_requote_{self._exit_requotes_used}",
                    now,
                )
                self._request_exit("residual_partial_close", now, emergency=True)
            else:
                self._enter_unknown("exit_terminal_with_residual", now)

    def notify_trade(self, trade) -> None:
        if not trade.isclosed:
            return
        gross = float(trade.pnl)
        net = float(trade.pnlcomm)
        fee = float(trade.commission)
        cycle_id = getattr(self, "_active_cycle_id", None)
        record = {
            "trade_ref": trade.ref,
            "cycle_id": cycle_id,
            "size": float(trade.size),
            "gross_pnl": gross,
            "commission": fee,
            "net_pnl": net,
            "hypothetical": self.p.mode == "replay",
            "trading_day": self.p.trading_day,
            "account_fingerprint": self.p.account_fingerprint or None,
            "connection_generation": self.p.connection_generation or None,
            "instrument": self.p.instrument or self.data._name,
            "exchange": "CZCE" if self.p.mode == "simnow" else None,
            "ctp_identity_source": "post_close_reconciliation_queries",
            "ctp_identity_complete": False,
            "order_identities": [],
            "trade_identities": [],
        }
        self._trades.append(record)
        self._record("trades", record)
        _publish_trade_logger_context_if_ready(self)
        if self.p.risk_store is not None:
            try:
                self.p.risk_store.record_closed_trade(gross, fee)
            except Exception as exc:
                self._latch_risk_failure(exc)

    def _begin_execution_recovery_completion(self, now: float) -> None:
        """Queue the SDK's two-query flatness proof without blocking this callback."""

        plan = getattr(self, "_recovery_plan", None)
        token = str(plan.get("recovery_token_sha256") or "") if isinstance(plan, dict) else ""
        request = getattr(self.broker, "request_execution_recovery_completion", None)
        if not re.fullmatch(r"[0-9a-f]{64}", token) or not callable(request):
            self._transition("MANUAL_INTERVENTION", "recovery_completion_unavailable", now)
            return
        self._reconciliation_phase = "execution_recovery_complete"
        self._reconciliation_started = now
        try:
            receipt = request(
                self.notify_execution_recovery_completion,
                recovery_token_sha256=token,
            )
        except Exception:
            receipt = None
        if not isinstance(receipt, dict) or receipt.get("queued") is not True:
            self._transition("MANUAL_INTERVENTION", "recovery_completion_not_queued", now)
            return
        self._transition("RECOVERING", "sdk_recovery_flatness_proof_pending", now)

    def notify_execution_recovery_completion(self, result: dict[str, Any]) -> bool:
        """Stop only after the SDK has atomically completed recovery as flat."""

        now = float(self._clock.monotonic_now())
        if (
            self._reconciliation_phase != "execution_recovery_complete"
            or not isinstance(result, dict)
            or set(result) != {"completed", "status", "error_code"}
            or result.get("completed") is not True
            or result.get("status") != "completed"
            or result.get("error_code") is not None
        ):
            self._transition("MANUAL_INTERVENTION", "recovery_completion_unproven", now)
            return False
        self._recovery_completion = dict(result)
        self._transition("STOPPED_FLAT", "sdk_recovery_completed_flat", now)
        self.env.runstop()
        return True

    def notify_reconciliation(self, snapshot: dict[str, Any]) -> bool:
        """Consume an already-complete public SDK/Store reconciliation summary."""

        query_results = dict(snapshot.get("query_results") or snapshot.get("queries") or {})
        query_ids = []
        queries_complete = True
        for name in ("account", "positions", "orders", "trades"):
            result = dict(query_results.get(name) or {})
            raw_request_id = result.get("request_id")
            try:
                parsed_request_id = int(raw_request_id)
            except (TypeError, ValueError):
                parsed_request_id = 0
            request_id_value = str(parsed_request_id) if parsed_request_id > 0 else ""
            if isinstance(raw_request_id, bool) or not request_id_value:
                queries_complete = False
            query_ids.append(f"{name}:{request_id_value}")
            queries_complete = queries_complete and (
                result.get("complete") is True
                and result.get("is_last_seen") is True
                and result.get("timed_out") is False
                and result.get("unsupported") is not True
                and result.get("error_code") in {None, "", 0, "0"}
            )
        if (
            len(set(query_ids)) != 4
            or len({item.split(":", 1)[1] for item in query_ids if ":" in item}) != 4
        ):
            queries_complete = False
        composite_request_id = "|".join(query_ids)
        order_rows = list(dict(query_results.get("orders") or {}).get("records") or ())
        trade_rows = list(dict(query_results.get("trades") or {}).get("records") or ())

        def complete_ctp_row(row: Any, groups: tuple[tuple[str, ...], ...]) -> bool:
            return isinstance(row, dict) and all(
                any(row.get(name) not in {None, ""} for name in names) for names in groups
            )

        def row_matches_contract(row: dict[str, Any]) -> bool:
            instrument = str(row.get("instrument_id") or row.get("InstrumentID") or "").upper()
            exchange = str(row.get("exchange_id") or row.get("ExchangeID") or "").upper()
            return instrument == str(self.p.instrument).upper() and exchange in {"CZCE", "ZCE"}

        def order_sys_id(value: Any) -> str:
            text = str(value or "").strip()
            return text.rsplit(":", 1)[-1] if text else ""

        order_identities = [
            {
                "instrument": str(
                    row.get("instrument_id") or row.get("InstrumentID") or ""
                ).upper(),
                "exchange": str(row.get("exchange_id") or row.get("ExchangeID") or "").upper(),
                "front_id": str(row.get("front_id") or row.get("FrontID") or ""),
                "session_id": str(row.get("session_id") or row.get("SessionID") or ""),
                "order_ref": str(
                    row.get("order_ref") or row.get("OrderRef") or row.get("ctp_order_ref") or ""
                ),
                "order_sys_id": order_sys_id(
                    row.get("external_order_id") or row.get("OrderSysID") or row.get("order_sys_id")
                ),
            }
            for row in order_rows
            if row_matches_contract(row)
            and complete_ctp_row(
                row,
                (
                    ("instrument_id", "InstrumentID"),
                    ("exchange_id", "ExchangeID"),
                    ("front_id", "FrontID"),
                    ("session_id", "SessionID"),
                    ("order_ref", "OrderRef", "ctp_order_ref"),
                    ("external_order_id", "OrderSysID", "order_sys_id"),
                ),
            )
        ]
        trade_identities = [
            {
                "instrument": str(
                    row.get("instrument_id") or row.get("InstrumentID") or ""
                ).upper(),
                "exchange": str(row.get("exchange_id") or row.get("ExchangeID") or "").upper(),
                "trade_id": str(row.get("trade_id") or row.get("TradeID") or ""),
                "order_sys_id": order_sys_id(
                    row.get("external_order_id") or row.get("OrderSysID") or row.get("order_sys_id")
                ),
            }
            for row in trade_rows
            if row_matches_contract(row)
            and complete_ctp_row(
                row,
                (
                    ("instrument_id", "InstrumentID"),
                    ("exchange_id", "ExchangeID"),
                    ("trade_id", "TradeID"),
                    ("external_order_id", "OrderSysID", "order_sys_id"),
                ),
            )
        ]
        order_identity_complete = bool(order_identities)
        trade_identity_complete = bool(trade_identities)
        phase = str(self._reconciliation_phase or "")
        active_cycle_id = str(getattr(self, "_active_cycle_id", "") or "")
        cycle_binding_complete = phase not in {"closed", "unknown_resolution"}
        if phase in {"closed", "unknown_resolution"}:
            cycle_orders = [
                item
                for item in getattr(self, "_orders", ())
                if item.get("cycle_id") == active_cycle_id
                and item.get("ctp_identity_complete") is True
                and item.get("account_fingerprint") == self.p.account_fingerprint
                and item.get("trading_day") == self.p.trading_day
                and item.get("connection_generation") == self.p.connection_generation
                and str(item.get("instrument") or "").upper() == str(self.p.instrument).upper()
                and str(item.get("exchange") or "").upper() == "CZCE"
            ]
            query_orders = {item["order_sys_id"]: item for item in order_identities}
            matched_roles: dict[str, dict[str, Any]] = {}
            matched_local_orders: dict[str, Mapping[str, Any]] = {}
            for item in cycle_orders:
                sys_id = order_sys_id(item.get("ctp_order_sys_id") or item.get("external_order_id"))
                query_row = query_orders.get(sys_id)
                if (
                    query_row
                    and query_row["front_id"] == str(item.get("ctp_front_id") or "")
                    and query_row["session_id"] == str(item.get("ctp_session_id") or "")
                    and query_row["order_ref"] == str(item.get("ctp_order_ref") or "")
                ):
                    matched_roles[str(item.get("role") or "")] = query_row
                    matched_local_orders[sys_id] = item
            local_order_ids = {
                order_sys_id(item.get("ctp_order_sys_id") or item.get("external_order_id"))
                for item in cycle_orders
            }
            matched_order_ids = set(matched_local_orders)
            matched_trades = [
                item for item in trade_identities if item["order_sys_id"] in matched_order_ids
            ]
            trade_order_ids = {item["order_sys_id"] for item in matched_trades}
            executed_order_ids = {
                sys_id
                for sys_id, item in matched_local_orders.items()
                if float(item.get("executed_size") or 0.0) > 0
            }
            cycle_binding_complete = bool(
                active_cycle_id
                and local_order_ids
                and local_order_ids == matched_order_ids
                and executed_order_ids.issubset(trade_order_ids)
                and (
                    phase != "closed"
                    or (
                        {"entry", "exit"}.issubset(matched_roles)
                        and matched_order_ids == trade_order_ids
                        and len({item["trade_id"] for item in matched_trades}) >= 2
                    )
                )
            )
            if cycle_binding_complete:
                order_identities = list(matched_roles.values())
                trade_identities = matched_trades
                order_identity_complete = True
                trade_identity_complete = bool(matched_trades) or not executed_order_ids
        session = dict(snapshot.get("session") or {})
        snapshot_hash = str(
            snapshot.get("reconciliation_fingerprint") or snapshot.get("snapshot_hash") or ""
        )
        if not snapshot_hash and snapshot.get("evidence_complete") is True:
            snapshot_hash = hashlib.sha256(
                json.dumps(
                    {
                        "positions": snapshot.get("positions"),
                        "orders": snapshot.get("orders"),
                        "trades": snapshot.get("trades"),
                    },
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()

        complete = (
            queries_complete and snapshot.get("evidence_complete", snapshot.get("complete")) is True
        )
        raw_position_lots = snapshot.get("position_lots")
        summary_counts_present = bool(
            not isinstance(raw_position_lots, bool)
            and isinstance(raw_position_lots, (int, float))
            and math.isfinite(float(raw_position_lots))
            and float(raw_position_lots) >= 0.0
            and all(
                type(snapshot.get(name)) is int and snapshot[name] >= 0
                for name in (
                    "active_order_count",
                    "unknown_intent_count",
                    "unmatched_trade_count",
                )
            )
        )
        if summary_counts_present:
            position_lots = float(raw_position_lots)
            active_order_count = snapshot["active_order_count"]
            unknown_intent_count = snapshot["unknown_intent_count"]
            unmatched_trade_count = snapshot["unmatched_trade_count"]
        else:
            position_lots = math.inf
            active_order_count = unknown_intent_count = unmatched_trade_count = -1
        flat_flag = snapshot.get("flat")
        flat = (
            summary_counts_present
            and (flat_flag is True or (flat_flag is None and position_lots == 0))
            and position_lots == 0
            and active_order_count == 0
            and len(snapshot.get("nonzero_positions") or ()) == 0
            and len(snapshot.get("active_orders") or ()) == 0
            and unknown_intent_count == 0
            and unmatched_trade_count == 0
        )
        identity = snapshot_hash
        request_id = str(snapshot.get("request_id") or composite_request_id)
        reconciliation_identity = (
            str(
                snapshot.get("connection_generation") or session.get("connection_generation") or ""
            ),
            str(snapshot.get("account_fingerprint") or session.get("account_fingerprint") or ""),
            str(snapshot.get("trading_day") or session.get("trading_day") or ""),
        )
        expected_account = _account_core(self.p.account_fingerprint)
        observed_account = _account_core(reconciliation_identity[1])
        try:
            observed_generation = int(reconciliation_identity[0])
        except (TypeError, ValueError):
            observed_generation = 0
        identity_matches = (
            observed_generation > 0
            and (
                not self.p.connection_generation
                or observed_generation == int(self.p.connection_generation)
            )
            and (not expected_account or observed_account == expected_account)
            and bool(observed_account)
            and len(reconciliation_identity[2]) == 8
            and reconciliation_identity[2].isdigit()
            and (not self.p.trading_day or reconciliation_identity[2] == str(self.p.trading_day))
        )
        if request_id and request_id in self._reconciliation_request_ids_seen:
            return False
        if (
            not complete
            or not flat
            or not identity
            or not request_id
            or not all(reconciliation_identity)
            or not identity_matches
            or not cycle_binding_complete
        ):
            self._reconciliation_hash = ""
            self._reconciliation_count = 0
            return False
        if (
            identity == self._reconciliation_hash
            and reconciliation_identity == self._reconciliation_identity
        ):
            self._reconciliation_count += 1
        else:
            self._reconciliation_hash = identity
            self._reconciliation_count = 1
            self._reconciliation_identity = reconciliation_identity
        self._reconciliation_request_id = request_id
        self._reconciliation_request_ids_seen.add(request_id)
        self._reconciliation_round_request_ids.append(request_id)
        if self._reconciliation_count < 2:
            self._last_reconciliation_requested = None
            return False
        now = float(snapshot.get("completed_monotonic", self._clock.monotonic_now()))
        account_core = _account_core(reconciliation_identity[1])
        bound_account = f"acct_{account_core}" if account_core else ""
        cycle_evidence = {
            "cycle_id": active_cycle_id or None,
            "account_fingerprint": bound_account,
            "trading_day": reconciliation_identity[2],
            "connection_generation": int(reconciliation_identity[0]),
            "instrument": str(self.p.instrument).upper(),
            "exchange": "CZCE",
            "order_identities": sorted(
                order_identities,
                key=lambda item: (
                    item["order_sys_id"],
                    item["front_id"],
                    item["session_id"],
                    item["order_ref"],
                ),
            ),
            "trade_identities": sorted(
                trade_identities,
                key=lambda item: (item["trade_id"], item["order_sys_id"]),
            ),
        }
        cycle_identity_sha256 = (
            hashlib.sha256(
                json.dumps(
                    cycle_evidence,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if phase == "closed" and cycle_binding_complete
            else None
        )
        proof = {
            "phase": self._reconciliation_phase,
            "complete": True,
            "request_ids": list(self._reconciliation_round_request_ids[-2:]),
            "distinct_request_ids": len(set(self._reconciliation_round_request_ids[-2:])) == 2,
            "snapshot_hash": identity,
            **cycle_evidence,
            "cycle_identity_sha256": cycle_identity_sha256,
            "ctp_order_identity_complete": order_identity_complete,
            "ctp_trade_identity_complete": trade_identity_complete,
            "cycle_binding_complete": cycle_binding_complete,
        }
        self._reconciliation_proofs.append(proof)
        _publish_trade_logger_context_if_ready(self)
        if phase == "closed" and cycle_identity_sha256:
            for trade in reversed(self._trades):
                if (
                    trade.get("cycle_id") == active_cycle_id
                    and trade.get("hypothetical") is False
                    and trade.get("ctp_identity_complete") is not True
                ):
                    trade.update(
                        {
                            **cycle_evidence,
                            "cycle_identity_sha256": cycle_identity_sha256,
                            "ctp_identity_complete": True,
                        }
                    )
                    self._record(
                        "trades",
                        {
                            "event": "reconciliation_cycle_binding",
                            **cycle_evidence,
                            "cycle_identity_sha256": cycle_identity_sha256,
                        },
                    )
                    break
        for row in order_rows:
            self._record(
                "orders",
                {
                    "event": "reconciliation_ctp_identity",
                    "request_id": request_id,
                    "InstrumentID": row.get("InstrumentID", row.get("instrument_id")),
                    "ExchangeID": row.get("ExchangeID", row.get("exchange_id")),
                    "FrontID": row.get("FrontID", row.get("front_id")),
                    "SessionID": row.get("SessionID", row.get("session_id")),
                    "OrderRef": row.get("OrderRef", row.get("order_ref")),
                    "OrderSysID": row.get("OrderSysID", row.get("external_order_id")),
                    "ctp_identity_complete": order_identity_complete,
                },
            )
        for row in trade_rows:
            self._record(
                "trades",
                {
                    "event": "reconciliation_ctp_identity",
                    "request_id": request_id,
                    "InstrumentID": row.get("InstrumentID", row.get("instrument_id")),
                    "ExchangeID": row.get("ExchangeID", row.get("exchange_id")),
                    "TradeID": row.get("TradeID", row.get("trade_id")),
                    "OrderSysID": row.get("OrderSysID", row.get("external_order_id")),
                    "ctp_identity_complete": trade_identity_complete,
                },
            )
        self._reconciliation_count = 0
        self._reconciliation_hash = ""
        self._reconciliation_started = None
        if self._reconciliation_phase == "closed":
            self._cooldown_started = now
            self._transition("COOLDOWN", "post_close_reconciled", now)
        elif self._reconciliation_phase == "flat_release":
            self._transition("FLAT", "flat_release_reconciled", now)
        elif self._reconciliation_phase == "drain_flat":
            self._transition("STOPPED_FLAT", "drain_reconciled_flat", now)
            if self.state == "STOPPED_FLAT":
                self.env.runstop()
        elif self._reconciliation_phase == "unknown_resolution":
            self._unknown_intents = 0
            self._active_order = None
            self.deadline.confirmed_terminal()
            if self._unknown_origin_was_draining:
                self._transition("STOPPED_FLAT", "unknown_resolved_flat", now)
                if self.state == "STOPPED_FLAT":
                    self.env.runstop()
            else:
                self._cooldown_started = now
                self._transition("COOLDOWN", "unknown_resolved_flat", now)
        elif self._reconciliation_phase == "manual_monitor":
            if getattr(self, "_recovery_only", False):
                self._begin_execution_recovery_completion(now)
            else:
                self._transition("STOPPED_FLAT", "manual_read_only_reconciled_flat", now)
                if self.state == "STOPPED_FLAT":
                    self.env.runstop()
        return True

    def _begin_reconciliation(self, phase: str, reason: str, now: float) -> None:
        self._reconciliation_phase = phase
        self._reconciliation_started = now
        self._reconciliation_count = 0
        self._reconciliation_hash = ""
        self._reconciliation_identity = None
        self._reconciliation_round_request_ids = []
        self._last_reconciliation_requested = None
        self._reconciliation_requests_issued = 0
        self._transition("RECOVERING", reason, now)
        self._request_reconciliation(now)

    def _request_reconciliation(self, now: float) -> None:
        if (
            self._last_reconciliation_requested is not None
            and now - self._last_reconciliation_requested < self.p.reconciliation_request_interval
        ):
            return
        if (
            self._reconciliation_phase == "unknown_resolution"
            and self._reconciliation_requests_issued
            >= int(self.p.maximum_unknown_reconciliation_rounds)
        ):
            self._enter_manual_monitor("unknown_reconciliation_two_rounds_exhausted", now)
            return
        method = getattr(self.broker, "request_ctp_reconciliation", None)
        if not callable(method):
            method = getattr(self.broker, "request_reconciliation", None)
        if not callable(method):
            self._block("broker_reconciliation_api_missing")
            return
        # The Broker owns the non-blocking query lane and invokes this callback
        # later from its Cerebro-thread ``next`` hook.  No CTP query may run
        # synchronously inside a Strategy callback.
        try:
            accepted = method(self.notify_reconciliation)
        except TypeError:
            accepted = method()
        self._last_reconciliation_requested = now
        self._reconciliation_requests_issued += 1
        if accepted is False or (isinstance(accepted, dict) and accepted.get("queued") is not True):
            self._block("broker_reconciliation_request_rejected")

    def stop(self) -> None:
        provider = self.p.session_state_provider
        if callable(provider):
            try:
                terminal = provider()
                self._terminal_session_state = dict(terminal) if isinstance(terminal, dict) else {}
            except Exception:
                self._terminal_session_state = {}
                self._block("terminal_session_state_unavailable")
        if self.p.mode == "shadow" and self._orders:
            self._transition("MANUAL_INTERVENTION", "shadow_order_invariant_breached")
        if (
            self._recovery_only
            and self._recovery_completion is None
            and self.state != "MANUAL_INTERVENTION"
        ):
            self._transition("MANUAL_INTERVENTION", "recovery_completion_missing")
        if self._gross_position_lots() != 0 and self.state != "MANUAL_INTERVENTION":
            self._transition("MANUAL_INTERVENTION", "engine_stopped_with_position")
        _publish_trade_logger_context_if_ready(self, force=True)

    @staticmethod
    def _finite_lots(value: Any) -> int | None:
        """Normalize an exact, non-negative local-cache contract quantity."""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
            return None
        return int(numeric)

    @staticmethod
    def _cached_mapping_value(mapping: Mapping[str, Any], data: Any) -> Any:
        """Look up a feed using the local cache's object or stable-name key."""
        candidates = (data, getattr(data, "_name", None), getattr(data, "_dataname", None))
        for key in candidates:
            # Feed ``==`` builds a Backtrader line operation and can dereference
            # a not-yet-populated current bar.  Only literal cache-key tests
            # are safe in startup reporting.
            if key is None or (isinstance(key, str) and not key):
                continue
            try:
                value = mapping.get(key)
            except (AttributeError, TypeError):
                value = None
            if value is not None:
                return value
        return None

    def _cached_report_position_lots(self) -> tuple[int | None, bool]:
        """Return local cached gross exposure without calling ``getposition``.

        Live CTP brokers may refresh synchronously from ``getposition``.  The
        generic report path is intentionally forbidden from doing that.  New
        broker caches expose ``position_legs`` so a dual-side account retains
        both legs; an older cache can only prove a net position and is marked
        incomplete rather than silently reporting a hedge as flat.
        """
        report_data = self._report_data()
        if report_data is None:
            return None, False
        getter = getattr(self.broker, "get_cached_report_state", None)
        if not callable(getter):
            return None, False
        try:
            state = getter()
        except Exception:
            return None, False
        if not isinstance(state, Mapping):
            return None, False

        legs = state.get("position_legs")
        if isinstance(legs, Mapping):
            cached_legs = self._cached_mapping_value(legs, report_data)
            if isinstance(cached_legs, Mapping):
                long_position = cached_legs.get("long")
                short_position = cached_legs.get("short")
                long_lots = self._finite_lots(
                    long_position.get("size")
                    if isinstance(long_position, Mapping)
                    else getattr(long_position, "size", 0)
                )
                short_lots = self._finite_lots(
                    short_position.get("size")
                    if isinstance(short_position, Mapping)
                    else getattr(short_position, "size", 0)
                )
                if long_lots is not None and short_lots is not None:
                    return long_lots + short_lots, True

        positions = state.get("positions")
        cached_position = (
            self._cached_mapping_value(positions, report_data)
            if isinstance(positions, Mapping)
            else None
        )
        raw_net_lots = (
            cached_position.get("size")
            if isinstance(cached_position, Mapping)
            else getattr(cached_position, "size", None)
        )
        try:
            net_lots = self._finite_lots(abs(float(raw_net_lots)))
        except (TypeError, ValueError):
            net_lots = None
        if net_lots is None:
            return None, False
        get_param = getattr(self.broker, "get_param", None)
        mode = str(get_param("position_mode", "net") if callable(get_param) else "net").lower()
        return net_lots, mode != "dual_side"

    def _report_context(self) -> dict[str, Any]:
        """Return SA-specific evidence for TradeLogger's report extension.

        TradeLogger owns the generic runtime snapshot and freezes the final
        report.  This strategy only supplies the controlled CTP state needed
        by the Iteration 22 admission, reconciliation, and G3/G4 judges.
        """
        report_data = self._report_data()
        cached_position_lots, position_cache_complete = self._cached_report_position_lots()
        base = {
            "strategy": type(self).__name__,
            "candidate_id": self.p.candidate_id,
            "mode": self.p.mode,
            "purpose": self.p.purpose,
            "instrument": self.p.instrument or getattr(report_data, "_name", None),
            "trading_day": self.p.trading_day,
            "account_fingerprint": self.p.account_fingerprint or None,
            "state": self.state,
            "state_reason": self.state_reason,
            "position_lots": cached_position_lots,
            "position_lots_cache_complete": position_cache_complete,
            "active_order": self._active_order.ref if self._active_order is not None else None,
            "unknown_intents": self._unknown_intents,
            "invalid_quotes": self._invalid_quotes,
            "block_counts": dict(sorted(self._block_counts.items())),
            "closed_bars": len(self.closed_bars),
            "quote_window_seconds": quote_window_span(self.quote_window.quotes),
            "orders": list(self._orders),
            "trades": list(self._trades),
            "state_history": list(self._state_history),
            "prediction_kind": "uncalibrated_score",
            "research_status": self.p.research_status,
            "evidence_failure_count": self._evidence_failure_count,
            "evidence_failure_reason": self._evidence_failure_reason or None,
            "risk_persistence_ok": bool(
                self.p.risk_store is not None and self.p.risk_store.persistence_ok
            ),
            "risk_failure_count": self._risk_failure_count,
            "risk_failure_reason": self._risk_failure_reason or None,
            "volatile_emergency_write_keys": sorted(
                getattr(self.p.risk_store, "volatile_emergency_keys", ())
                if self.p.risk_store is not None
                else ()
            ),
            "reconciliation_proofs": list(self._reconciliation_proofs),
            "terminal_session_state": dict(self._terminal_session_state),
            "engineering_trigger_fired": self._engineering_trigger_fired,
            "session_calendar_sha256": self.p.session_calendar_sha256 or None,
            "exit_requotes_used": self._exit_requotes_used,
            "trade_logger_context": {
                "published": self._trade_logger_context_published,
                "failure_count": self._trade_logger_context_failure_count,
                "last_error": self._trade_logger_context_last_error,
            },
            "execution_recovery": {
                "recovery_only": self._recovery_only,
                "status": (
                    self._recovery_plan.get("status")
                    if isinstance(self._recovery_plan, dict)
                    else None
                ),
                "execution_cycle_id": (
                    self._recovery_plan.get("execution_cycle_id")
                    if isinstance(self._recovery_plan, dict)
                    else None
                ),
                "completed": bool(
                    isinstance(self._recovery_completion, dict)
                    and self._recovery_completion.get("completed") is True
                ),
                "normal_closed_cycles": 0 if self._recovery_only else None,
            },
            "observation_evidence": {
                "profile": self.p.environment_profile or None,
                "trading_day": self.p.trading_day or None,
                "expected_connection_generation": self.p.connection_generation or None,
                "observed_connection_generations": sorted(self._observation_generations),
                "first_valid_quote_utc": (
                    datetime.fromtimestamp(self._observation_first_event, timezone.utc).isoformat()
                    if self._observation_first_event is not None
                    else None
                ),
                "last_valid_quote_utc": (
                    datetime.fromtimestamp(self._observation_last_event, timezone.utc).isoformat()
                    if self._observation_last_event is not None
                    else None
                ),
                "valid_session_seconds": sum(self._observation_seconds_by_session.values()),
                "valid_seconds_by_session": dict(
                    sorted(self._observation_seconds_by_session.items())
                ),
                "qualified_quotes": self._qualified_quotes,
                "qualified_completed_bars": self._qualified_bars,
                "first_completed_bar_end_utc": (
                    datetime.fromtimestamp(self._first_bar_end, timezone.utc).isoformat()
                    if self._first_bar_end is not None
                    else None
                ),
                "last_completed_bar_end_utc": (
                    datetime.fromtimestamp(self._last_bar_end, timezone.utc).isoformat()
                    if self._last_bar_end is not None
                    else None
                ),
            },
        }
        if self.p.mode in {"shadow", "replay"}:
            base.pop("trades", None)
            base["fills_forbidden"] = self.p.mode == "shadow"
            base["hypothetical_fills"] = False
            base["pnl_fields_emitted"] = False
        else:
            base["hypothetical_fills"] = False
            base["gross_pnl"] = sum(item["gross_pnl"] for item in self._trades)
            base["net_pnl"] = sum(item["net_pnl"] for item in self._trades)
        return base

    def _mark_trade_logger_context_dirty(self) -> None:
        self._trade_logger_context_dirty = True
        self._trade_logger_context_revision += 1

    def _record_trade_logger_context_failure(
        self, reason: str, exc: Exception | None = None
    ) -> None:
        """Persist a bounded, secret-free diagnostic for a failed publication."""
        exception_type = type(exc).__name__ if exc is not None else None
        diagnostic = f"{reason}:{exception_type or ''}".rstrip(":")
        observer_result = "returned_false" if reason == "update_rejected" else None
        self._trade_logger_context_last_error = diagnostic
        if self._trade_logger_context_last_failure_recorded == diagnostic:
            return
        self._trade_logger_context_last_failure_recorded = diagnostic
        self._trade_logger_context_failure_count += 1
        # EvidenceWriter is already the controlled durable diagnostics lane.
        # Do not retain provider exception text, which can contain credentials.
        self._record(
            "risk_events",
            {
                "event": "trade_logger_context_publish_failed",
                "reason": reason,
                "exception_type": exception_type,
                "observer_result": observer_result,
                "failure_count": self._trade_logger_context_failure_count,
            },
        )

    def _report_data(self) -> Any | None:
        """Read a feed only when its line aliases are available locally."""
        try:
            return self.data
        except (AttributeError, IndexError):
            return None

    def _publish_trade_logger_context(self, *, force: bool = False) -> bool:
        """Publish SA state into the live generic report without broker I/O.

        The extension is updated on state/bar/order/trade transitions and once
        per 128 valid quotes.  A rejected/raised observer update stays dirty,
        but retry cadence follows the last attempt rather than every quote.
        """
        qualified_quotes = int(getattr(self, "_qualified_quotes", 0))
        context_revision = int(getattr(self, "_trade_logger_context_revision", 0))
        last_attempted_revision = int(getattr(self, "_trade_logger_last_attempted_revision", -1))
        last_attempted_quotes = int(getattr(self, "_trade_logger_last_attempted_quotes", 0))
        if (
            not force
            and context_revision == last_attempted_revision
            and qualified_quotes - last_attempted_quotes < 128
        ):
            return True
        observer = getattr(getattr(self, "stats", None), "trade_logger", None)
        update = getattr(observer, "update_report_context", None)
        if not callable(update):
            self._trade_logger_last_attempted_quotes = qualified_quotes
            self._trade_logger_last_attempted_revision = context_revision
            self._trade_logger_context_failed_since_success = True
            self._record_trade_logger_context_failure("observer_unavailable")
            return False
        try:
            accepted = bool(update(self._report_context(), namespace="sa_midfreq"))
        except Exception as exc:
            self._trade_logger_last_attempted_quotes = qualified_quotes
            self._trade_logger_last_attempted_revision = context_revision
            self._trade_logger_context_failed_since_success = True
            self._record_trade_logger_context_failure("update_raised", exc)
            return False
        self._trade_logger_last_attempted_quotes = qualified_quotes
        self._trade_logger_last_attempted_revision = context_revision
        if not accepted:
            self._trade_logger_context_failed_since_success = True
            self._record_trade_logger_context_failure("update_rejected")
            return False
        self._trade_logger_context_dirty = False
        self._trade_logger_context_published = True
        self._trade_logger_context_failed_since_success = False
        self._trade_logger_context_last_error = None
        self._trade_logger_context_last_failure_recorded = None
        return True
