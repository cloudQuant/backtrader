#!/usr/bin/env python
"""Self-similarity (intraday time-of-day pattern matching) strategy.

Implements iteration 35: match the current intraday return window against
the same time-of-day windows of the most recent historical trading days,
trade the directional bias when the probability gate and the positive
expectation gate both pass, hold for a fixed bar horizon, and protect the
position with an OCO stop/take bracket priced at ``exit_multiple`` times
the expected log return.

Design reference:
docs/_internal/opts/requirements/迭代35-自相似性策略实现/设计文档.md (D35-01 ~ D35-15)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
import json
import math
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

import backtrader as bt

DECISION_LONG = "LONG"
DECISION_SHORT = "SHORT"
DECISION_SKIP = "SKIP"

REASON_NO_WINDOW = "NO_WINDOW"
REASON_NO_CANDIDATES = "NO_CANDIDATES"
REASON_INSUFFICIENT_MATCHES = "INSUFFICIENT_MATCHES"
REASON_NEGATIVE_EXPECTATION = "NEGATIVE_EXPECTATION"
REASON_PROB_BELOW = "PROB_BELOW"
REASON_POSITION_OPEN = "POSITION_OPEN"

MIN_PRICE_TICK = 0.01


class DataValidationError(ValueError):
    """Raised before any backtest starts when the OHLCV frame is unusable."""


# ---------------------------------------------------------------------------
# Pure functions (unit-testable without a running Cerebro)
# ---------------------------------------------------------------------------


def validate_ohlcv(frame: pd.DataFrame) -> None:
    """Validate monotonic index and OHLC sanity (D35-02, reason DATA_INVALID)."""
    if frame is None or len(frame) == 0:
        raise DataValidationError("DATA_INVALID: empty frame")
    required = {"open", "high", "low", "close"}
    missing = required.difference(frame.columns)
    if missing:
        raise DataValidationError("DATA_INVALID: missing columns %s" % sorted(missing))
    if not frame.index.is_monotonic_increasing:
        raise DataValidationError("DATA_INVALID: index not sorted ascending")
    low_above = frame["low"] > frame["high"]
    if low_above.any():
        first = frame.index[low_above][0]
        raise DataValidationError("DATA_INVALID: low > high at %s" % first)
    bad = (frame["open"] > frame["high"]) | (frame["open"] < frame["low"])
    bad = bad | (frame["close"] > frame["high"]) | (frame["close"] < frame["low"])
    if bad.any():
        first = frame.index[bad][0]
        raise DataValidationError("DATA_INVALID: open/close outside range at %s" % first)
    if not np.isfinite(frame[list(required)].to_numpy(dtype=float)).all():
        raise DataValidationError("DATA_INVALID: non-finite prices")


def pearson_corr(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Vectorised Pearson correlation of each matrix row against ``vector``.

    Rows with (near) zero variance yield NaN and are excluded upstream.
    """
    mat = np.asarray(matrix, dtype=float)
    vec = np.asarray(vector, dtype=float)
    mat_centered = mat - mat.mean(axis=1, keepdims=True)
    vec_centered = vec - vec.mean()
    numerator = mat_centered @ vec_centered
    denominator = np.linalg.norm(mat_centered, axis=1) * np.linalg.norm(vec_centered)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.where(denominator > 1e-12, numerator / denominator, np.nan)
    return corr


def directional_stats(
    corr: np.ndarray,
    forward_returns: np.ndarray,
    corr_threshold: float,
) -> Tuple[int, float, float]:
    """Selection plus sign-adjusted statistics (D35-05).

    ``adjusted = sign(corr) * forward_return`` merges positive- and
    negative-correlation candidates into one statistical pool. Returns
    ``(n_selected, up_prob, expected_return)``; NaN probabilities when
    nothing is selected.
    """
    corr = np.asarray(corr, dtype=float)
    forward_returns = np.asarray(forward_returns, dtype=float)
    selected = np.isfinite(corr) & (np.abs(corr) >= corr_threshold)
    n_selected = int(selected.sum())
    if n_selected == 0:
        return 0, float("nan"), float("nan")
    adjusted = np.sign(corr[selected]) * forward_returns[selected]
    up_prob = float((adjusted > 0).mean())
    expected_return = float(adjusted.mean())
    return n_selected, up_prob, expected_return


def build_decision(
    n_selected: int,
    up_prob: float,
    expected_return: float,
    prob_threshold: float,
    min_matches: int,
) -> Tuple[str, str]:
    """Decision chain per D35-06 (order: matches -> expectation -> probability)."""
    if n_selected < min_matches:
        return DECISION_SKIP, REASON_INSUFFICIENT_MATCHES
    if not (expected_return > 0.0):
        return DECISION_SKIP, REASON_NEGATIVE_EXPECTATION
    if up_prob >= prob_threshold:
        return DECISION_LONG, ""
    if up_prob <= 1.0 - prob_threshold:
        return DECISION_SHORT, ""
    return DECISION_SKIP, REASON_PROB_BELOW


def stop_take_prices(
    entry: float,
    m_log: float,
    is_long: bool,
    tick: float = MIN_PRICE_TICK,
) -> Tuple[float, float]:
    """OCO bracket prices from log-distance ``m_log`` (D35-07 oracle).

    Long: take above entry, stop below; short mirrored. Each leg distance is
    expanded to at least one ``tick``.
    """
    take_dist = max(math.expm1(abs(m_log)) * entry, tick)
    stop_dist = max(-math.expm1(-abs(m_log)) * entry, tick)
    if is_long:
        return entry + take_dist, entry - stop_dist
    return entry - stop_dist, entry + take_dist


@dataclass
class SignalResult:
    """Outcome of one signal evaluation (auditable projection)."""

    decision: str = DECISION_SKIP
    reason: str = REASON_NO_WINDOW
    n_candidates: int = 0
    n_selected: int = 0
    avg_abs_corr: float = 0.0
    up_prob: float = 0.0
    expected_return: float = 0.0


# ---------------------------------------------------------------------------
# Feature engine: intraday time-of-day alignment (D35-02 ~ D35-06)
# ---------------------------------------------------------------------------


class SimilarityEngine:
    """Index an M1 frame and evaluate the self-similarity signal chain."""

    def __init__(
        self,
        frame: pd.DataFrame,
        window_bars: int,
        horizon_bars: int,
        lookback_days: int,
        corr_threshold: float = 0.6,
        prob_threshold: float = 0.75,
        min_matches: int = 5,
    ) -> None:
        validate_ohlcv(frame)
        if window_bars < 2:
            raise ValueError("window_bars must be >= 2")
        if horizon_bars < 1:
            raise ValueError("horizon_bars must be >= 1")
        if lookback_days < 1:
            raise ValueError("lookback_days must be >= 1")
        self.window_bars = int(window_bars)
        self.horizon_bars = int(horizon_bars)
        self.lookback_days = int(lookback_days)
        self.corr_threshold = float(corr_threshold)
        self.prob_threshold = float(prob_threshold)
        self.min_matches = int(min_matches)

        close = frame["close"].to_numpy(dtype=float)
        log_returns = np.full(len(frame), np.nan)
        log_returns[1:] = np.log(close[1:] / close[:-1])
        self._log_returns = log_returns
        self._opens = frame["open"].to_numpy(dtype=float)

        minutes = frame.index.hour * 60 + frame.index.minute
        self._days = sorted({ts.date() for ts in frame.index})
        self._day_ids = {day: idx for idx, day in enumerate(self._days)}
        self._tod_rows = [np.full(1440, -1, dtype=np.int64) for _ in self._days]
        day_of_row = np.fromiter(
            (self._day_ids[ts.date()] for ts in frame.index),
            dtype=np.int64,
            count=len(frame),
        )
        for day_id, tod, row in zip(day_of_row, minutes, np.arange(len(frame))):
            self._tod_rows[day_id][tod] = row

        # Per-day validity of a window anchored at time-of-day ``a``:
        # bars [a, a + window_bars - 1] (window) plus [a + window_bars,
        # a + window_bars + horizon_bars] (entry..exit opens) all present.
        need = self.window_bars + self.horizon_bars + 1
        self._valid_anchor: list[np.ndarray] = []
        for tod_rows in self._tod_rows:
            present = (tod_rows >= 0).astype(np.int64)
            cumsum = np.concatenate(([0], np.cumsum(present)))
            counts = cumsum[need:] - cumsum[: 1440 - need + 1]
            valid = np.zeros(1440, dtype=bool)
            if len(counts):
                valid[: len(counts)] = counts == need
            self._valid_anchor.append(valid)

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _tod(dt: pd.Timestamp) -> int:
        return dt.hour * 60 + dt.minute

    def _current_window(self, day: date_type, tod: int) -> Optional[np.ndarray]:
        start = tod - (self.window_bars - 1)
        if start < 0:
            return None
        tod_rows = self._tod_rows[self._day_ids[day]]
        rows = tod_rows[start : tod + 1]
        if len(rows) != self.window_bars or (rows < 0).any():
            return None
        return rows

    def candidates_for(self, dt: pd.Timestamp) -> list:
        """Most recent ``lookback_days`` valid candidate days before dt's day.

        Validity: same-anchor window and forward span fully present on that
        day (D35-04). The current trading day is never a candidate.
        """
        day_id = self._day_ids.get(dt.date())
        if day_id is None:
            return []
        anchor = self._tod(dt) - (self.window_bars - 1)
        if anchor < 0 or anchor + self.window_bars + self.horizon_bars + 1 > 1440:
            return []
        selected: list = []
        for candidate_id in range(day_id - 1, -1, -1):
            if self._valid_anchor[candidate_id][anchor]:
                selected.append(self._days[candidate_id])
                if len(selected) >= self.lookback_days:
                    break
        return selected

    def evaluate(self, dt: pd.Timestamp) -> SignalResult:
        """Run the full signal chain for the bar ending at ``dt`` (D35-06)."""
        day = dt.date()
        if day not in self._day_ids:
            return SignalResult(reason=REASON_NO_WINDOW)
        tod = self._tod(dt)
        rows = self._current_window(day, tod)
        if rows is None:
            return SignalResult(reason=REASON_NO_WINDOW)
        current = self._log_returns[rows[1:]]

        candidate_days = self.candidates_for(dt)
        if not candidate_days:
            return SignalResult(reason=REASON_NO_CANDIDATES)

        anchor = tod - (self.window_bars - 1)
        matrix = np.empty((len(candidate_days), self.window_bars - 1))
        forward = np.empty(len(candidate_days))
        day_ids = self._day_ids
        tod_rows_all = self._tod_rows
        log_returns = self._log_returns
        opens = self._opens
        for i, candidate_day in enumerate(candidate_days):
            cand_rows = tod_rows_all[day_ids[candidate_day]]
            win_rows = cand_rows[anchor : anchor + self.window_bars]
            matrix[i] = log_returns[win_rows[1:]]
            entry_row = cand_rows[tod + 1]
            exit_row = cand_rows[tod + 1 + self.horizon_bars]
            forward[i] = math.log(opens[exit_row] / opens[entry_row])

        corr = pearson_corr(matrix, current)
        n_selected, up_prob, expected_return = directional_stats(corr, forward, self.corr_threshold)
        decision, reason = build_decision(
            n_selected, up_prob, expected_return, self.prob_threshold, self.min_matches
        )
        selected_mask = np.isfinite(corr) & (np.abs(corr) >= self.corr_threshold)
        avg_abs_corr = float(np.abs(corr[selected_mask]).mean()) if n_selected else 0.0
        return SignalResult(
            decision=decision,
            reason=reason,
            n_candidates=len(candidate_days),
            n_selected=n_selected,
            avg_abs_corr=avg_abs_corr,
            up_prob=up_prob if n_selected else 0.0,
            expected_return=expected_return if n_selected else 0.0,
        )


# ---------------------------------------------------------------------------
# Backtrader strategy (thin integration layer, D35-07 / D35-08)
# ---------------------------------------------------------------------------


class SelfSimilarityStrategy(bt.Strategy):
    """Thin strategy wrapper around :class:`SimilarityEngine`."""

    params = (
        ("window_bars", 75),
        ("horizon_bars", 15),
        ("lookback_days", 60),
        ("corr_threshold", 0.6),
        ("prob_threshold", 0.75),
        ("exit_multiple", 3.0),
        ("min_matches", 5),
        ("size", 1.0),
        ("use_bracket", True),  # OCO stop/take bracket; False = horizon exit only
        ("print_log", True),
        ("signals_path", None),
        ("engine", None),
    )

    def __init__(self) -> None:
        if self.p.engine is None:
            raise ValueError("SelfSimilarityStrategy requires a SimilarityEngine")
        self.engine = self.p.engine
        self.signal_log: list = []
        self.closed_trades: list = []
        self.equity_curve: list = []
        self.total_entries = 0
        self.stop_or_take_count = 0
        self._bars_held = 0
        self._exit_submitted = False
        self._pending_er = 0.0
        self._entry_ref = None
        self._take_order = None
        self._stop_order = None
        self._entry_exec_dt = None
        self._entry_exec_price = None
        self._entry_direction = ""
        self._exit_exec = None
        self._exit_kind = ""
        self._signals_fh = None
        if self.p.signals_path:
            path = Path(self.p.signals_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._signals_fh = path.open("a", encoding="utf-8")

    # -- lifecycle -------------------------------------------------------

    def stop(self) -> None:
        if self._signals_fh:
            self._signals_fh.close()

    def log(self, text: str) -> None:
        if self.p.print_log:
            print(text)

    # -- signal bookkeeping ----------------------------------------------

    def _record_signal(self, dt, decision: str, reason: str, result: SignalResult) -> None:
        row = {
            "dt": dt.isoformat(),
            "decision": decision,
            "reason": reason,
            "n_candidates": result.n_candidates if result else 0,
            "n_selected": result.n_selected if result else 0,
            "avg_abs_corr": result.avg_abs_corr if result else 0.0,
            "up_prob": result.up_prob if result else 0.0,
            "expected_return": result.expected_return if result else 0.0,
        }
        self.signal_log.append(row)
        if self._signals_fh:
            self._signals_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if self.p.print_log and decision != DECISION_SKIP:
            self.log(
                "%s %s selected=%d up_prob=%.3f er=%.2e"
                % (dt, decision, row["n_selected"], row["up_prob"], row["expected_return"])
            )

    # -- core loop --------------------------------------------------------

    def next(self) -> None:
        dt = self.data.datetime.datetime(0)
        self.equity_curve.append(float(self.broker.getvalue()))
        if self.position:
            self._record_signal(dt, DECISION_SKIP, REASON_POSITION_OPEN, None)
            self._bars_held += 1
            if self._bars_held >= self.p.horizon_bars and not self._exit_submitted:
                self._cancel_bracket()
                self.close()
                self._exit_submitted = True
                self._exit_kind = "HORIZON"
            return
        result = self.engine.evaluate(dt)
        self._record_signal(dt, result.decision, result.reason, result)
        if result.decision == DECISION_LONG:
            self._pending_er = result.expected_return
            entry = self.buy(size=self.p.size)
            self._entry_ref = entry.ref
        elif result.decision == DECISION_SHORT:
            self._pending_er = result.expected_return
            entry = self.sell(size=self.p.size)
            self._entry_ref = entry.ref

    # -- order / trade notifications --------------------------------------

    def _cancel_bracket(self) -> None:
        for order in (self._take_order, self._stop_order):
            if order is not None and order.alive():
                self.cancel(order)

    def notify_order(self, order) -> None:
        if order.status == order.Completed:
            dt = self.data.datetime.datetime(0)
            if self._entry_ref is not None and order.ref == self._entry_ref:
                self._on_entry_filled(order, dt)
            elif any(
                o is not None and order.ref == o.ref for o in (self._take_order, self._stop_order)
            ):
                self.stop_or_take_count += 1
                self._exit_kind = "TAKE" if order.ref == self._take_order.ref else "STOP"
                self._exit_exec = (dt, order.executed.price)
            else:
                # horizon exit market order
                self._exit_exec = (dt, order.executed.price)
                if not self._exit_kind:
                    self._exit_kind = "HORIZON"
            return
        if order.status in (order.Canceled, order.Rejected, order.Margin, order.Expired):
            if self._entry_ref is not None and order.ref == self._entry_ref:
                self.log(
                    "%s entry order failed (%s), resetting" % (order.ref, order.getstatusname())
                )
                self._reset_position_state()

    def _on_entry_filled(self, order, dt) -> None:
        entry_price = order.executed.price
        is_long = order.isbuy()
        self._entry_direction = "LONG" if is_long else "SHORT"
        if not self.p.use_bracket:
            # Experiment mode: no OCO bracket; the horizon exit in next()
            # (bars_held >= horizon_bars -> close()) is the only exit.
            self.log(
                "%s ENTRY %s @%.2f (no bracket, horizon exit only)"
                % (dt, "long" if is_long else "short", entry_price)
            )
            self.total_entries += 1
            self._entry_exec_dt = dt
            self._entry_exec_price = entry_price
            return
        m_log = self.p.exit_multiple * self._pending_er
        take_price, stop_price = stop_take_prices(entry_price, m_log, is_long)
        side = "long" if is_long else "short"
        self.log(
            "%s ENTRY %s @%.2f take=%.2f stop=%.2f m_log=%.2e"
            % (dt, side, entry_price, take_price, stop_price, m_log)
        )
        if is_long:
            self._take_order = self.sell(
                exectype=bt.Order.Limit, price=take_price, size=self.p.size
            )
            self._stop_order = self.sell(
                exectype=bt.Order.Stop,
                price=stop_price,
                size=self.p.size,
                oco=self._take_order,
            )
        else:
            self._take_order = self.buy(exectype=bt.Order.Limit, price=take_price, size=self.p.size)
            self._stop_order = self.buy(
                exectype=bt.Order.Stop,
                price=stop_price,
                size=self.p.size,
                oco=self._take_order,
            )
        self.total_entries += 1
        self._entry_exec_dt = dt
        self._entry_exec_price = entry_price

    def notify_trade(self, trade) -> None:
        if not trade.isclosed:
            return
        exit_dt, exit_price = self._exit_exec if self._exit_exec else (None, None)
        self.closed_trades.append(
            {
                "entry_dt": self._entry_exec_dt,
                "exit_dt": exit_dt,
                "entry_price": self._entry_exec_price,
                "exit_price": exit_price,
                "pnl": trade.pnlcomm,
                "exit_kind": self._exit_kind,
                "direction": self._entry_direction,
            }
        )
        self.log(
            "%s TRADE CLOSED %s -> %s pnl=%.2f (%s)"
            % (exit_dt, self._entry_exec_dt, exit_price, trade.pnlcomm, self._exit_kind)
        )
        self._reset_position_state()

    def _reset_position_state(self) -> None:
        self._bars_held = 0
        self._exit_submitted = False
        self._pending_er = 0.0
        self._entry_ref = None
        self._take_order = None
        self._stop_order = None
        self._entry_exec_dt = None
        self._entry_exec_price = None
        self._entry_direction = ""
        self._exit_exec = None
        self._exit_kind = ""
