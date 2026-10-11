#!/usr/bin/env python
"""FNN-embedding retrieval strategy (iteration 35-1).

Implements scheme A of the initial requirement: a feed-forward autoencoder
compresses 12-dim feature windows of XAUUSD M1 bars into a low-dimensional
embedding; cosine similarity retrieves the Top-N most similar historical
windows from a full-history sliding library; the sign-adjusted forward
returns of the neighbours drive a Wilson-lower-bound / cost-adjusted
expectation gated position, held for a fixed bar horizon with a floored
OCO stop/take bracket.

Design reference:
docs/_internal/opts/requirements/迭代35-1-自相似性策略改进/设计文档.md (D351-01 ~ D351-15)
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import lfilter

import backtrader as bt

DECISION_LONG = "LONG"
DECISION_SHORT = "SHORT"
DECISION_SKIP = "SKIP"

REASON_NO_WINDOW = "NO_WINDOW"
REASON_NO_NORM = "NO_NORM"
REASON_NO_SAMPLES = "NO_SAMPLES"
REASON_INSUFFICIENT = "INSUFFICIENT_MATCHES"
REASON_COST_BELOW = "COST_BELOW"
REASON_PROB_BELOW = "PROB_BELOW"
REASON_POSITION_OPEN = "POSITION_OPEN"

N_FEATURES = 12
EPS = 1e-12
WILSON_Z = 1.96
RSI_PERIOD = 14
MIN_PRICE_TICK = 0.01


class DataValidationError(ValueError):
    """Raised before any backtest starts when the OHLCV frame is unusable."""


def validate_ohlcv(frame: pd.DataFrame) -> None:
    """Validate monotonic index and OHLC sanity (reason DATA_INVALID)."""
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


# ---------------------------------------------------------------------------
# Feature engine (D351-03, frozen 12-dim list, vectorised)
# ---------------------------------------------------------------------------


def _empty_store():
    return (
        np.zeros((0, N_FEATURES)),
        pd.DatetimeIndex([]),
        np.zeros(0),
        pd.DatetimeIndex([]),
    )


def compute_feature_matrix(
    frame: pd.DataFrame,
    window_bars: int,
    stride: int = 1,
    horizon_bars: int = 15,
) -> Tuple[np.ndarray, pd.DatetimeIndex, np.ndarray, pd.DatetimeIndex]:
    """Compute the 12-dim feature matrix over all valid sliding windows.

    Returns ``(features, end_dts, label_fr, label_ready_dts)`` where row i
    describes the window ending at ``end_dts[i]`` (valid: same trading day,
    contiguous time-of-day, exactly ``window_bars`` bars) whose forward
    label ``label_fr[i] = ln(open[end + 1 + H] / open[end + 1])`` is fully
    realised at ``label_ready_dts[i]`` (row-index convention matches the
    execution path). Windows without a realisable label (data tail) are
    dropped.
    """
    if window_bars < 5:
        raise ValueError("window_bars must be >= 5 (RSI self-containment)")
    W = int(window_bars)
    H = int(horizon_bars)
    stride = max(int(stride), 1)
    n = len(frame)
    if n < W + H + 2:
        return _empty_store()

    close = frame["close"].to_numpy(dtype=float)
    open_ = frame["open"].to_numpy(dtype=float)
    high = frame["high"].to_numpy(dtype=float)
    low = frame["low"].to_numpy(dtype=float)
    tickvol = frame["tickvol"].to_numpy(dtype=float) if "tickvol" in frame.columns else np.ones(n)

    dts = frame.index
    day_codes = np.asarray(pd.factorize(dts.date)[0])
    tod_vals = dts.hour * 60 + dts.minute

    # Candidate window end rows: window fits and label rows end + 1 + H exist.
    ends = np.arange(W - 1, n - (H + 1), stride)
    if len(ends) == 0:
        return _empty_store()
    starts = ends - W + 1

    # Validity: same trading day across the window and contiguous minutes.
    same_day = day_codes[starts] == day_codes[ends]
    same_day &= day_codes[starts] == day_codes[starts + W // 2]
    contiguous = (tod_vals[ends] - tod_vals[starts]) == (W - 1)
    valid = same_day & contiguous
    ends, starts = ends[valid], starts[valid]
    if len(ends) == 0:
        return _empty_store()

    log_close = np.log(np.maximum(close, EPS))
    m1 = starts + W // 2
    m2 = starts + (2 * W) // 3

    feats = np.empty((len(ends), N_FEATURES), dtype=float)
    feats[:, 0] = log_close[m1] - log_close[starts]  # f1 front-segment return
    feats[:, 1] = log_close[m2] - log_close[m1]  # f2 mid-segment return
    feats[:, 2] = log_close[ends] - log_close[m2]  # f3 last-segment return

    # f4: realised vol = std of the window's W-1 log returns * sqrt(W-1)
    lr_full = np.concatenate(([0.0], np.diff(log_close)))
    feats[:, 3] = pd.Series(lr_full).rolling(W - 1, min_periods=W - 1).std().to_numpy(dtype=float)[
        ends
    ] * math.sqrt(W - 1)

    # f5: RSI(14) self-contained per window (Wilder EMA recursion, batched)
    feats[:, 4] = _batch_rsi(log_close, starts, ends)

    feats[:, 5] = close[ends] / close[starts] - 1.0  # f6 momentum

    # f7: close position within the window high-low range
    win_low = pd.Series(low).rolling(W, min_periods=W).min().to_numpy(dtype=float)[ends]
    win_high = pd.Series(high).rolling(W, min_periods=W).max().to_numpy(dtype=float)[ends]
    feats[:, 6] = (close[ends] - win_low) / (win_high - win_low + EPS)

    # f8-f10: candle anatomy (body / upper shadow / lower shadow means)
    rng = np.maximum(high - low, EPS)
    body = np.abs(close - open_) / rng
    upper = (high - np.maximum(open_, close)) / rng
    lower = (np.minimum(open_, close) - low) / rng
    feats[:, 7] = _window_mean(body, starts, ends)
    feats[:, 8] = _window_mean(upper, starts, ends)
    feats[:, 9] = _window_mean(lower, starts, ends)

    # f11-f12: tick-volume level and back/front ratio
    log_vol = np.log(tickvol + 1.0)
    vol_cs = np.concatenate(([0.0], np.cumsum(log_vol)))
    feats[:, 10] = (vol_cs[ends + 1] - vol_cs[starts]) / W
    front = (vol_cs[m1] - vol_cs[starts]) / np.maximum(m1 - starts, 1)
    back = (vol_cs[ends + 1] - vol_cs[m1]) / np.maximum(ends + 1 - m1, 1)
    feats[:, 11] = back / (front + EPS)

    label_fr = np.log(np.maximum(open_[ends + 1 + H], EPS) / np.maximum(open_[ends + 1], EPS))
    return feats, pd.DatetimeIndex(dts[ends]), label_fr, pd.DatetimeIndex(dts[ends + 1 + H])


def _window_mean(arr: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    cs = np.concatenate(([0.0], np.cumsum(arr)))
    width = ends[0] - starts[0] + 1
    return (cs[ends + 1] - cs[starts]) / width


def _batch_rsi(log_close: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Self-contained Wilder RSI(14) at each window end, batched via lfilter.

    Per window the gain/loss series are the W-1 log returns inside the
    window (gains[j] covers bar j+1); the recursion
    ``y_t = (1 - 1/n) y_{t-1} + x_t / n`` is an IIR filter applied along
    axis=1, initialised at each window's own first value (no information
    crosses window boundaries, D351-03 self-containment).
    """
    gains = np.diff(log_close)  # gains[j] = log return of bar j+1
    pos = np.maximum(gains, 0.0)
    neg = np.maximum(-gains, 0.0)
    n_returns = ends[0] - starts[0]  # W - 1 per window
    idx_grid = starts[:, None] + np.arange(n_returns)[None, :]

    out = np.empty(len(starts), dtype=float)
    a = 1.0 - 1.0 / RSI_PERIOD
    chunk = 200_000
    for begin in range(0, len(starts), chunk):
        rows = slice(begin, min(begin + chunk, len(starts)))
        win_pos = pos[idx_grid[rows]]
        win_neg = neg[idx_grid[rows]]
        avg_gain = lfilter([1.0 - a], [1.0, -a], win_pos, axis=1)[:, -1]
        avg_loss = lfilter([1.0 - a], [1.0, -a], win_neg, axis=1)[:, -1]
        rs = avg_gain / (avg_loss + EPS)
        out[rows] = 100.0 - 100.0 / (1.0 + rs)
    return out


# ---------------------------------------------------------------------------
# Rolling normalisation (D351-03, strictly past-only)
# ---------------------------------------------------------------------------


def rolling_normalize(
    features: np.ndarray, norm_window: int, norm_min: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Z-score each row using only the previous ``norm_window`` samples.

    Returns ``(features_norm, valid_mask)``; rows with fewer than
    ``norm_min`` prior samples are marked invalid (NO_NORM). Degenerate
    (near-zero std) features are zeroed.
    """
    df = pd.DataFrame(features)
    shifted = df.rolling(norm_window, min_periods=1).mean().shift(1)
    shifted_var = df.rolling(norm_window, min_periods=1).var().shift(1)
    counts = (
        df.rolling(norm_window, min_periods=1).count().shift(1).iloc[:, 0].to_numpy(dtype=float)
    )

    mu = shifted.to_numpy(dtype=float)
    sigma = np.sqrt(np.maximum(shifted_var.to_numpy(dtype=float), 0.0))
    ok = sigma > 1e-12
    sigma_safe = np.where(ok, sigma, 1.0)
    normalized = np.where(ok, (features - mu) / sigma_safe, 0.0)
    normalized = np.nan_to_num(normalized, nan=0.0, posinf=0.0, neginf=0.0)
    return normalized, counts >= norm_min


# ---------------------------------------------------------------------------
# Decision statistics (D351-07) and bracket prices (D351-08)
# ---------------------------------------------------------------------------


def wilson_lower(p_hat: float, n: int, z: float = WILSON_Z) -> float:
    """Wilson score interval lower bound (oracle table in D351-07)."""
    if n <= 0:
        return float("nan")
    centre = p_hat + z * z / (2.0 * n)
    margin = z * math.sqrt(p_hat * (1.0 - p_hat) / n + z * z / (4.0 * n * n))
    return (centre - margin) / (1.0 + z * z / n)


def build_decision(
    n_selected: int,
    p_low: float,
    expected_return: float,
    cost_gate: float,
    prob_threshold: float,
    min_matches: int,
) -> Tuple[str, str]:
    """Decision chain per D351-07 (matches -> cost -> probability)."""
    if n_selected < min_matches:
        return DECISION_SKIP, REASON_INSUFFICIENT
    if not (expected_return >= cost_gate):
        return DECISION_SKIP, REASON_COST_BELOW
    if p_low >= prob_threshold:
        return DECISION_LONG, ""
    if p_low <= 1.0 - prob_threshold:
        return DECISION_SHORT, ""
    return DECISION_SKIP, REASON_PROB_BELOW


def stop_take_prices_floored(
    entry: float,
    expected_return: float,
    exit_multiple: float,
    atr_fast: float,
    spread_dollar: float,
    atr_floor: float,
    spread_floor: float,
    is_long: bool,
    tick: float = MIN_PRICE_TICK,
) -> Tuple[float, float]:
    """Floored OCO bracket prices (D351-08.2).

    Log distance ``m = max(exit_multiple * er, floor_log)`` where the floor
    derives from ATR and spread dollar distances; each leg is widened to at
    least one tick. Long: (take above, stop below); short mirrored.
    """
    nominal = exit_multiple * max(expected_return, 0.0)
    floor_dollar = max(atr_floor * max(atr_fast, 0.0), spread_floor * max(spread_dollar, 0.0))
    safe_entry = max(entry, EPS)
    floor_log = math.log(1.0 + max(floor_dollar, tick) / safe_entry)
    m = max(nominal, floor_log)
    take_up = max(entry * math.exp(m), entry + tick)
    stop_dn = max(entry * math.exp(-m), tick)
    if is_long:
        return take_up, stop_dn
    return stop_dn, take_up


def round_trip_cost(commission_pct: float, spread_cost_pct: float) -> float:
    """Round-trip cost estimate used by the expectation gate (D351-07)."""
    return 2.0 * commission_pct + spread_cost_pct


# ---------------------------------------------------------------------------
# Retrieval library (D351-06)
# ---------------------------------------------------------------------------


@dataclass
class SignalResult:
    """Outcome of one signal evaluation (auditable projection)."""

    decision: str = DECISION_SKIP
    reason: str = REASON_NO_WINDOW
    n_lib: int = 0
    n_after_excl: int = 0
    n_selected: int = 0
    top_sim_mean: float = 0.0
    top_sim_min: float = 0.0
    v_norm: float = 0.0
    p_hat: float = 0.0
    p_low: float = 0.0
    expected_return: float = 0.0
    cost_gate: float = 0.0
    encoder_version: str = ""


def _ns_int64(dts) -> np.ndarray:
    """DatetimeIndex -> int64 nanoseconds (pandas 3 may store us/ms units)."""
    return np.asarray(pd.DatetimeIndex(dts).to_numpy(dtype="datetime64[ns]")).view("int64")


class EmbeddingLibrary:
    """Feature/label store with lazy label availability (G351-02 defence 2)."""

    def __init__(
        self,
        features_norm: np.ndarray,
        valid_mask: np.ndarray,
        end_dts,
        label_fr,
        label_ready_dts,
    ):
        keep = np.asarray(valid_mask, dtype=bool)
        self.features = np.ascontiguousarray(features_norm[keep], dtype=np.float32)
        self.end_dts = pd.DatetimeIndex(end_dts)[keep]
        self.label_fr = np.asarray(label_fr, dtype=np.float64)[keep]
        self.label_ready_dts = pd.DatetimeIndex(label_ready_dts)[keep]
        # Nanosecond timestamps (unit-safe across pandas versions).
        self._end_ns = _ns_int64(self.end_dts)
        self.label_ready_ns = _ns_int64(self.label_ready_dts)
        # Epoch minutes per row: fast integer distance for exclusion/decorrelation.
        self._end_epoch_min = self._end_ns // 60_000_000_000
        self.n = len(self.label_fr)
        self.embeddings: Optional[np.ndarray] = None
        self.encoder_version: str = ""

    def query(
        self,
        t0_dt: pd.Timestamp,
        v_now: np.ndarray,
        sim_threshold: float,
        top_n: int,
        window_bars: int,
        horizon_bars: int,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Retrieval with exclusion zone + decorrelated Top-N (D351-06.2).

        Returns ``(selected_positions, sims)`` indexing the library arrays;
        empty when nothing clears the gates.
        """
        if self.embeddings is None or self.n == 0 or top_n <= 0:
            return np.zeros(0, dtype=int), np.zeros(0)

        t0 = pd.Timestamp(t0_dt)
        ready = np.searchsorted(self.label_ready_ns, t0.value, side="right")
        if ready <= 0:
            return np.zeros(0, dtype=int), np.zeros(0)

        t0_epoch_min = t0.value // 60_000_000_000
        end_epoch_min = self._end_epoch_min[:ready]
        allowed = (t0_epoch_min - end_epoch_min) >= (window_bars + horizon_bars)
        if not allowed.any():
            return np.zeros(0, dtype=int), np.zeros(0)

        vec = np.asarray(v_now, dtype=np.float32)
        vec = vec / (np.linalg.norm(vec) + 1e-12)
        emb = self.embeddings[:ready]
        sims_all = (emb @ vec) / (np.linalg.norm(emb, axis=1) + 1e-12)

        cand_idx = np.nonzero(allowed & (sims_all >= sim_threshold))[0]
        if len(cand_idx) == 0:
            return np.zeros(0, dtype=int), np.zeros(0)
        order = cand_idx[np.argsort(-sims_all[cand_idx])]
        cand_min = end_epoch_min[order]

        # Vectorised greedy decorrelation: repeatedly take the highest-
        # similarity candidate, then mask everything within dedup_gap
        # minutes of it (covers the whole candidate list, not just a
        # top-slice — the near-self band otherwise starves the Top-N).
        dedup_gap = max(window_bars // 2, 10)  # minutes
        active = np.ones(len(order), dtype=bool)
        chosen: list = []
        for _ in range(int(top_n)):
            nxt = int(np.argmax(active))
            if not active[nxt]:
                break
            chosen.append(int(order[nxt]))
            active &= np.abs(cand_min - cand_min[nxt]) >= dedup_gap
        chosen_arr = np.asarray(chosen, dtype=int)
        return chosen_arr, sims_all[chosen_arr]


# ---------------------------------------------------------------------------
# Strategy-facing engine (coordinates features, encoder bundle, retrieval)
# ---------------------------------------------------------------------------


class FnnRetrievalEngine:
    """Evaluate the retrieval decision chain for a decision bar (D351-07).

    Holds the feature store and the library; the encoder bundle (current
    embeddings) is switched atomically by the rolling trainer at each
    retrain boundary so that library and query vectors always share one
    encoder version.
    """

    def __init__(
        self,
        frame: pd.DataFrame,
        window_bars: int,
        horizon_bars: int,
        stride: int,
        norm_window: int,
        norm_min: int,
        sim_threshold: float,
        prob_threshold: float,
        min_matches: int,
        top_n: int,
        sim_neutral: float,
        cost_gate: float,
    ) -> None:
        validate_ohlcv(frame)
        self.window_bars = int(window_bars)
        self.horizon_bars = int(horizon_bars)
        self.sim_threshold = float(sim_threshold)
        self.prob_threshold = float(prob_threshold)
        self.min_matches = int(min_matches)
        self.top_n = int(top_n)
        self.sim_neutral = float(sim_neutral)
        self.cost_gate = float(cost_gate)

        features, end_dts, label_fr, label_ready = compute_feature_matrix(
            frame, self.window_bars, stride=stride, horizon_bars=self.horizon_bars
        )
        features_norm, valid_mask = rolling_normalize(features, norm_window, norm_min)
        self.library = EmbeddingLibrary(features_norm, valid_mask, end_dts, label_fr, label_ready)
        self._features_full = features_norm
        self._dt_to_row = {ts: i for i, ts in enumerate(pd.DatetimeIndex(end_dts))}

    def evaluate(self, dt, encoder_bundle) -> SignalResult:
        """Run the full signal chain for the bar ending at ``dt``."""
        result = SignalResult(cost_gate=self.cost_gate)
        row = self._dt_to_row.get(pd.Timestamp(dt))
        if row is None:
            result.reason = REASON_NO_WINDOW
            return result
        if encoder_bundle is None or self.library.embeddings is None:
            result.reason = REASON_NO_SAMPLES
            return result

        x = self._features_full[row]
        if not np.isfinite(x).all():
            result.reason = REASON_NO_NORM
            return result

        v_now = encoder_bundle.encode_single(x)
        result.v_norm = float(np.linalg.norm(v_now))
        result.encoder_version = encoder_bundle.version
        result.n_lib = self.library.n

        positions, sims = self.library.query(
            dt,
            v_now,
            self.sim_threshold,
            self.top_n,
            self.window_bars,
            self.horizon_bars,
        )
        if len(positions) == 0:
            result.reason = REASON_NO_SAMPLES
            return result
        result.n_after_excl = len(positions)

        adj = np.sign(sims - self.sim_neutral) * self.library.label_fr[positions]
        n_sel = int(len(adj))
        p_hat = float((adj > 0).mean())
        er = float(adj.mean())
        result.n_selected = n_sel
        result.p_hat = p_hat
        result.p_low = wilson_lower(p_hat, n_sel)
        result.expected_return = er
        result.top_sim_mean = float(sims.mean())
        result.top_sim_min = float(sims.min())

        decision, reason = build_decision(
            n_sel,
            result.p_low,
            er,
            self.cost_gate,
            self.prob_threshold,
            self.min_matches,
        )
        result.decision = decision
        result.reason = reason
        return result


# ---------------------------------------------------------------------------
# Backtrader strategy (thin integration layer, D351-08 state machine)
# ---------------------------------------------------------------------------


class FnnEmbeddingStrategy(bt.Strategy):
    """Thin strategy wrapper: engine + rolling trainer + execution."""

    params = (
        ("window_bars", 75),
        ("horizon_bars", 15),
        ("top_n", 30),
        ("sim_threshold", 0.8),
        ("prob_threshold", 0.75),
        ("min_matches", 10),
        ("k_cost", 1.5),
        ("exit_multiple", 3.0),
        ("sim_neutral", 0.5),
        ("atr_floor", 1.0),
        ("spread_floor", 1.5),
        ("size", 1.0),
        ("use_bracket", True),  # OCO stop/take bracket; False = horizon exit only
        ("retrain_freq", 20),
        ("spread_cost_pct", 0.00015),
        ("print_log", True),
        ("signals_path", None),
        ("engine", None),
        ("trainer", None),
    )

    def __init__(self) -> None:
        if self.p.engine is None:
            raise ValueError("FnnEmbeddingStrategy requires an FnnRetrievalEngine")
        if self.p.trainer is None:
            raise ValueError("FnnEmbeddingStrategy requires a RollingTrainer")
        self.engine = self.p.engine
        self.trainer = self.p.trainer
        self.signal_log: list = []
        self.closed_trades: list = []
        self.equity_curve: list = []
        self.total_entries = 0
        self.stop_or_take_count = 0
        self.retrain_count = 0
        self.encoder_versions_used: set = set()
        self._current_day = None
        self._days_seen = 0
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
        self._atr_fast = 0.0
        self._signals_fh = None
        if self.p.signals_path:
            path = Path(self.p.signals_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._signals_fh = path.open("a", encoding="utf-8")
        self._adopt_encoder("init")

    # -- lifecycle -------------------------------------------------------

    def stop(self) -> None:
        if self._signals_fh:
            self._signals_fh.close()

    def log(self, text: str) -> None:
        if self.p.print_log:
            print(text)

    def _adopt_encoder(self, trigger: str) -> None:
        """Point library embeddings at the trainer's current bundle."""
        bundle = self.trainer.current_bundle()
        if bundle is None:
            return
        self.trainer.apply_to_library(self.engine.library)
        self.encoder_versions_used.add(bundle.version)
        self.log("encoder=%s library=%d (%s)" % (bundle.version, self.engine.library.n, trigger))

    def _maybe_retrain(self, dt) -> None:
        day = dt.date()
        if self._current_day is None:
            self._current_day = day
            return
        if day != self._current_day:
            self._days_seen += 1
            self._current_day = day
            if self._days_seen % self.p.retrain_freq == 0:
                self.trainer.advance_to(pd.Timestamp(dt), trigger="retrain")
                self.retrain_count += 1
                self._adopt_encoder("retrain")

    # -- signal bookkeeping ----------------------------------------------

    def _record_signal(self, dt, decision: str, reason: str, result) -> None:
        row = {
            "dt": dt.isoformat(),
            "decision": decision,
            "reason": reason,
            "n_lib": result.n_lib if result else 0,
            "n_after_excl": result.n_after_excl if result else 0,
            "n_selected": result.n_selected if result else 0,
            "top_sim_mean": result.top_sim_mean if result else 0.0,
            "top_sim_min": result.top_sim_min if result else 0.0,
            "v_norm": result.v_norm if result else 0.0,
            "encoder_version": result.encoder_version if result else "",
            "p_hat": result.p_hat if result else 0.0,
            "p_low": result.p_low if result else 0.0,
            "expected_return": result.expected_return if result else 0.0,
            "cost_gate": result.cost_gate if result else 0.0,
        }
        self.signal_log.append(row)
        if self._signals_fh:
            self._signals_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if self.p.print_log and decision != DECISION_SKIP:
            self.log(
                "%s %s n=%d p_low=%.4f er=%.2e gate=%.2e"
                % (
                    dt,
                    decision,
                    row["n_selected"],
                    row["p_low"],
                    row["expected_return"],
                    row["cost_gate"],
                )
            )

    # -- core loop --------------------------------------------------------

    def next(self) -> None:
        dt = self.data.datetime.datetime(0)
        self.equity_curve.append(float(self.broker.getvalue()))
        self._maybe_retrain(dt)
        self._update_atr_fast()

        if self.position:
            self._record_signal(dt, DECISION_SKIP, REASON_POSITION_OPEN, None)
            self._bars_held += 1
            if self._bars_held >= self.p.horizon_bars and not self._exit_submitted:
                self._cancel_bracket()
                self.close()
                self._exit_submitted = True
                self._exit_kind = "HORIZON"
            return

        if self.trainer.current_bundle() is None:
            # Lazy initial encoder: train as soon as MIN_TRAIN_SAMPLES
            # labels are realised before the decision instant (walk-forward).
            if self.trainer.advance_to(pd.Timestamp(dt), trigger="lazy-init") is not None:
                self._adopt_encoder("lazy-init")
            else:
                result = SignalResult(cost_gate=self.engine.cost_gate)
                result.reason = REASON_NO_SAMPLES
                self._record_signal(dt, DECISION_SKIP, REASON_NO_SAMPLES, result)
                return

        result = self.engine.evaluate(dt, self.trainer.current_bundle())
        self._record_signal(dt, result.decision, result.reason, result)
        if result.decision == DECISION_LONG:
            self._pending_er = result.expected_return
            order = self.buy(size=self.p.size)
            self._entry_ref = order.ref
        elif result.decision == DECISION_SHORT:
            self._pending_er = result.expected_return
            order = self.sell(size=self.p.size)
            self._entry_ref = order.ref

    def _update_atr_fast(self) -> None:
        """Bar-level fast ATR over the last 14 M1 bars (stop floor input)."""
        n = 14
        if len(self.data) < n:
            self._atr_fast = 0.0
            return
        prev_close = self.data.close[-1]
        trs = []
        for i in range(n):
            high_i = self.data.high[-i]
            low_i = self.data.low[-i]
            trs.append(max(high_i - low_i, abs(high_i - prev_close), abs(low_i - prev_close)))
            prev_close = self.data.close[-i]
        self._atr_fast = float(sum(trs) / n)

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
        spread_dollar = entry_price * self.p.spread_cost_pct
        take_price, stop_price = stop_take_prices_floored(
            entry_price,
            self._pending_er,
            self.p.exit_multiple,
            self._atr_fast,
            spread_dollar,
            self.p.atr_floor,
            self.p.spread_floor,
            is_long,
        )
        side = "long" if is_long else "short"
        self.log(
            "%s ENTRY %s @%.2f take=%.2f stop=%.2f er=%.2e atr=%.2f"
            % (dt, side, entry_price, take_price, stop_price, self._pending_er, self._atr_fast)
        )
        if is_long:
            self._take_order = self.sell(
                exectype=bt.Order.Limit, price=take_price, size=self.p.size
            )
            self._stop_order = self.sell(
                exectype=bt.Order.Stop, price=stop_price, size=self.p.size, oco=self._take_order
            )
        else:
            self._take_order = self.buy(exectype=bt.Order.Limit, price=take_price, size=self.p.size)
            self._stop_order = self.buy(
                exectype=bt.Order.Stop, price=stop_price, size=self.p.size, oco=self._take_order
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
