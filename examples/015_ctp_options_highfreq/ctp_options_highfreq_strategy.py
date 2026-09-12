"""Tick-only C/P/F parity candidate used by the Iteration 25 replay.

The example owns only candidate-local screening, confirmation count, and the
zero-write replay projection.  All CTP quote validation, generation-scoped
cohort admission, and trusted-time rechecks are delegated to
``backtrader.feeds.CtpQuoteCohortValidator``.  It does not call a CTP client,
maintain an order journal, or claim a local replay intent is an external trade.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import backtrader as bt

try:
    from .execution_timing import TimingFact, project_timing, projection_to_dict
except ImportError:  # Direct execution through this directory's run.py.
    from execution_timing import TimingFact, project_timing, projection_to_dict


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite decimal value: {value!r}")
    return result


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def canonical_sha256(value: Mapping[str, Any]) -> str:
    """Return the stable identity used by this candidate's frozen fixture."""

    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _quote_as_dict(quote: bt.feeds.CtpQuoteEvidence) -> dict[str, Any]:
    """Make immutable public cohort evidence JSON-safe for the local report."""

    return {
        "symbol": quote.symbol,
        "exchange": quote.exchange,
        "asset_type": quote.asset_type,
        "bid": quote.bid,
        "ask": quote.ask,
        "bid_size": quote.bid_size,
        "ask_size": quote.ask_size,
        "last": quote.last,
        "lower_limit": quote.lower_limit,
        "upper_limit": quote.upper_limit,
        "source_epoch": quote.source_epoch,
        "receive_epoch": quote.receive_epoch,
        "receive_monotonic_ns": quote.receive_monotonic_ns,
        "ingest_seq": quote.ingest_seq,
        "connection_generation": quote.connection_generation,
        "subscription_epoch": quote.subscription_epoch,
        "trading_day": quote.trading_day,
        "action_day": quote.action_day,
        "clock_domain_id": quote.clock_domain_id,
        "rules_hash": quote.rules_hash,
        "source": quote.source,
        "event_time_source": quote.event_time_source,
        "source_clock_error_ms": quote.source_clock_error_ms,
        "receive_clock_error_ms": quote.receive_clock_error_ms,
    }


def _quote_fingerprint(quote: bt.feeds.CtpQuoteEvidence) -> tuple[Any, ...]:
    """Identify repeated raw economic evidence without revalidating a quote.

    ``ingest_seq`` and receipt times are intentionally excluded: a redelivery
    cannot become the candidate's second independent confirmation merely by
    receiving a new transport sequence.
    """

    return (
        quote.symbol,
        quote.bid,
        quote.ask,
        quote.bid_size,
        quote.ask_size,
        quote.last,
        quote.lower_limit,
        quote.upper_limit,
        quote.source_epoch,
        quote.connection_generation,
        quote.subscription_epoch,
        quote.trading_day,
        quote.action_day,
        quote.clock_domain_id,
        quote.rules_hash,
        quote.source,
        quote.event_time_source,
        quote.source_clock_error_ms,
        quote.receive_clock_error_ms,
    )


def parity_screen(
    cohort: Mapping[str, bt.feeds.CtpQuoteEvidence],
    *,
    bundle: Mapping[str, Any],
    entry_buffer_cny: Any,
    total_reserve_cny: Any,
) -> dict[str, Any]:
    """Calculate the frozen conversion/reversal screens from executable sides."""

    future = cohort[str(bundle["future"]["symbol"])]
    call = cohort[str(bundle["call"]["symbol"])]
    put = cohort[str(bundle["put"]["symbol"])]
    multiplier = _decimal(bundle["future"]["multiplier"])
    strike = _decimal(bundle["strike"])
    discount = _decimal(bundle["discount_factor"])
    reserve = _decimal(total_reserve_cny)
    threshold = _decimal(entry_buffer_cny)

    conversion_gross = multiplier * (
        _decimal(call.bid) - _decimal(put.ask) - discount * (_decimal(future.ask) - strike)
    )
    reversal_gross = multiplier * (
        _decimal(put.bid) - _decimal(call.ask) + discount * (_decimal(future.bid) - strike)
    )

    def row(direction: str, gross: Decimal) -> dict[str, Any]:
        net = gross - reserve
        return {
            "direction": direction,
            "gross_cny": _decimal_text(gross),
            "total_reserve_cny": _decimal_text(reserve),
            "net_screen_cny": _decimal_text(net),
            "entry_buffer_cny": _decimal_text(threshold),
            "eligible": net > threshold,
        }

    return {
        "conversion": row("conversion", conversion_gross),
        "reversal": row("reversal", reversal_gross),
    }


class CtpOptionsHighfreqStrategy(bt.Strategy):
    """A channel-mode strategy whose ordinary intent can arise only from ticks."""

    # No SDK risk projection is available in this self-contained replay.  Keep
    # the design deadlines visible as an offline signal projection, but never
    # turn them into a synthetic cancel, hedge, or second execution ledger.
    _OFFLINE_DEADLINES_MS = {
        "leg_timeout_ms": 1_000,
        "unhedged_timeout_ms": 3_000,
        "holding_timeout_ms": 60_000,
    }

    params = (
        ("mode", "replay"),
        ("candidate_id", ""),
        ("symbols", ()),
        ("exchange_id", ""),
        ("bundle", None),
        ("bundle_hash", ""),
        ("tick_sizes", None),
        ("lots_per_leg", 1),
        ("max_quote_age_ms", 250),
        ("max_cross_leg_skew_ms", 100),
        ("max_source_age_ms", 250),
        ("max_source_skew_ms", 100),
        ("max_source_clock_error_ms", 5),
        ("complete_cohort_confirmations", 2),
        ("entry_buffer_cny", 20),
        ("total_reserve_cny", 20),
    )

    def __init__(self) -> None:
        self._symbols = tuple(str(symbol) for symbol in self.p.symbols)
        self._bundle = dict(self.p.bundle or {})
        self._tick_sizes = dict(self.p.tick_sizes or {})
        try:
            role_asset_types = {
                str(self._bundle["future"]["symbol"]): "future",
                str(self._bundle["call"]["symbol"]): "option",
                str(self._bundle["put"]["symbol"]): "option",
            }
            exchange_id = str(self.p.exchange_id)
            if not exchange_id or set(role_asset_types) != set(self._symbols):
                raise ValueError("frozen bundle identity is incomplete")
            expected_legs = tuple(
                bt.feeds.CtpCohortLeg(
                    symbol=symbol,
                    exchange=exchange_id,
                    price_tick=float(self._tick_sizes[symbol]),
                    asset_type=role_asset_types[symbol],
                )
                for symbol in self._symbols
            )
            policy = bt.feeds.CtpCohortPolicy(
                max_receive_age_ms=float(self.p.max_quote_age_ms),
                max_receive_skew_ms=float(self.p.max_cross_leg_skew_ms),
                max_source_age_ms=float(self.p.max_source_age_ms),
                max_source_skew_ms=float(self.p.max_source_skew_ms),
                max_source_clock_error_ms=float(self.p.max_source_clock_error_ms),
                max_receive_clock_error_ms=float(self.p.max_source_clock_error_ms),
            )
            self._cohort_validator = bt.feeds.CtpQuoteCohortValidator(
                expected_legs=expected_legs,
                expected_rules_hash=str(self.p.bundle_hash),
                policy=policy,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid public CTP cohort configuration") from exc

        self._last_confirmed_updates: dict[str, tuple[Any, ...] | None] = dict.fromkeys(
            self._symbols
        )
        self._confirmation_scope: tuple[int, int] | None = None
        self._confirmation_direction: str | None = None
        self._confirmed_cohorts = 0
        self._ordinary_intents: list[dict[str, Any]] = []
        self._intent_consumed = False
        self._reject_counts: Counter[str] = Counter()
        self._last_rejection = ""
        self._last_cohort: dict[str, Any] | None = None
        self._last_screen: dict[str, Any] | None = None
        self._cohort_screen_history: list[dict[str, Any]] = []
        self._last_clock_now: bt.feeds.CtpCohortNow | None = None
        self._clock_domain_id: str | None = None
        self._clock_rejection_latched = False
        self._clock_rejection_reason = ""
        self._offline_deadline_projection: dict[str, Any] = {
            "status": "OFFLINE_SIGNAL_ONLY",
            "risk_projection_available": False,
            "basis": "no_sdk_read_only_risk_projection",
            **self._OFFLINE_DEADLINES_MS,
            "risk_actions": [],
        }
        self._timing_facts: tuple[TimingFact, ...] = ()
        self._last_idle_lower_ns: int | None = None
        self._timing_projection = self._project_timing(now_upper_ns=None)
        self.callback_counts = {"tick": 0, "bar": 0, "idle": 0, "next": 0}

    def _project_timing(self, *, now_upper_ns: int | None) -> Any:
        """Project local timing evidence without creating an execution path."""

        return project_timing(
            self._timing_facts,
            now_upper_ns=now_upper_ns,
            expected_provider_id="",
            expected_source_id="",
            expected_scope_id="",
            expected_clock_domain_id="",
            intent_id=str(self.p.candidate_id),
            leg_ids=self._symbols,
            last_idle_lower_ns=self._last_idle_lower_ns,
        )

    def notify_tick(self, tick: Any) -> None:
        """Consume one tick and, only here, possibly create an ordinary intent."""

        self.callback_counts["tick"] += 1
        try:
            now = self._now_from_tick(tick)
        except (TypeError, ValueError):
            self._reject("TRUSTED_NOW_INVALID", reset_confirmation=True)
            return

        if not self._accept_clock_now(now, source="tick"):
            return
        if self._clock_rejection_latched:
            self._last_rejection = self._clock_rejection_reason
            return

        result = self._cohort_validator.ingest(tick, now=now)
        if result.cohort is None:
            self._record_cohort_rejection(result.reason)
            return
        self._consider_cohort(result.cohort, now=now)

    def notify_bar(self, _bar: Any) -> None:
        """Record compatibility bar callbacks without creating ordinary intent."""

        self.callback_counts["bar"] += 1

    def notify_idle(self, now: Any = None) -> None:
        """Recheck cached evidence with trusted time without creating intent.

        Cerebro's compatibility hook has no time argument.  The absence of a
        provider is therefore a fail-closed clock failure; the last tick's
        receive time is never reused as ``now``.  A real SDK risk projection is
        intentionally not emulated by this offline example.
        """

        self.callback_counts["idle"] += 1
        try:
            trusted_now = self._cohort_now_from_value(now)
        except (TypeError, ValueError):
            self._timing_projection = self._project_timing(now_upper_ns=None)
            self._latch_clock_rejection(
                "TRUSTED_NOW_REQUIRED" if now is None else "TRUSTED_NOW_INVALID"
            )
            return

        if not self._accept_clock_now(trusted_now, source="idle"):
            self._timing_projection = self._project_timing(now_upper_ns=None)
            return

        self._timing_projection = self._project_timing(now_upper_ns=trusted_now.now_monotonic_ns)
        self._last_idle_lower_ns = trusted_now.now_monotonic_ns

        result = self._cohort_validator.validate_at(now=trusted_now)
        if result.cohort is None:
            self._reject(str(result.reason or "COHORT_RECHECK_FAILED"), reset_confirmation=True)
            return

        # A valid idle recheck is deliberately observational.  It cannot
        # promote cached edge into an ordinary signal or claim a risk action.
        self._last_rejection = ""

    def next(self) -> None:
        """Channel-line compatibility hook; it must never create an intent."""

        self.callback_counts["next"] += 1

    @staticmethod
    def _now_from_tick(tick: Any) -> bt.feeds.CtpCohortNow:
        """Use explicit same-domain receipt evidence supplied with this tick."""

        return CtpOptionsHighfreqStrategy._cohort_now_from_value(
            {
                "now_monotonic_ns": getattr(tick, "cohort_decision_now_monotonic_ns", None),
                "now_epoch": getattr(tick, "cohort_decision_now_epoch", None),
                "clock_domain_id": getattr(tick, "cohort_decision_now_clock_domain_id", None),
                "receive_clock_error_ms": getattr(
                    tick, "cohort_decision_now_receive_clock_error_ms", None
                ),
                "receive_clock_quality": getattr(
                    tick, "cohort_decision_now_receive_clock_quality", None
                ),
                "freshness_verified": getattr(tick, "cohort_decision_now_freshness_verified", None),
            }
        )

    @staticmethod
    def _cohort_now_from_value(value: Any) -> bt.feeds.CtpCohortNow:
        """Normalize explicit trusted clock evidence without a local fallback."""

        if isinstance(value, bt.feeds.CtpCohortNow):
            return value
        if value is None:
            raise ValueError("trusted idle clock evidence is required")

        def read(name: str) -> Any:
            if isinstance(value, Mapping):
                return value.get(name)
            return getattr(value, name, None)

        return bt.feeds.CtpCohortNow(
            now_monotonic_ns=read("now_monotonic_ns"),
            now_epoch=read("now_epoch"),
            clock_domain_id=read("clock_domain_id"),
            receive_clock_error_ms=read("receive_clock_error_ms"),
            receive_clock_quality=read("receive_clock_quality"),
            freshness_verified=read("freshness_verified"),
        )

    def _accept_clock_now(self, now: bt.feeds.CtpCohortNow, *, source: str) -> bool:
        """Require one monotonic clock domain for all tick and idle checks."""

        if self._clock_domain_id is not None and now.clock_domain_id != self._clock_domain_id:
            reason = "IDLE_CLOCK_DOMAIN_MISMATCH" if source == "idle" else "CLOCK_DOMAIN_CHANGED"
            self._latch_clock_rejection(reason)
            return False
        if (
            self._last_clock_now is not None
            and now.now_monotonic_ns < self._last_clock_now.now_monotonic_ns
        ):
            reason = "IDLE_CLOCK_REGRESSION" if source == "idle" else "CLOCK_REGRESSION"
            self._latch_clock_rejection(reason)
            return False
        self._clock_domain_id = now.clock_domain_id
        self._last_clock_now = now
        return True

    def _latch_clock_rejection(self, reason: str) -> None:
        """Latch a clock safety failure until an explicit new strategy instance."""

        self._clock_rejection_latched = True
        self._clock_rejection_reason = reason
        self._reject(reason, reset_confirmation=True)

    def _record_cohort_rejection(self, reason: str | None) -> None:
        if reason == bt.feeds.CtpCohortReason.WAITING_FOR_LEGS:
            self._last_rejection = "WAITING_ALL_LEGS"
            return
        if reason == bt.feeds.CtpCohortReason.WAITING_FOR_ALL_LEGS_NEW:
            # A normal barrier may observe one newly updated leg before the
            # remaining legs arrive.  It is not a duplicate sequence by
            # itself; retain the prior economic streak until the next full
            # cohort is assembled.  Exact sequence repeats are rejected by
            # the validator with DUPLICATE_OR_OUT_OF_ORDER below.
            self._last_rejection = "WAITING_ALL_LEGS_NEW"
            return
        self._reject(str(reason or "UNKNOWN_QUOTE_REJECTION"), reset_confirmation=True)

    def _consider_cohort(
        self, cohort: bt.feeds.CtpQuoteCohort, *, now: bt.feeds.CtpCohortNow
    ) -> None:
        scope = (cohort.connection_generation, cohort.subscription_epoch)
        if self._confirmation_scope is not None and scope != self._confirmation_scope:
            # A reconnect/subscription renewal starts a distinct evidence
            # domain.  Candidate confirmation cannot aggregate cohorts across
            # those domains even though each cohort is independently valid.
            self._reset_confirmation()
        quotes = cohort.quotes
        updates = {symbol: _quote_fingerprint(quotes[symbol]) for symbol in self._symbols}
        if any(updates[symbol] == self._last_confirmed_updates[symbol] for symbol in self._symbols):
            self._reject("DUPLICATE_COHORT_PAYLOAD", reset_confirmation=True)
            return

        self._last_confirmed_updates = dict(updates)
        self._confirmation_scope = scope
        self._last_cohort = {
            "cohort_id": cohort.cohort_id,
            "sequences": {symbol: quotes[symbol].ingest_seq for symbol in self._symbols},
            "quotes": {symbol: _quote_as_dict(quotes[symbol]) for symbol in self._symbols},
            "confirmation_index": self._confirmed_cohorts + 1,
        }
        self._last_rejection = ""

        screen = parity_screen(
            cohort.quotes,
            bundle=self._bundle,
            entry_buffer_cny=self.p.entry_buffer_cny,
            total_reserve_cny=self.p.total_reserve_cny,
        )
        self._last_screen = screen
        eligible_directions = self._eligible_directions(screen)
        direction = eligible_directions[0] if len(eligible_directions) == 1 else None
        self._cohort_screen_history.append(
            {
                "cohort_id": cohort.cohort_id,
                "direction": direction,
                "screen": screen,
            }
        )
        if direction is None:
            reason = (
                "NO_SIGNAL_NET_EDGE" if not eligible_directions else "AMBIGUOUS_SIGNAL_DIRECTION"
            )
            self._reject(reason, reset_confirmation=True)
            return

        if self._confirmation_direction is not None and direction != self._confirmation_direction:
            self._reject("SIGNAL_DIRECTION_CHANGED", reset_confirmation=True)
            # The switching cohort is the first valid confirmation for the new
            # direction; it cannot complete a two-round streak by itself.
            self._last_confirmed_updates = dict(updates)
            self._confirmation_scope = scope
            self._confirmation_direction = direction
            self._confirmed_cohorts = 1
            self._last_cohort["confirmation_index"] = 1
            return

        self._confirmation_direction = direction
        self._confirmed_cohorts += 1
        self._last_cohort["confirmation_index"] = self._confirmed_cohorts
        if self._confirmed_cohorts < int(self.p.complete_cohort_confirmations):
            return
        if self._intent_consumed:
            self._last_rejection = "MAX_CYCLES_REACHED"
            return

        final_gate = self._cohort_validator.validate_at(now=now)
        if final_gate.cohort is None:
            self._reject(str(final_gate.reason or "COHORT_RECHECK_FAILED"), reset_confirmation=True)
            return

        screen = parity_screen(
            final_gate.cohort.quotes,
            bundle=self._bundle,
            entry_buffer_cny=self.p.entry_buffer_cny,
            total_reserve_cny=self.p.total_reserve_cny,
        )
        self._last_screen = screen
        final_directions = self._eligible_directions(screen)
        final_direction = final_directions[0] if len(final_directions) == 1 else None
        if final_direction != direction:
            self._reject("SIGNAL_RECHECK_CHANGED", reset_confirmation=True)
            return

        self._intent_consumed = True
        anchor_ns = max(quote.receive_monotonic_ns for quote in final_gate.cohort.quotes.values())
        deadline_projection = self._deadline_projection(anchor_ns)
        self._ordinary_intents.append(
            {
                "intent_id": f"{self.p.candidate_id}:{self._last_cohort['cohort_id']}:{direction}",
                "cohort_id": self._last_cohort["cohort_id"],
                "direction": direction,
                "screen": screen[direction],
                "execution_status": "NOT_SUBMITTED_REPLAY",
                "reason": "tick_only_two_same_direction_complete_cohorts",
                "deadline_projection": deadline_projection,
            }
        )

    def _reset_confirmation(self) -> None:
        self._confirmed_cohorts = 0
        self._last_confirmed_updates = dict.fromkeys(self._symbols)
        self._confirmation_scope = None
        self._confirmation_direction = None

    @staticmethod
    def _eligible_directions(screen: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
        return tuple(
            direction for direction in ("conversion", "reversal") if screen[direction]["eligible"]
        )

    def _deadline_projection(self, anchor_ns: int) -> dict[str, Any]:
        """Return explicit offline deadlines without pretending to execute them."""

        return {
            **self._offline_deadline_projection,
            "anchor_monotonic_ns": anchor_ns,
            "leg_deadline_monotonic_ns": anchor_ns + 1_000_000_000,
            "unhedged_deadline_monotonic_ns": anchor_ns + 3_000_000_000,
            "holding_deadline_monotonic_ns": anchor_ns + 60_000_000_000,
        }

    def _reject(self, reason: str, *, reset_confirmation: bool) -> None:
        self._last_rejection = reason or "UNKNOWN_QUOTE_REJECTION"
        self._reject_counts[self._last_rejection] += 1
        if reset_confirmation:
            self._reset_confirmation()

    def replay_report(self) -> dict[str, Any]:
        """Return the candidate-local, JSON-safe replay projection."""

        return {
            "candidate_id": str(self.p.candidate_id),
            "mode": str(self.p.mode),
            "callback_counts": dict(self.callback_counts),
            "confirmed_cohorts": self._confirmed_cohorts,
            "ordinary_intent_count": len(self._ordinary_intents),
            "ordinary_intents": list(self._ordinary_intents),
            "reject_counts": dict(sorted(self._reject_counts.items())),
            "last_rejection": self._last_rejection or None,
            "last_cohort": self._last_cohort,
            "last_screen": self._last_screen,
            "cohort_screen_history": list(self._cohort_screen_history),
            "offline_deadline_projection": dict(self._offline_deadline_projection),
            "timing_projection": projection_to_dict(self._timing_projection),
            "clock_rejection_latched": self._clock_rejection_latched,
            "clock_rejection_reason": self._clock_rejection_reason or None,
            "normal_order_submissions": 0,
            "risk_reduction_requests": 0,
            "actual_fills": 0,
            "execution_basis": "none",
            "pnl_fields_emitted": False,
            "hft_status": "NOT_ADMITTED",
            "hft_no_go_reason": "local_replay_has_no_queue_latency_or_actual_fill_evidence",
        }
