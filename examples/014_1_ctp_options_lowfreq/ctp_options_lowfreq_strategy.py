"""Closed-bar C/P/F conversion/reversal strategy used only by this example.

The module deliberately has no imports from another ``examples`` directory.
Its replay orders are local Backtrader orders; a replay result is therefore
not evidence of a CTP write, a fill, or economic profitability.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import backtrader as bt
from backtrader.feeds import (
    BarBarrierPolicy,
    BarEvidence,
    BarLeg,
    ClockMapping,
    MultiLegBarBarrier,
)

try:
    from .execution_timing import (
        BarPriceEnvelope,
        ClockObservation,
        ClockSafetyError,
        ConfirmationProjection,
        ExecutionFact,
        ExecutionToken,
        ExecutionWindow,
        HoldProjection,
        ScopedClock,
        SessionRiskPolicy,
        TimingContractError,
        TokenProjection,
        classify_execution_facts,
        economic_scores,
        execution_price_allowed,
        freeze_bar_envelopes,
        project_risk_bar,
        replay_fill_status,
    )
except ImportError:  # Direct execution through this directory's run.py.
    from execution_timing import (
        BarPriceEnvelope,
        ClockObservation,
        ClockSafetyError,
        ConfirmationProjection,
        ExecutionFact,
        ExecutionToken,
        ExecutionWindow,
        HoldProjection,
        ScopedClock,
        SessionRiskPolicy,
        TimingContractError,
        TokenProjection,
        classify_execution_facts,
        economic_scores,
        execution_price_allowed,
        freeze_bar_envelopes,
        project_risk_bar,
        replay_fill_status,
    )


class CtpOptionsLowfreqStrategy(bt.Strategy):
    """A single-basket, closed-15-minute-bar C/P/F research strategy.

    The historical residual window is read before the current closed bar is
    appended.  This makes the current bar eligible for evaluation but prevents
    it from changing its own mean or standard deviation.
    """

    params = (
        ("candidate_id", "ctp-options-lowfreq-replay-v1"),
        ("future_symbol", "CZCE.SA701"),
        ("call_symbol", "CZCE.SA701C1080"),
        ("put_symbol", "CZCE.SA701P1080"),
        ("strike", 1000.0),
        ("multiplier", 1.0),
        ("discount", 1.0),
        ("window", 40),
        ("entry_z", 2.5),
        ("exit_z", 0.5),
        ("minimum_score", 20.0),
        ("round_trip_cost", 20.0),
        ("fee_schedule", None),
        ("exit_reserve", 0.0),
        ("financing_reserve", 0.0),
        ("model_reserve", 0.0),
        ("projected_entry_capital", 6500.0),
        ("capital_limit", 10000.0),
        ("ordinary_limit", 8000.0),
        ("recovery_reserve", 2000.0),
        ("price_tick", 1.0),
        ("bar_minutes", 15),
        ("confirmation_bars", 2),
        ("minimum_holding_minutes", 30),
        ("max_holding_bars", 8),
        ("first_send_seconds", 1),
        ("completion_seconds", 60),
        ("minimum_hold_seconds", 1800),
        ("maximum_hold_seconds", 7200),
        ("risk_bar_max_age_seconds", 910),
        ("session_stop_entry_seconds", 1800),
        ("session_exit_seconds", 600),
        ("session_handover_seconds", 180),
        ("exchange", "CZCE"),
        ("rules_hash", "ctp-options-replay-rules-v1"),
        ("price_ticks", None),
        ("exchange_limits", None),
        ("clock_provider", None),
    )

    def __init__(self):
        def positive_int(value: object, name: str) -> int:
            if type(value) is not int or value <= 0:
                raise TimingContractError(f"{name} must be a positive integer")
            return value

        try:
            entry_z = float(self.p.entry_z)
            minimum_score = float(self.p.minimum_score)
        except (TypeError, ValueError) as exc:
            raise TimingContractError("entry thresholds must be finite numbers") from exc
        if not math.isfinite(entry_z) or entry_z < 2.5:
            raise TimingContractError("entry_z must be at least 2.5")
        if not math.isfinite(minimum_score) or minimum_score < 20.0:
            raise TimingContractError("minimum_score must be at least 20")
        first_send_seconds = positive_int(self.p.first_send_seconds, "first_send_seconds")
        completion_seconds = positive_int(self.p.completion_seconds, "completion_seconds")
        bar_minutes = positive_int(self.p.bar_minutes, "bar_minutes")
        minimum_holding_minutes = positive_int(
            self.p.minimum_holding_minutes, "minimum_holding_minutes"
        )
        max_holding_bars = positive_int(self.p.max_holding_bars, "max_holding_bars")
        minimum_hold_seconds = positive_int(self.p.minimum_hold_seconds, "minimum_hold_seconds")
        maximum_hold_seconds = positive_int(self.p.maximum_hold_seconds, "maximum_hold_seconds")
        risk_bar_max_age_seconds = positive_int(
            self.p.risk_bar_max_age_seconds, "risk_bar_max_age_seconds"
        )
        session_stop_entry_seconds = positive_int(
            self.p.session_stop_entry_seconds, "session_stop_entry_seconds"
        )
        session_exit_seconds = positive_int(self.p.session_exit_seconds, "session_exit_seconds")
        session_handover_seconds = positive_int(
            self.p.session_handover_seconds, "session_handover_seconds"
        )
        if first_send_seconds != 1 or completion_seconds != 60:
            raise TimingContractError("entry timing must remain fixed at 1s and 60s")
        if minimum_hold_seconds < 1800:
            raise TimingContractError("minimum_hold_seconds must be at least 1800")
        if maximum_hold_seconds > 7200:
            raise TimingContractError("maximum_hold_seconds must be at most 7200")
        if maximum_hold_seconds < minimum_hold_seconds:
            raise TimingContractError("maximum hold cannot be below minimum hold")
        if minimum_hold_seconds < minimum_holding_minutes * 60:
            raise TimingContractError("seconds minimum hold cannot weaken minutes setting")
        if maximum_hold_seconds > max_holding_bars * bar_minutes * 60:
            raise TimingContractError("seconds maximum hold cannot weaken bars setting")
        if risk_bar_max_age_seconds > 910:
            raise TimingContractError("risk_bar_max_age_seconds must be at most 910")
        expected = (self.p.future_symbol, self.p.call_symbol, self.p.put_symbol)
        self._data_by_symbol = {data._name: data for data in self.datas}
        missing = [symbol for symbol in expected if symbol not in self._data_by_symbol]
        if missing:
            raise ValueError(f"missing required C/P/F feeds: {','.join(missing)}")
        self._history: list[float] = []
        self._state = "FLAT"
        self._cycle_direction: str | None = None
        self._entry_legs: list[dict[str, object]] = []
        self._planned_legs: list[dict[str, object]] = []
        self._leg_index = 0
        self._pending_order = None
        self._pending_order_ref: int | None = None
        self._submission_in_flight = False
        self._entry_bar: int | None = None
        self._entry_completed_at: datetime | None = None
        self._last_closed_timestamp: datetime | None = None
        self._active_basket_id: str | None = None
        self._active_decision_id: str | None = None
        self._exit_execution_window: ExecutionWindow | None = None
        self._entry_confirmation: dict[str, object] | None = None
        self._confirmation_projection = ConfirmationProjection(
            required=int(self.p.confirmation_bars),
            bar_interval_seconds=bar_minutes * 60,
        )
        # ``Strategy._events`` belongs to Backtrader's notification machinery;
        # keep the strategy projection under an unambiguous local name.
        self._cycle_events: list[dict[str, object]] = []
        # ``Strategy._orders`` is an internal order-notification queue.
        self._order_projection: list[dict[str, object]] = []
        self._ordinary_decisions = 0
        self._rejections: list[str] = []
        self._terminal_order_refs: set[int] = set()
        self._barrier = MultiLegBarBarrier(
            expected_legs=tuple(BarLeg(symbol, self.p.exchange) for symbol in expected),
            candidate_id=self.p.candidate_id,
            expected_rules_hash=self.p.rules_hash,
            policy=BarBarrierPolicy(
                timeframe_seconds=float(self.p.bar_minutes) * 60.0, timeout_seconds=10.0
            ),
            clock_mode="replay",
            expected_clock_domain="iter23-replay-clock",
        )
        self._last_decision_input = None
        self._barrier_results: list[dict[str, object]] = []
        # These records are the local-replay evidence projection.  They are
        # deliberately kept in memory: replay must not silently create files
        # or imply that an offline report is an external trading ledger.
        self._bar_cohort_evidence: list[dict[str, object]] = []
        self._indicative_score_evidence: list[dict[str, object]] = []
        self._replay_clock_mapping: ClockMapping | None = None
        self._last_price_envelopes: dict[str, BarPriceEnvelope] = {}
        if self.p.clock_provider is not None and not callable(self.p.clock_provider):
            raise TimingContractError("clock_provider must be callable")
        self._clock = ScopedClock(provider=self.p.clock_provider)
        self._clock_rejection_latched = False
        self._clock_rejection_reason: str | None = None
        self._current_clock_now_ns: int | None = None
        self._decision_scope: tuple[Any, ...] | None = None
        self._execution_window: ExecutionWindow | None = None
        self._hold_projection = HoldProjection(
            expected_legs=(self.p.future_symbol, self.p.call_symbol, self.p.put_symbol),
            minimum_hold_seconds=minimum_hold_seconds,
            maximum_hold_seconds=maximum_hold_seconds,
        )
        self._session_policy = SessionRiskPolicy(
            stop_entry_seconds=session_stop_entry_seconds,
            exit_seconds=session_exit_seconds,
            handover_seconds=session_handover_seconds,
        )
        self._execution_facts: list[ExecutionFact] = []
        self._execution_fact_history: list[ExecutionFact] = []
        self._execution_fact_keys: set[tuple[Any, ...]] = set()
        self._quarantined_execution_facts: list[dict[str, Any]] = []
        # Keep submission identity separate from raw execution history.  Only
        # facts tied to an order returned by the current Backtrader handoff
        # can authorize a subsequent protection leg.
        self._submitted_order_ids_by_leg: dict[str, set[str]] = {}
        self._confirmed_fill_by_leg: dict[str, float] = {}
        self._fill_timing = replay_fill_status()
        self._rejected_execution_possible = False
        self._confirmed_fill_quantity = 0.0
        self._possible_exposure = False
        self._token_projection = TokenProjection()
        self._consumed_token_digest: str | None = None
        self._last_idle_projection: dict[str, Any] = {
            "status": "OFFLINE_SIGNAL_ONLY",
            "risk_projection_available": False,
            "risk_actions": [],
        }
        self._basket_status = "FLAT_UNVERIFIED"
        if session_stop_entry_seconds < 1800:
            raise TimingContractError("session_stop_entry_seconds must be at least 1800")
        if session_exit_seconds < 600:
            raise TimingContractError("session_exit_seconds must be at least 600")
        if session_handover_seconds < 180:
            raise TimingContractError("session_handover_seconds must be at least 180")

    def _snapshot(self) -> tuple[datetime, dict[str, dict[str, float]]]:
        snapshot: dict[str, dict[str, float]] = {}
        timestamps: dict[str, datetime] = {}
        for symbol, data in self._data_by_symbol.items():
            if len(data) <= 0:
                raise ValueError("MISSING_CLOSED_BAR")
            timestamp = data.datetime.datetime(0)
            if timestamp.tzinfo is not None:
                raise ValueError("TIMEZONE_AWARE_BAR_UNSUPPORTED")
            timestamps[symbol] = timestamp.replace(tzinfo=None)
            values = {
                "open": float(data.open[0]),
                "high": float(data.high[0]),
                "low": float(data.low[0]),
                "close": float(data.close[0]),
                "volume": float(data.volume[0]),
            }
            if any(not math.isfinite(value) or value <= 0 for value in values.values()):
                raise ValueError(f"invalid closed bar for {symbol}")
            if values["high"] < values["low"]:
                raise ValueError(f"inverted closed bar for {symbol}")
            snapshot[symbol] = values
        unique_timestamps = set(timestamps.values())
        if len(unique_timestamps) != 1:
            raise ValueError("TRIPLE_LEG_TIMESTAMP_MISMATCH")
        return unique_timestamps.pop(), snapshot

    def _bar_evidence(
        self,
        symbol: str,
        timestamp: datetime,
        values: Mapping[str, float],
        leg_index: int,
    ) -> BarEvidence:
        """Build explicit replay evidence at the feed-to-strategy boundary."""

        # Backtrader's PandasData fixture timestamps are naive.  The public
        # evidence object records the replay domain explicitly and interprets
        # those values as UTC, so no wall-clock or CPU arrival time leaks in.
        end = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
        end = end.astimezone(timezone.utc)
        start = end - timedelta(minutes=int(self.p.bar_minutes))
        sequence = int(len(self)) * 10 + leg_index + 1
        if self._replay_clock_mapping is None:
            self._replay_clock_mapping = ClockMapping(
                mapping_id=f"{self.p.candidate_id}:synthetic-replay-clock",
                wall_utc_at_anchor=end,
                mono_ns_at_anchor=0,
                clock_domain_id="iter23-replay-clock",
                connection_generation=1,
                source="iter23-local-replay-recorded-anchor",
                error_bound_ns=0,
                valid_until_mono_ns=10**18,
                rules_hash=self.p.rules_hash,
                synthetic=True,
            )
        mapping = self._replay_clock_mapping
        elapsed = (end - mapping.wall_utc_at_anchor).total_seconds()
        seal_mono = elapsed + 0.5 + (0.1 * leg_index)
        seal_at = end + timedelta(seconds=0.5 + (0.1 * leg_index))
        return BarEvidence(
            symbol=symbol,
            exchange=self.p.exchange,
            bucket_start=start,
            bucket_end=end,
            available_at=seal_at,
            seal_received_mono=seal_mono,
            seal_received_at=seal_at,
            trading_day=end.strftime("%Y%m%d"),
            generation=1,
            session_segment="replay-day",
            rules_hash=self.p.rules_hash,
            quality="GOOD",
            volume_complete=True,
            first_ingest_seq=sequence,
            last_ingest_seq=sequence,
            quote_cutoff_seq=sequence,
            bar_id=f"{self.p.candidate_id}:{symbol}:{end.isoformat()}:{sequence}",
            bar_sequence=sequence,
            closure_reason="replay_recorded_seal",
            watermark=end + timedelta(seconds=2),
            max_event_time=end - timedelta(microseconds=1),
            open=values["open"],
            high=values["high"],
            low=values["low"],
            close=values["close"],
            volume=values["volume"],
            clock_domain="iter23-replay-clock",
            clock_mode="replay",
            candidate_id=self.p.candidate_id,
            timeframe_seconds=float(self.p.bar_minutes) * 60.0,
            trade_count=1,
            complete=True,
            clock_mapping=mapping,
        )

    def _consume_barrier(self, timestamp: datetime, snapshot: Mapping[str, Mapping[str, float]]):
        result = None
        for index, symbol in enumerate(
            (self.p.future_symbol, self.p.call_symbol, self.p.put_symbol)
        ):
            result = self._barrier.ingest(
                self._bar_evidence(symbol, timestamp, snapshot[symbol], index)
            )
        assert result is not None
        self._barrier_results.append(
            {"reason": result.reason, "ready": result.ready, "reset_warmup": result.reset_warmup}
        )
        self._bar_cohort_evidence.append(
            {
                "candidate_id": self.p.candidate_id,
                "bar_index": len(self),
                "bucket_end": (
                    result.decision_input.bucket_end.isoformat()
                    if result.ready and result.decision_input is not None
                    else timestamp.isoformat()
                ),
                "ready": bool(result.ready),
                "reason": result.reason,
                "reset_warmup": bool(result.reset_warmup),
                "clock_mode": "replay",
                "clock_domain": "iter23-replay-clock",
                "barrier_evidence": (result.decision_input.to_dict() if result.ready else None),
            }
        )
        if not result.ready:
            if result.reset_warmup:
                self._history.clear()
                self._reset_entry_confirmation("BARARRIER_SCOPE_RESET")
            return None
        self._last_decision_input = result.decision_input
        decision_input = result.decision_input
        current_scope = (
            decision_input.trading_day,
            decision_input.generation,
            decision_input.session_segment,
            decision_input.rules_hash,
            decision_input.clock_domain,
        )
        if self._decision_scope is not None and current_scope != self._decision_scope:
            self._reset_entry_confirmation("BARARRIER_SCOPE_CHANGED")
        self._decision_scope = current_scope
        # BarBarrier exposes a frozen same-domain monotonic seal.  This is an
        # offline replay clock anchor, never a local wall-clock fallback.
        ready_mono = float(decision_input.barrier_ready_mono)
        if not math.isfinite(ready_mono) or ready_mono < 0:
            self._reset_entry_confirmation("INVALID_DECISION_CLOCK")
            self._rejections.append("INVALID_DECISION_CLOCK")
            return None
        self._current_clock_now_ns = int(round(ready_mono * 1_000_000_000))
        return result.decision_input

    def _residual(self, snapshot: Mapping[str, Mapping[str, float]]) -> float:
        future = snapshot[self.p.future_symbol]["close"]
        call = snapshot[self.p.call_symbol]["close"]
        put = snapshot[self.p.put_symbol]["close"]
        return call - put - self.p.discount * (future - self.p.strike)

    def _zscore(self, residual: float) -> float | None:
        if len(self._history) < int(self.p.window):
            return None
        sample = self._history[-int(self.p.window) :]
        mean = sum(sample) / len(sample)
        variance = sum((value - mean) ** 2 for value in sample) / (len(sample) - 1)
        if variance <= 0 or not math.isfinite(variance):
            return None
        return (residual - mean) / math.sqrt(variance)

    def _limits(self, snapshot: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, float]]:
        ticks = self.p.price_ticks or dict.fromkeys(snapshot, self.p.price_tick)
        envelopes = freeze_bar_envelopes(
            snapshot,
            ticks=ticks,
            scope=f"{self.p.candidate_id}:{self.p.rules_hash}",
            exchange_limits=self.p.exchange_limits,
        )
        self._last_price_envelopes = envelopes
        return {
            symbol: {"buy": envelope.upper, "sell": envelope.lower}
            for symbol, envelope in envelopes.items()
        }

    def _score(
        self,
        direction: str,
        limits: Mapping[str, Mapping[str, float]],
    ) -> float:
        envelopes = {
            "F": self._last_price_envelopes[self.p.future_symbol],
            "C": self._last_price_envelopes[self.p.call_symbol],
            "P": self._last_price_envelopes[self.p.put_symbol],
        }
        scores = economic_scores(
            envelopes,
            multiplier=self.p.multiplier,
            discount=self.p.discount,
            strike=self.p.strike,
            total_costs=(
                None
                if self.p.fee_schedule is not None
                else {"conversion": self.p.round_trip_cost, "reversal": self.p.round_trip_cost}
            ),
            fee_schedule=self.p.fee_schedule,
            reserves=(
                {
                    "exit": self.p.exit_reserve,
                    "financing": self.p.financing_reserve,
                    "model": self.p.model_reserve,
                }
                if self.p.fee_schedule is not None
                else None
            ),
            minimum_score=self.p.minimum_score,
        )
        return scores[direction].net_cny

    def _record(self, kind: str, **values: object) -> None:
        self._cycle_events.append({"bar": len(self), "kind": kind, **values})

    def _reset_entry_confirmation(self, reason: str | None = None) -> None:
        had_confirmation = (
            self._entry_confirmation is not None or self._confirmation_projection.count
        )
        self._confirmation_projection.reset(reason)
        if had_confirmation and reason is not None:
            self._record("entry_confirmation_reset", reason=reason)
        self._entry_confirmation = None

    def _ordinary_action_allowed(self, timestamp: datetime) -> bool:
        for event in reversed(self._cycle_events):
            if event.get("kind") not in {"entry_decision", "exit_decision"}:
                continue
            return event.get("bar_timestamp") != timestamp.isoformat()
        return True

    def _confirmed_entry(self, direction: str, score: float, timestamp: datetime) -> bool:
        qualified = self._confirmation_projection.accept(
            direction,
            self._decision_scope,
            timestamp,
            qualified=True,
        )
        if qualified:
            self._entry_confirmation = None
            return True
        self._entry_confirmation = {"direction": direction, "timestamp": timestamp}
        self._record(
            "entry_confirmation_pending",
            direction=direction,
            indicative_score=round(score, 6),
            bar_timestamp=timestamp.isoformat(),
        )
        return False

    def _entry_budget_allows(self) -> bool:
        projected = float(self.p.projected_entry_capital)
        ordinary = float(self.p.ordinary_limit)
        capital = float(self.p.capital_limit)
        reserve = float(self.p.recovery_reserve)
        if any(
            not math.isfinite(value) or value < 0
            for value in (projected, ordinary, capital, reserve)
        ):
            return False
        return projected <= ordinary and projected + reserve <= capital

    def _latch_clock_rejection(self, reason: str) -> None:
        self._clock_rejection_latched = True
        self._clock_rejection_reason = reason
        self._rejections.append(reason)
        self._record("rejected", reason=reason)
        self._reset_entry_confirmation(reason)

    def _observe_clock(self, value: Any = None) -> ClockObservation:
        """Observe only an explicit scoped clock; never use a bar timestamp as now."""

        try:
            observation = self._clock.observe(value)
            if self._decision_scope is not None:
                expected_generation = int(self._decision_scope[1])
                expected_domain = str(self._decision_scope[4])
                if observation.generation != expected_generation:
                    raise ClockSafetyError("CLOCK_GENERATION_SCOPE_CHANGED")
                if observation.domain != expected_domain:
                    raise ClockSafetyError("CLOCK_DOMAIN_SCOPE_CHANGED")
                if observation.scope is not None and observation.scope != self._decision_scope:
                    raise ClockSafetyError("CLOCK_DECISION_SCOPE_CHANGED")
        except ClockSafetyError as exc:
            self._latch_clock_rejection(str(exc))
            raise
        self._current_clock_now_ns = observation.monotonic_ns
        return observation

    def set_clock_provider(self, provider: Any) -> None:
        """Install the explicit scoped provider used by no-bar ``notify_idle``."""

        if not callable(provider):
            raise TimingContractError("clock provider must be callable")
        if self._clock.last is not None:
            raise TimingContractError("clock provider cannot change after observation")
        self._clock = ScopedClock(provider=provider)

    def _start_execution_window(self) -> bool:
        if self.p.clock_provider is not None:
            try:
                self._observe_clock()
            except ClockSafetyError:
                return False
        anchor = self._current_clock_now_ns
        if anchor is None or anchor < 0:
            self._latch_clock_rejection("TRUSTED_CLOCK_REQUIRED")
            return False
        try:
            self._execution_window = ExecutionWindow(
                decision_mono_ns=anchor,
                first_send_seconds=int(self.p.first_send_seconds),
                completion_seconds=int(self.p.completion_seconds),
            )
        except TimingContractError as exc:
            self._latch_clock_rejection("INVALID_EXECUTION_WINDOW")
            self._record("rejected", reason="INVALID_EXECUTION_WINDOW", detail=str(exc))
            return False
        return True

    def _execution_gate(self, *, first_leg: bool) -> bool:
        window = self._exit_execution_window if self._state == "EXITING" else self._execution_window
        if window is None:
            return True
        # BackBroker's next-bar callback is a local hypothetical projection;
        # its 15-minute stepping cannot prove a real 1s/60s handoff.  Keep the
        # legacy replay state machine runnable, while the report explicitly
        # labels this timing gate NOT_RUN.  Any caller supplying a trusted live
        # clock uses the strict gate below.
        if (
            self._last_decision_input is not None
            and self._last_decision_input.clock_mode == "replay"
            and self.p.clock_provider is None
        ):
            return True
        if self.p.clock_provider is not None:
            try:
                self._observe_clock()
            except ClockSafetyError:
                return False
        now = self._current_clock_now_ns
        if now is None:
            self._latch_clock_rejection("TRUSTED_CLOCK_REQUIRED")
            return False
        gate = window.gate(
            now,
            "first_send" if first_leg else "remaining_legs",
            possible_exposure=self._possible_exposure,
        )
        if gate.status == "ELIGIBLE_FOR_OTHER_GATES":
            return True
        self._state = "HALTED"
        self._rejections.append(gate.status)
        self._record("halted", reason=gate.status, deadline_ns=gate.deadline_ns)
        if self._possible_exposure:
            self._basket_status = "RECOVERY_REQUIRED"
        return False

    def _record_possible_exposure(self, leg: Mapping[str, object]) -> None:
        now = self._current_clock_now_ns
        if now is None:
            return
        self._possible_exposure = True
        self._hold_projection.record_possible_exposure(str(leg["symbol"]), lower_ns=now)

    def _strict_execution_scope(self, fact: ExecutionFact) -> tuple[bool, str]:
        """Admit only facts bound to the active order and complete scope.

        A fact without a clock provider is not a free-floating replay fill:
        confirmation, hold timing, and protection permission all consume this
        same admitted set.  Foreign facts remain quarantine/risk evidence but
        cannot enter any derived confirmation view.
        """

        submitted_order_ids_by_leg = getattr(self, "_submitted_order_ids_by_leg", {})
        expected_order_ids = set(submitted_order_ids_by_leg.get(fact.leg, ()))
        # A normal BackBroker handoff has already returned an order ref.
        # Include the pending ref defensively for custom synchronous brokers
        # that deliver a fact while the handoff is still in flight.
        if self._pending_order_ref is not None:
            current_leg = (
                self._planned_legs[self._leg_index]
                if self._leg_index < len(self._planned_legs)
                else None
            )
            if current_leg is not None and str(current_leg["symbol"]) == fact.leg:
                expected_order_ids.add(str(self._pending_order_ref))
        if fact.order_id is None:
            return False, "FILL_ORDER_REQUIRED"
        if str(fact.order_id) not in expected_order_ids:
            return False, "FILL_ORDER_MISMATCH"
        if self._decision_scope is None:
            return False, "MISSING_DECISION_SCOPE"
        if self._active_decision_id is None or fact.decision_id != self._active_decision_id:
            return False, "FILL_DECISION_MISMATCH"
        if self._active_basket_id is None or fact.basket_id != self._active_basket_id:
            return False, "FILL_BASKET_MISMATCH"
        expected_generation = int(self._decision_scope[1])
        expected_domain = str(self._decision_scope[4])
        if fact.clock_domain != expected_domain:
            return False, "FILL_CLOCK_DOMAIN_MISMATCH"
        if fact.generation != expected_generation:
            return False, "FILL_CLOCK_GENERATION_MISMATCH"
        if fact.timestamped_fill and self._execution_window is not None:
            if fact.fill_lower_ns < self._execution_window.decision_mono_ns:
                return False, "FILL_BEFORE_DECISION"
            if fact.fill_upper_ns > self._execution_window.completion_deadline_ns:
                return False, "FILL_AFTER_COMPLETION_DEADLINE"
        return True, ""

    def _confirmed_leg_quantity(self, symbol: str) -> float:
        return self._confirmed_fill_by_leg.get(symbol, 0.0)

    def record_execution_fact(self, fact: ExecutionFact | Mapping[str, Any]) -> dict[str, Any]:
        """Consume an explicitly timestamped synthetic fact for offline timing tests.

        This method never sends, cancels, or reconciles an order.  Local
        BackBroker callbacks continue to be hypothetical projections and do not
        reach this path.
        """

        if isinstance(fact, Mapping):
            fill_time = fact.get("fill_time_ns")
            fact = ExecutionFact(
                leg=str(fact.get("leg", "")),
                quantity=fact.get("quantity"),
                status=str(fact.get("status", "unknown")),
                fill_lower_ns=fact.get("fill_lower_ns", fact.get("fill_lower_mono_ns", fill_time)),
                fill_upper_ns=fact.get("fill_upper_ns", fact.get("fill_upper_mono_ns", fill_time)),
                source=str(fact.get("source", fact.get("execution_source", "unknown"))),
                clock_domain=fact.get("clock_domain", fact.get("clock_domain_id")),
                generation=fact.get("generation", fact.get("connection_generation")),
                decision_id=fact.get("decision_id"),
                basket_id=fact.get("basket_id"),
                order_id=fact.get("order_id", fact.get("order_ref")),
                fact_id=fact.get("fact_id", fact.get("execution_id")),
                source_identity=fact.get("source_identity", fact.get("source")),
                quantity_kind=str(fact.get("quantity_kind", "incremental")),
            )
        if not isinstance(fact, ExecutionFact):
            raise TimingContractError("execution fact is required")
        self._execution_fact_history.append(fact)
        if fact.identity_key in self._execution_fact_keys:
            return dict(self._fill_timing)
        self._execution_fact_keys.add(fact.identity_key)
        scope_valid, scope_reason = self._strict_execution_scope(fact)
        # ``_execution_facts`` is the single admitted set consumed by the
        # classifier and all protection permissions.  Keep rejected facts in
        # history/quarantine so they remain visible possible-risk evidence,
        # but never let them contribute quantity or hold timestamps.
        if scope_valid:
            self._execution_facts.append(fact)
        else:
            self._rejected_execution_possible = True
            self._quarantined_execution_facts.append(
                {"fact_id": fact.fact_id, "leg": fact.leg, "reason": scope_reason}
            )
        if fact.timestamped_fill and scope_valid:
            self._hold_projection.record_confirmed_fill(
                fact.leg, fact.fill_lower_ns, fact.fill_upper_ns
            )
            current = self._confirmed_leg_quantity(fact.leg)
            if fact.quantity_kind == "cumulative":
                self._confirmed_fill_by_leg[fact.leg] = max(current, fact.quantity)
            else:
                self._confirmed_fill_by_leg[fact.leg] = current + fact.quantity
        deadline = (
            self._execution_window.completion_deadline_ns
            if self._execution_window is not None
            else 2**63 - 1
        )
        expected_domain = None
        expected_generation = None
        decision_mono_ns = None
        scope_required = getattr(self.p, "clock_provider", None) is not None or any(
            fact.clock_domain is not None or fact.generation is not None
            for fact in self._execution_facts
        )
        if scope_required and self._decision_scope is not None:
            expected_domain = str(self._decision_scope[4])
            expected_generation = int(self._decision_scope[1])
            decision_mono_ns = (
                self._execution_window.decision_mono_ns if self._execution_window else None
            )
        result = classify_execution_facts(
            tuple(self._execution_facts),
            deadline_ns=deadline,
            expected_clock_domain=expected_domain,
            expected_generation=expected_generation,
            decision_mono_ns=decision_mono_ns,
        )
        possible_exposure = result.possible_exposure or self._rejected_execution_possible
        status = result.status
        if possible_exposure and not result.confirmed_quantity:
            status = "FILL_TIMING_UNKNOWN"
        self._fill_timing = {
            "status": status,
            "confirmed_quantity": result.confirmed_quantity,
            "possible_exposure": possible_exposure,
            "source": result.source,
            "reason": scope_reason or result.reason,
        }
        self._confirmed_fill_quantity = result.confirmed_quantity
        return dict(self._fill_timing)

    notify_execution = record_execution_fact
    record_fill = record_execution_fact

    def _risk_idle_projection(self, observation: ClockObservation) -> dict[str, Any]:
        decision_input = self._last_decision_input
        if decision_input is None:
            return {
                "status": "OFFLINE_SIGNAL_ONLY",
                "risk_projection_available": False,
                "risk_actions": [],
                "execution_eligible": False,
                "reason": "NO_CLOSED_BAR",
            }
        session_open = observation.session_open
        price_limits_known = observation.price_limits_known
        # A missing current-session or current-limit observation is unknown;
        # the previously frozen bar envelopes cannot be reused as live facts.
        if session_open is None:
            session_open = False
        if price_limits_known is None:
            price_limits_known = False
        session_evidence = None
        if session_open:
            session_evidence = {
                "scope": observation.session_scope,
                "generation": observation.generation,
                "source": observation.source,
            }
        price_limits_evidence = None
        if price_limits_known:
            price_limits_evidence = {
                "scope": observation.price_limits_scope,
                "generation": observation.generation,
                "source": observation.price_limits_source,
                "reference_identity": observation.price_limits_reference_identity,
            }
        mapping = getattr(decision_input, "clock_mapping", None) or self._replay_clock_mapping
        try:
            projection = project_risk_bar(
                bucket_end=decision_input.bucket_end,
                now=observation,
                session_open=session_open,
                price_limits_known=price_limits_known,
                mapping_error_ns=observation.mapping_error_ns,
                max_age_seconds=int(self.p.risk_bar_max_age_seconds),
                cancel_authority=False,
                clock_mapping=mapping,
                scope=self._decision_scope,
                session_evidence=session_evidence,
                price_limits_evidence=price_limits_evidence,
            )
        except TimingContractError as exc:
            return {
                "status": "OFFLINE_SIGNAL_ONLY",
                "risk_projection_available": False,
                "risk_actions": [],
                "reason": str(exc),
            }
        # This example has no SDK-owned read-only risk projection.  Even a
        # fresh pure-K bar therefore remains a projection and cannot produce a
        # local cancel/hedge/flat action.
        return {
            "status": projection.status,
            "risk_projection_available": False,
            "risk_actions": [],
            "allowed_read_only_actions": projection.allowed_actions,
            "age_upper_seconds": projection.age_upper_seconds,
            "reason": projection.reason,
        }

    def _entry_legs_for(self, direction: str, limits: Mapping[str, Mapping[str, float]]):
        future = self.p.future_symbol
        call = self.p.call_symbol
        put = self.p.put_symbol
        if direction == "conversion":
            order = ((put, "buy"), (future, "buy"), (call, "sell"))
        else:
            order = ((call, "buy"), (future, "sell"), (put, "sell"))
        return [
            {"symbol": symbol, "side": side, "price": limits[symbol][side], "size": 1}
            for symbol, side in order
        ]

    def _start_entry(
        self,
        direction: str,
        limits: Mapping[str, Mapping[str, float]],
        score: float,
        timestamp: datetime,
    ) -> None:
        if not self._entry_budget_allows():
            if "BUDGET_REJECTED" not in self._rejections:
                self._rejections.append("BUDGET_REJECTED")
            self._record("rejected", reason="BUDGET_REJECTED")
            return
        if not self._start_execution_window():
            return
        if self._decision_scope is None:
            self._latch_clock_rejection("MISSING_DECISION_SCOPE")
            return
        decision_input = self._last_decision_input
        if decision_input is None:
            self._latch_clock_rejection("MISSING_DECISION_INPUT")
            return
        token = ExecutionToken(
            candidate=str(self.p.candidate_id),
            trading_day=str(decision_input.trading_day),
            session=str(decision_input.session_segment),
            bar_end=timestamp.isoformat(),
        )
        if not self._token_projection.consume(token):
            self._rejections.append("TOKEN_ALREADY_CONSUMED")
            self._record("rejected", reason="TOKEN_ALREADY_CONSUMED")
            return
        self._consumed_token_digest = token.digest
        self._active_decision_id = token.digest
        self._active_basket_id = token.digest
        self._confirmed_fill_by_leg.clear()
        self._execution_facts.clear()
        self._execution_fact_history.clear()
        self._execution_fact_keys.clear()
        self._quarantined_execution_facts.clear()
        self._submitted_order_ids_by_leg.clear()
        self._rejected_execution_possible = False
        self._confirmed_fill_quantity = 0.0
        self._fill_timing = replay_fill_status()
        self._exit_execution_window = None
        self._state = "ENTERING"
        self._cycle_direction = direction
        self._entry_legs = self._entry_legs_for(direction, limits)
        self._planned_legs = [dict(leg) for leg in self._entry_legs]
        self._leg_index = 0
        self._ordinary_decisions += 1
        self._basket_status = "ORDINARY_ENTRY_PROJECTED"
        self._record(
            "entry_decision",
            direction=direction,
            indicative_score=round(score, 6),
            bar_timestamp=timestamp.isoformat(),
            token_digest=token.digest,
            first_send_deadline_ns=self._execution_window.first_send_deadline_ns,
            completion_deadline_ns=self._execution_window.completion_deadline_ns,
        )
        self._submit_next_leg()

    def _start_exit(
        self,
        limits: Mapping[str, Mapping[str, float]],
        reason: str,
        timestamp: datetime,
        held_minutes: float,
    ) -> None:
        if self._state != "OPEN":
            return
        if self.p.clock_provider is not None:
            try:
                self._observe_clock()
                if self._current_clock_now_ns is None:
                    raise ClockSafetyError("TRUSTED_CLOCK_REQUIRED")
                self._exit_execution_window = ExecutionWindow(
                    decision_mono_ns=self._current_clock_now_ns,
                    first_send_seconds=int(self.p.first_send_seconds),
                    completion_seconds=int(self.p.completion_seconds),
                )
            except (ClockSafetyError, TimingContractError) as exc:
                self._latch_clock_rejection(str(exc))
                return
        self._state = "EXITING"
        self._planned_legs = []
        for leg in reversed(self._entry_legs):
            side = "sell" if leg["side"] == "buy" else "buy"
            symbol = str(leg["symbol"])
            self._planned_legs.append(
                {"symbol": symbol, "side": side, "price": limits[symbol][side], "size": 1}
            )
        self._leg_index = 0
        self._ordinary_decisions += 1
        self._record(
            "exit_decision",
            reason=reason,
            bar_timestamp=timestamp.isoformat(),
            held_minutes=held_minutes,
        )
        self._submit_next_leg()

    def _submit_next_leg(self) -> None:
        if self._state == "HALTED" or self._pending_order is not None or self._submission_in_flight:
            return
        if self._leg_index >= len(self._planned_legs):
            if self._state == "ENTERING":
                self._state = "OPEN"
                self._basket_status = "OPEN_UNVERIFIED"
                self._entry_bar = len(self)
                if self._last_closed_timestamp is None:
                    self._state = "HALTED"
                    self._rejections.append("MISSING_FULL_BASKET_COMPLETION_TIME")
                    self._record("halted", reason="MISSING_FULL_BASKET_COMPLETION_TIME")
                    return
                self._entry_completed_at = self._last_closed_timestamp
                self._record(
                    "basket_open",
                    direction=self._cycle_direction,
                    completed_at=self._entry_completed_at.isoformat(),
                    fill_timing="FILL_TIMING_UNKNOWN",
                    confirmed_fill_quantity=self._confirmed_fill_quantity,
                )
            elif self._state == "EXITING":
                self._state = "FLAT"
                self._basket_status = "LOCAL_BASKET_FLAT_UNVERIFIED"
                self._cycle_direction = None
                self._entry_bar = None
                self._entry_completed_at = None
                self._record("local_basket_flat_unverified", status=self._basket_status)
            return
        leg = self._planned_legs[self._leg_index]
        if not self._execution_gate(first_leg=self._leg_index == 0):
            return
        envelope = self._last_price_envelopes.get(str(leg["symbol"]))
        if envelope is None or not execution_price_allowed(
            envelope, str(leg["side"]), leg["price"]
        ):
            self._state = "HALTED"
            self._rejections.append("PRICE_ENVELOPE_NOT_EXECUTION_ELIGIBLE")
            self._record("halted", reason="PRICE_ENVELOPE_NOT_EXECUTION_ELIGIBLE")
            return
        self._record_possible_exposure(leg)
        data = self._data_by_symbol[str(leg["symbol"])]
        submit = self.buy if leg["side"] == "buy" else self.sell
        submitted_leg_index = self._leg_index
        self._submission_in_flight = True
        try:
            order = submit(
                data=data,
                size=int(leg["size"]),
                exectype=bt.Order.Limit,
                price=float(leg["price"]),
            )
        except Exception:
            order = None
        finally:
            self._submission_in_flight = False
        if order is None:
            self._state = "HALTED"
            self._rejections.append("BROKER_REJECTED_ORDER")
            self._record("halted", reason="BROKER_REJECTED_ORDER")
            return
        self._submitted_order_ids_by_leg.setdefault(str(leg["symbol"]), set()).add(str(order.ref))
        if order.ref in self._terminal_order_refs:
            # A native/broker callback can be delivered before buy/sell returns.
            # ``notify_order`` already matched this exact leg and advanced it.
            if self._state != "HALTED" and self._leg_index != submitted_leg_index:
                self._submit_next_leg()
            return
        if self._state == "HALTED":
            return
        if self._leg_index != submitted_leg_index:
            # Do not overwrite state that an early callback has already advanced.
            self._submit_next_leg()
            return
        self._pending_order = order
        self._pending_order_ref = order.ref

    def _order_matches_current_leg(self, order) -> bool:
        if self._leg_index >= len(self._planned_legs):
            return False
        if self._pending_order_ref is not None and order.ref != self._pending_order_ref:
            return False
        if self._pending_order_ref is None and not self._submission_in_flight:
            return False
        leg = self._planned_legs[self._leg_index]
        symbol = getattr(getattr(order, "data", None), "_name", "")
        expected_side = str(leg["side"])
        expected_size = abs(float(leg["size"]))
        created_size = abs(float(getattr(getattr(order, "created", None), "size", 0.0)))
        return (
            symbol == leg["symbol"]
            and ((expected_side == "buy") == bool(order.isbuy()))
            and math.isclose(created_size, expected_size, rel_tol=0.0, abs_tol=1e-12)
        )

    def _halt_for_order(self, order, reason: str) -> None:
        symbol = getattr(getattr(order, "data", None), "_name", "")
        self._state = "HALTED"
        self._rejections.append(reason)
        self._record("halted", reason=reason, order_ref=order.ref, symbol=symbol)

    def notify_order(self, order) -> None:
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.ref in self._terminal_order_refs:
            return
        matches_current_leg = self._order_matches_current_leg(order)
        if matches_current_leg and self._submission_in_flight and self._pending_order_ref is None:
            # Bind a synchronous callback before its broker call returns so a
            # fact consumed by a callback wrapper after ``super()`` can still
            # be checked against this exact submitted order.
            current_leg = self._planned_legs[self._leg_index]
            self._submitted_order_ids_by_leg.setdefault(str(current_leg["symbol"]), set()).add(
                str(order.ref)
            )
        if not matches_current_leg:
            if order.status != order.Partial:
                self._terminal_order_refs.add(order.ref)
            self._halt_for_order(order, "UNEXPECTED_ORDER_CALLBACK")
            return
        symbol = getattr(order.data, "_name", "")
        if order.status == order.Partial:
            # A synchronous broker callback may arrive before ``buy``/``sell``
            # returns.  Bind the ref here while the in-flight leg is still the
            # current leg so later Completed/Canceled callbacks retain the
            # accumulated fact even though HALTED forbids new submissions.
            self._pending_order = order
            self._pending_order_ref = order.ref
            self._order_projection.append(
                {
                    "symbol": symbol,
                    "side": "buy" if order.isbuy() else "sell",
                    "status": "partial",
                    "size": abs(float(order.executed.size)),
                    "price": float(order.executed.price or 0.0),
                    "source": "backbroker_replay_hypothetical",
                    "fill_timing": "FILL_TIMING_UNKNOWN",
                }
            )
            # Partial is an observation, not a terminal state.  Keep the
            # reference so a later Completed/Canceled callback is correlated;
            # HALTED blocks new legs while still ingesting those facts.
            self._halt_for_order(order, "PARTIAL_FILL_RECOVERY_REQUIRED")
            return
        self._terminal_order_refs.add(order.ref)
        self._pending_order = None
        self._pending_order_ref = None
        if order.status == order.Completed:
            expected_size = abs(float(self._planned_legs[self._leg_index]["size"]))
            actual_size = abs(float(order.executed.size))
            if not math.isclose(actual_size, expected_size, rel_tol=0.0, abs_tol=1e-12):
                self._order_projection.append(
                    {
                        "symbol": symbol,
                        "side": "buy" if order.isbuy() else "sell",
                        "status": "completed_size_mismatch",
                        "size": actual_size,
                        "price": float(order.executed.price),
                        "source": "backbroker_replay_hypothetical",
                        "fill_timing": "FILL_TIMING_UNKNOWN",
                    }
                )
                self._halt_for_order(order, "ORDER_COMPLETED_SIZE_MISMATCH")
                return
            self._order_projection.append(
                {
                    "symbol": symbol,
                    "side": "buy" if order.isbuy() else "sell",
                    "status": "completed",
                    "size": abs(float(order.executed.size)),
                    "price": float(order.executed.price),
                    "source": "backbroker_replay_hypothetical",
                    "fill_timing": "FILL_TIMING_UNKNOWN",
                }
            )
            if (
                getattr(self.p, "clock_provider", None) is not None
                and self._state == "ENTERING"
                and self._confirmed_leg_quantity(symbol) < expected_size
            ):
                self._state = "HALTED"
                self._basket_status = "RECOVERY_REQUIRED"
                self._rejections.append("PROTECTION_FILL_CONFIRMATION_REQUIRED")
                self._record(
                    "halted",
                    reason="PROTECTION_FILL_CONFIRMATION_REQUIRED",
                    symbol=symbol,
                )
                return
            self._leg_index += 1
            self._submit_next_leg()
            return
        self._order_projection.append(
            {
                "symbol": symbol,
                "side": "buy" if order.isbuy() else "sell",
                "status": order.getstatusname().lower(),
                "size": abs(float(order.executed.size)),
                "price": float(order.executed.price or 0.0),
                "source": "backbroker_replay_hypothetical",
                "fill_timing": "FILL_TIMING_UNKNOWN",
            }
        )
        self._halt_for_order(order, "ORDER_TERMINAL_WITHOUT_FULL_FILL")

    def notify_idle(self, now: Any = None) -> None:
        """Advance local timing projections without inventing an execution action.

        Cerebro invokes this callback without arguments.  That path is
        deliberately rejected unless the caller supplied a trusted scoped
        clock provider.  A last bar or last callback timestamp is never used as
        the current time.
        """

        try:
            observation = self._observe_clock(now)
        except ClockSafetyError:
            self._last_idle_projection = {
                "status": "OFFLINE_SIGNAL_ONLY",
                "risk_projection_available": False,
                "risk_actions": [],
                "reason": self._clock_rejection_reason,
            }
            return
        self._last_idle_projection = self._risk_idle_projection(observation)
        if self._execution_window is not None:
            first_leg = self._leg_index == 0
            self._execution_gate(first_leg=first_leg)
        if self._state == "OPEN" and self._hold_projection.risk_exit_allowed(
            observation.monotonic_ns
        ):
            # No SDK read-only risk projection is available to this example;
            # expose the deadline and keep the action list empty.
            self._basket_status = "RECOVERY_REQUIRED"
            self._record(
                "risk_deadline_reached",
                status="RISK_PROJECTION_ONLY",
                risk_actions=[],
                monotonic_ns=observation.monotonic_ns,
            )

    def notify_bar(self, _bar: Any) -> None:
        """Compatibility callback; closed bars remain the sole decision input."""

    def next(self) -> None:
        try:
            timestamp, snapshot = self._snapshot()
        except (IndexError, KeyError, ValueError) as exc:
            self._reset_entry_confirmation(str(exc))
            self._history.clear()
            self._rejections.append(str(exc))
            self._record("rejected", reason=str(exc))
            return

        decision_input = self._consume_barrier(timestamp, snapshot)
        if decision_input is None:
            self._reset_entry_confirmation("BARARRIER_NOT_READY")
            self._rejections.append("BARARRIER_NOT_READY")
            self._record("rejected", reason="BARARRIER_NOT_READY")
            return
        if self._clock_rejection_latched:
            self._reset_entry_confirmation(self._clock_rejection_reason or "CLOCK_UNSAFE")
            return
        timestamp = decision_input.bucket_end.replace(tzinfo=None)
        # All prices below come from the immutable public BarEvidence map.
        snapshot = {
            symbol: {
                field: getattr(bar, field) for field in ("open", "high", "low", "close", "volume")
            }
            for symbol, bar in decision_input.bars.items()
        }
        self._last_closed_timestamp = timestamp
        residual = self._residual(snapshot)
        if not math.isfinite(residual):
            self._reset_entry_confirmation("NONFINITE_RESIDUAL")
            self._rejections.append("NONFINITE_RESIDUAL")
            return
        try:
            if self._state in {"ENTERING", "EXITING", "HALTED"}:
                self._reset_entry_confirmation("STATE_NOT_FLAT")
                return
            zscore = self._zscore(residual)
            try:
                limits = self._limits(snapshot)
            except (TimingContractError, ValueError) as exc:
                self._reset_entry_confirmation("INVALID_PRICE_ENVELOPE")
                self._rejections.append("INVALID_PRICE_ENVELOPE")
                self._record("rejected", reason="INVALID_PRICE_ENVELOPE", detail=str(exc))
                return
            if self._state == "OPEN":
                self._reset_entry_confirmation("STATE_OPEN")
                use_hold_projection = (
                    self._hold_projection.minimum_deadline_ns is not None
                    or self._hold_projection.maximum_deadline_ns is not None
                )
                if use_hold_projection:
                    now_ns = self._current_clock_now_ns
                    if now_ns is None:
                        self._rejections.append("TRUSTED_CLOCK_REQUIRED")
                        return
                    min_hold_met = self._hold_projection.normal_exit_allowed(now_ns)
                    max_hold_met = self._hold_projection.risk_exit_allowed(now_ns)
                    if not min_hold_met and not max_hold_met:
                        return
                    hold_anchor = (
                        max(self._hold_projection._fill_upper_by_leg.values())
                        if self._hold_projection.minimum_deadline_ns is not None
                        else self._hold_projection.first_possible_exposure_mono_ns
                    )
                    held_minutes = (
                        max(0.0, (now_ns - hold_anchor) / 1_000_000_000.0 / 60.0)
                        if hold_anchor is not None
                        else 0.0
                    )
                else:
                    if self._entry_completed_at is None:
                        self._state = "HALTED"
                        self._rejections.append("MISSING_FULL_BASKET_COMPLETION_TIME")
                        self._record("halted", reason="MISSING_FULL_BASKET_COMPLETION_TIME")
                        return
                    held_minutes = (timestamp - self._entry_completed_at).total_seconds() / 60.0
                    min_hold_met = held_minutes >= float(self.p.minimum_holding_minutes)
                    max_hold_minutes = int(self.p.max_holding_bars) * int(self.p.bar_minutes)
                    max_hold_met = held_minutes >= max_hold_minutes
                if (
                    (min_hold_met or max_hold_met)
                    and (max_hold_met or (zscore is not None and abs(zscore) <= self.p.exit_z))
                    and self._ordinary_action_allowed(timestamp)
                ):
                    self._start_exit(
                        limits,
                        "residual_reverted" if min_hold_met and not max_hold_met else "max_holding",
                        timestamp,
                        held_minutes,
                    )
                return
            if zscore is None or abs(zscore) < self.p.entry_z:
                self._reset_entry_confirmation("ENTRY_SIGNAL_NOT_QUALIFIED")
                return
            direction = "conversion" if zscore > 0 else "reversal"
            try:
                score = self._score(direction, limits)
            except (TimingContractError, ValueError) as exc:
                self._reset_entry_confirmation("INCOMPLETE_COST_EVIDENCE")
                self._rejections.append("INCOMPLETE_COST_EVIDENCE")
                self._record("rejected", reason="INCOMPLETE_COST_EVIDENCE", detail=str(exc))
                return
            self._indicative_score_evidence.append(
                {
                    "candidate_id": self.p.candidate_id,
                    "bar_index": len(self),
                    "bar_timestamp": timestamp.isoformat(),
                    "direction": direction,
                    "residual": round(residual, 12),
                    "zscore": round(zscore, 12),
                    "indicative_score_cny": round(score, 12),
                    "minimum_score_cny": float(self.p.minimum_score),
                    "eligible": bool(score > self.p.minimum_score),
                    "source": "closed_bar_envelope_only",
                }
            )
            if score <= self.p.minimum_score:
                self._reset_entry_confirmation("INDICATIVE_SCORE_TOO_SMALL")
                self._rejections.append("INDICATIVE_SCORE_TOO_SMALL")
                self._record("rejected", reason="INDICATIVE_SCORE_TOO_SMALL", score=round(score, 6))
                return
            # Every confirmation round must pass the budget gate itself.  A
            # later round cannot repair a budget failure from the first one.
            if not self._entry_budget_allows():
                self._reset_entry_confirmation("BUDGET_REJECTED")
                if "BUDGET_REJECTED" not in self._rejections:
                    self._rejections.append("BUDGET_REJECTED")
                self._record("rejected", reason="BUDGET_REJECTED")
                return
            if not self._confirmed_entry(direction, score, timestamp):
                return
            if self._ordinary_action_allowed(timestamp):
                self._start_entry(direction, limits, score, timestamp)
        finally:
            # The current synchronized closed bar is appended only after its decision.
            self._history.append(residual)
            self._history = self._history[-(int(self.p.window) * 2) :]

    def report(self) -> dict[str, object]:
        positions = {
            symbol: float(self.getposition(data).size)
            for symbol, data in sorted(self._data_by_symbol.items())
        }
        evidence = {
            "bar_cohorts.jsonl": list(self._bar_cohort_evidence),
            "indicative_scores.jsonl": list(self._indicative_score_evidence),
            "bar_only_access_audit.json": {
                "mode": "replay",
                "input_boundary": "closed_15m_ohlcv_and_quality_metadata",
                "allowed_market_fields": ["open", "high", "low", "close", "volume"],
                "forbidden_market_inputs": ["tick", "bid", "ask", "order_book", "last_trade"],
                "execution_fill_status": "FILL_TIMING_UNKNOWN",
                "network_requests": 0,
                "order_writes": 0,
                "external_write_status": "ZERO_EXTERNAL_WRITE",
            },
            "capital_path_states.jsonl": [
                {
                    "event_index": index,
                    "event_kind": event.get("kind"),
                    "strategy_state": self._state,
                    "capital_limit_cny": float(self.p.capital_limit),
                    "ordinary_limit_cny": float(self.p.ordinary_limit),
                    "recovery_reserve_cny": float(self.p.recovery_reserve),
                    "projected_entry_capital_cny": float(self.p.projected_entry_capital),
                    "account_snapshot": "UNKNOWN_OFFLINE_NO_SDK_SNAPSHOT",
                }
                for index, event in enumerate(self._cycle_events)
            ],
        }
        return {
            "candidate_id": self.p.candidate_id,
            "state": self._state,
            "basket_status": self._basket_status,
            "flat_status": (
                "LOCAL_BASKET_FLAT_UNVERIFIED" if self._state == "FLAT" else self._basket_status
            ),
            "authoritative_flat_status": "NOT_RUN_SDK_TWO_ROUND_RECONCILIATION",
            "account_risk_status": "UNKNOWN_OFFLINE_NO_SDK_SNAPSHOT",
            "budget_evidence": "OFFLINE_PROJECTED_CAPITAL_FIXTURE_NOT_O2_PROOF",
            "ordinary_decisions": self._ordinary_decisions,
            "orders": self._order_projection,
            "events": self._cycle_events,
            "rejections": self._rejections,
            "positions": positions,
            "entry_confirmation_bars": int(self.p.confirmation_bars),
            "minimum_holding_minutes": int(self.p.minimum_hold_seconds) // 60,
            "barrier": {
                "policy_timeout_seconds": self._barrier.policy.timeout_seconds,
                "timeframe_seconds": self._barrier.policy.timeframe_seconds,
                "last_input": (
                    self._last_decision_input.to_dict()
                    if self._last_decision_input is not None
                    else None
                ),
                "clock_mode": "replay",
                "clock_domain": "iter23-replay-clock",
                "late_bar_policy": "retired_bucket_no_backfill",
                "results": list(self._barrier_results),
            },
            "timing_projection": {
                "execution_window": (
                    self._execution_window.projection()
                    if self._execution_window is not None
                    else None
                ),
                "exit_execution_window": (
                    self._exit_execution_window.projection()
                    if self._exit_execution_window is not None
                    else None
                ),
                "execution_gate_mode": (
                    "OFFLINE_HYPOTHETICAL_CALLBACKS"
                    if self.p.clock_provider is None
                    else "SCOPED_MONOTONIC_CLOCK"
                ),
                "hold": self._hold_projection.projection(),
                "fill_timing": dict(self._fill_timing),
                "fill_timing_status": self._fill_timing["status"],
                "confirmed_fill_quantity": self._confirmed_fill_quantity,
                "confirmed_fills": self._confirmed_fill_quantity,
                "confirmed_fill_by_leg": dict(self._confirmed_fill_by_leg),
                "possible_exposure": self._possible_exposure,
                "execution_fact_count": len(self._execution_fact_history),
                "quarantined_execution_facts": list(self._quarantined_execution_facts),
                "price_envelopes": {
                    symbol: {
                        "tick": envelope.tick,
                        "half_envelope": envelope.half_envelope,
                        "lower": envelope.lower,
                        "upper": envelope.upper,
                        "exchange_limits_known": envelope.exchange_limits_known,
                        "limit_source": envelope.limit_source,
                        "reference_identity": envelope.reference_identity,
                        "execution_eligible": envelope.execution_eligible,
                    }
                    for symbol, envelope in sorted(self._last_price_envelopes.items())
                },
                "cost_evidence": (
                    "synthetic_six_side_aggregate"
                    if self.p.fee_schedule is None
                    else "explicit_six_side_offset_schedule"
                ),
                "risk_projection_available": False,
                "risk_actions": [],
                "execution_eligible": False,
                "idle": dict(self._last_idle_projection),
                "clock_rejection_latched": self._clock_rejection_latched,
                "clock_rejection_reason": self._clock_rejection_reason,
                "token_digest": self._consumed_token_digest,
                "token_durability": self._token_projection.durability_status,
                "session_policy": {
                    "stop_entry_seconds": self._session_policy.stop_entry_seconds,
                    "exit_seconds": self._session_policy.exit_seconds,
                    "handover_seconds": self._session_policy.handover_seconds,
                    "basket_loss_limit": self._session_policy.basket_loss_limit,
                    "daily_loss_limit": self._session_policy.daily_loss_limit,
                    "account_risk_status": "UNKNOWN",
                    "status": "NOT_RUN_REAL_ACCOUNT_OR_FEE_EVIDENCE",
                },
                "authoritative_flat_status": "NOT_RUN_SDK_TWO_ROUND_RECONCILIATION",
            },
            "external_request_counts": {"network": 0, "order_write": 0},
            "evidence_package": evidence,
            "evidence_boundary": (
                "offline local-bar replay only; no CTP request, actual fill, authoritative "
                "flat or PnL claim; OHLC fill timing is unknown"
            ),
        }
