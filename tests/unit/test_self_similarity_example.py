"""Unit tests for the Iteration 35 self-similarity example.

Covers the numeric oracles defined in the iteration-35 design document
(D35-03 ~ D35-07) and the acceptance scenarios AC35-01 ~ AC35-10 that are
verifiable without the real XAUUSD data file.
"""

from __future__ import annotations

import importlib
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]

strategy_mod = importlib.import_module("examples.016_self_similarity.self_similarity_strategy")

DECISION_LONG = strategy_mod.DECISION_LONG
DECISION_SHORT = strategy_mod.DECISION_SHORT
DECISION_SKIP = strategy_mod.DECISION_SKIP
REASON_NO_WINDOW = strategy_mod.REASON_NO_WINDOW
REASON_NO_CANDIDATES = strategy_mod.REASON_NO_CANDIDATES
REASON_INSUFFICIENT = strategy_mod.REASON_INSUFFICIENT_MATCHES
REASON_NEG_EXP = strategy_mod.REASON_NEGATIVE_EXPECTATION
REASON_PROB_BELOW = strategy_mod.REASON_PROB_BELOW
REASON_POSITION_OPEN = strategy_mod.REASON_POSITION_OPEN

DataValidationError = strategy_mod.DataValidationError
SimilarityEngine = strategy_mod.SimilarityEngine
SelfSimilarityStrategy = strategy_mod.SelfSimilarityStrategy
build_decision = strategy_mod.build_decision
directional_stats = strategy_mod.directional_stats
pearson_corr = strategy_mod.pearson_corr
stop_take_prices = strategy_mod.stop_take_prices
validate_ohlcv = strategy_mod.validate_ohlcv


# ---------------------------------------------------------------------------
# Synthetic data helpers (load_mt5_csv compatible frame)
# ---------------------------------------------------------------------------


def make_m1_frame(n_days, close_fn, drops=(), start="2021-01-04"):
    """Build a per-minute OHLCV frame with per-day close patterns.

    close_fn(day_idx_array, tod_array) -> close price array (vectorised).
    drops: iterable of (day_idx, tod_start, tod_end) inclusive ranges removed.
    """
    tod = np.arange(1440)
    day_idx = np.repeat(np.arange(n_days), 1440)
    tods = np.tile(tod, n_days)
    close = close_fn(day_idx, tods)
    open_ = close.copy()
    open_[1:] = close[:-1]
    first_of_day = np.tile(np.concatenate(([True], np.zeros(1439, bool))), n_days)
    open_[first_of_day] = close[first_of_day]
    base = pd.Timestamp(start)
    index = pd.DatetimeIndex(
        [base + pd.Timedelta(days=int(d), minutes=int(t)) for d, t in zip(day_idx, tods)]
    )
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.01,
            "low": np.minimum(open_, close) - 0.01,
            "close": close,
            "volume": 100.0,
            "openinterest": 0.0,
        },
        index=index,
    )
    for day_idx_, t0, t1 in drops:
        mask = frame.index.map(
            lambda ts, d=day_idx_, a=t0, b=t1: (
                (ts.date() - base.date()).days == d and a <= ts.hour * 60 + ts.minute <= b
            )
        )
        frame = frame[~np.asarray(mask)]
    return frame


def sine_daily(n_days, scale=8.0, base=1000.0):
    """Perfectly repeating intraday sine pattern (close prices)."""

    def close_fn(day_idx, tod):
        return base + scale * np.sin(2.0 * np.pi * tod / 1440.0)

    return close_fn


# ---------------------------------------------------------------------------
# AC35-01 data validation
# ---------------------------------------------------------------------------


class TestValidateOhlcv:
    def test_rejects_empty_frame(self):
        with pytest.raises(DataValidationError, match="DATA_INVALID"):
            validate_ohlcv(pd.DataFrame(columns=["open", "high", "low", "close"]))

    def test_rejects_unsorted_index(self):
        frame = make_m1_frame(1, sine_daily(1))
        shuffled = frame.iloc[::-1]
        with pytest.raises(DataValidationError, match="DATA_INVALID"):
            validate_ohlcv(shuffled)

    def test_rejects_low_above_high(self):
        frame = make_m1_frame(1, sine_daily(1)).copy()
        frame.iloc[10, frame.columns.get_loc("low")] = frame.iloc[10]["high"] + 5.0
        with pytest.raises(DataValidationError, match="DATA_INVALID"):
            validate_ohlcv(frame)

    def test_accepts_valid_frame(self):
        frame = make_m1_frame(2, sine_daily(2))
        validate_ohlcv(frame)  # must not raise


# ---------------------------------------------------------------------------
# AC35-02 window construction
# ---------------------------------------------------------------------------

WINDOW = 75


class TestWindowConstruction:
    def test_complete_day_produces_window(self):
        engine = SimilarityEngine(make_m1_frame(3, sine_daily(3)), WINDOW, 15, 60)
        result = engine.evaluate(pd.Timestamp("2021-01-06 10:30"))
        assert result.reason != REASON_NO_WINDOW

    def test_gap_inside_window_blocks_signal(self):
        drops = [(1, 9 * 60, 9 * 60 + 30)]  # day idx 1: 09:00-09:30 removed (31 bars)
        engine = SimilarityEngine(make_m1_frame(3, sine_daily(3), drops), WINDOW, 15, 60)
        assert engine.evaluate(pd.Timestamp("2021-01-05 09:45")).reason == REASON_NO_WINDOW
        # first valid bar: gap leaves 09:31; window [09:31, 10:45] has 75 bars
        assert engine.evaluate(pd.Timestamp("2021-01-05 10:44")).reason == REASON_NO_WINDOW
        assert engine.evaluate(pd.Timestamp("2021-01-05 10:45")).reason != REASON_NO_WINDOW

    def test_window_must_not_cross_day_boundary(self):
        engine = SimilarityEngine(make_m1_frame(3, sine_daily(3)), WINDOW, 15, 60)
        assert engine.evaluate(pd.Timestamp("2021-01-05 01:13")).reason == REASON_NO_WINDOW
        assert engine.evaluate(pd.Timestamp("2021-01-05 01:14")).reason != REASON_NO_WINDOW


# ---------------------------------------------------------------------------
# AC35-03 candidate pool
# ---------------------------------------------------------------------------


class TestCandidatePool:
    def make_engine(self, lookback):
        # 70 days; d10 window anchor span gapped, d20 forward span gapped,
        # d30 gapped outside both spans (still a valid candidate).
        drops = [
            (10, 10 * 60, 10 * 60 + 5),
            (20, 10 * 60 + 35, 10 * 60 + 35),
            (30, 12 * 60, 12 * 60),
        ]
        return SimilarityEngine(make_m1_frame(70, sine_daily(70), drops), WINDOW, 15, lookback)

    def test_pool_takes_last_sixty_valid_days_excluding_current(self):
        engine = self.make_engine(60)
        days = engine.candidates_for(pd.Timestamp("2021-03-14 10:30"))
        assert len(days) == 60
        # current day 2021-03-14 is day idx 69 (2021-01-04 + 69 days)
        current = (pd.Timestamp("2021-01-04") + pd.Timedelta(days=69)).date()
        assert current not in days
        # day idx 10 (2021-01-14) and idx 20 (2021-01-24) invalid at this anchor
        assert date(2021, 1, 14) not in days
        assert date(2021, 1, 24) not in days
        # day idx 30 gap at 12:00 is outside the 09:15-10:46 spans: still valid
        assert date(2021, 2, 3) in days
        # most recent valid day first
        assert days[0] == (pd.Timestamp("2021-01-04") + pd.Timedelta(days=68)).date()

    def test_pool_capped_by_available_valid_days(self):
        engine = self.make_engine(200)
        days = engine.candidates_for(pd.Timestamp("2021-03-14 10:30"))
        # 69 historical days minus 2 invalid = 67
        assert len(days) == 67

    def test_no_candidates_on_first_day(self):
        engine = SimilarityEngine(make_m1_frame(3, sine_daily(3)), WINDOW, 15, 60)
        result = engine.evaluate(pd.Timestamp("2021-01-04 12:00"))
        assert result.reason == REASON_NO_CANDIDATES


# ---------------------------------------------------------------------------
# AC35-04 Pearson oracle
# ---------------------------------------------------------------------------


class TestPearsonOracle:
    def test_design_oracle(self):
        r = np.array([0.01, 0.02, -0.01, 0.005])
        matrix = np.array(
            [
                2 * r,  # identical shape -> +1
                -2 * r,  # mirrored -> -1
                r + 0.1,  # shifted -> +1 (translation invariance)
                [1.0, 0.0, 0.0, 0.0],  # hand-computed -> 0.2000
                [0.5, 0.5, 0.5, 0.5],  # zero variance -> NaN
            ]
        )
        corr = pearson_corr(matrix, r)
        assert corr[0] == pytest.approx(1.0, abs=1e-8)
        assert corr[1] == pytest.approx(-1.0, abs=1e-8)
        assert corr[2] == pytest.approx(1.0, abs=1e-8)
        assert corr[3] == pytest.approx(0.2000, abs=1e-8)
        assert math.isnan(corr[4])


# ---------------------------------------------------------------------------
# AC35-05 directional statistics oracle
# ---------------------------------------------------------------------------


class TestDirectionalStats:
    def test_design_oracle_mixed_pool(self):
        corr = np.array([0.8, 0.8, 0.8, 0.8, 0.8, -0.7, -0.7, -0.7, 0.55])
        fr = np.array(
            [0.00012, 0.00008, 0.00015, -0.00003, 0.00010, -0.00009, 0.00002, -0.00007, 0.005]
        )
        n_selected, up_prob, expected_return = directional_stats(corr, fr, 0.6)
        assert n_selected == 8
        assert up_prob == pytest.approx(0.75, abs=1e-10)
        assert expected_return == pytest.approx(7e-5, abs=1e-10)

    def test_all_selected_below_threshold(self):
        corr = np.array([0.3, -0.2])
        fr = np.array([0.001, -0.001])
        n_selected, up_prob, expected_return = directional_stats(corr, fr, 0.6)
        assert n_selected == 0
        assert math.isnan(up_prob) and math.isnan(expected_return)


# ---------------------------------------------------------------------------
# AC35-06 decision chain boundaries
# ---------------------------------------------------------------------------


class TestDecideChain:
    CASES = [
        ((8, 0.75, 7e-5), DECISION_LONG, None),
        ((8, 0.25, 7e-5), DECISION_SHORT, None),
        ((8, 0.7499, 7e-5), DECISION_SKIP, REASON_PROB_BELOW),
        ((8, 0.2501, 7e-5), DECISION_SKIP, REASON_PROB_BELOW),
        ((8, 0.90, 0.0), DECISION_SKIP, REASON_NEG_EXP),
        ((8, 0.90, -1e-6), DECISION_SKIP, REASON_NEG_EXP),
        ((4, 0.90, 1e-4), DECISION_SKIP, REASON_INSUFFICIENT),
    ]

    @pytest.mark.parametrize("inputs,decision,reason", CASES)
    def test_boundaries(self, inputs, decision, reason):
        got_decision, got_reason = build_decision(*inputs, prob_threshold=0.75, min_matches=5)
        assert got_decision == decision
        if reason is None:
            assert got_decision in (DECISION_LONG, DECISION_SHORT)
        else:
            assert got_reason == reason


# ---------------------------------------------------------------------------
# AC35-09 stop/take price oracle
# ---------------------------------------------------------------------------


class TestDirectionMapping:
    """AC35-07: four-quadrant mapping equals the unified adj formula."""

    def _decide_from_pool(self, corr_value, futures):
        corr = np.full(len(futures), corr_value)
        fr = np.asarray(futures)
        n, up, er = directional_stats(corr, fr, 0.6)
        return build_decision(n, up, er, prob_threshold=0.75, min_matches=2)

    def test_positive_corr_majority_up_predicts_long(self):
        decision, _ = self._decide_from_pool(0.8, [0.001, 0.002, 0.0015, -0.0002, 0.0012])
        assert decision == DECISION_LONG

    def test_positive_corr_majority_down_predicts_short(self):
        # majority down but the mean must stay positive for the expectation gate
        decision, _ = self._decide_from_pool(0.8, [-0.001, -0.001, -0.001, -0.001, 0.005])
        assert decision == DECISION_SHORT

    def test_negative_corr_majority_up_predicts_short(self):
        decision, _ = self._decide_from_pool(-0.8, [0.001, 0.001, 0.001, 0.001, -0.005])
        assert decision == DECISION_SHORT

    def test_negative_corr_majority_down_predicts_long(self):
        decision, _ = self._decide_from_pool(-0.8, [-0.001, -0.002, -0.0015, 0.0002, -0.0012])
        assert decision == DECISION_LONG


class TestStopTakePrices:
    def test_long_oracle(self):
        take, stop = stop_take_prices(2000.0, 2.1e-4, True)
        assert take == pytest.approx(2000.0 * math.exp(2.1e-4), rel=1e-8)
        assert stop == pytest.approx(2000.0 * math.exp(-2.1e-4), rel=1e-8)
        assert take == pytest.approx(2000.4200, abs=1e-3)
        assert stop == pytest.approx(1999.5800, abs=1e-3)

    def test_short_symmetry(self):
        take, stop = stop_take_prices(2000.0, 2.1e-4, False)
        assert take == pytest.approx(2000.0 * math.exp(-2.1e-4), rel=1e-8)
        assert stop == pytest.approx(2000.0 * math.exp(2.1e-4), rel=1e-8)

    def test_minimum_tick_distance(self):
        take, stop = stop_take_prices(2000.0, 1e-9, True, tick=0.01)
        assert take - 2000.0 >= 0.01 - 1e-12
        assert 2000.0 - stop >= 0.01 - 1e-12


# ---------------------------------------------------------------------------
# AC35-08 / AC35-10 end-to-end timing on synthetic repeating pattern
# ---------------------------------------------------------------------------


def run_synthetic_backtest(exit_multiple, days=6):
    import backtrader as bt

    frame = make_m1_frame(days, sine_daily(days))
    data = bt.feeds.PandasData(dataname=frame)
    engine = strategy_mod.SimilarityEngine(
        frame,
        WINDOW,
        15,
        3,
        corr_threshold=0.6,
        prob_threshold=0.75,
        min_matches=2,
    )
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.set_coc(False)
    cerebro.addstrategy(
        SelfSimilarityStrategy,
        window_bars=WINDOW,
        horizon_bars=15,
        lookback_days=3,
        corr_threshold=0.6,
        prob_threshold=0.75,
        exit_multiple=exit_multiple,
        min_matches=2,
        size=1.0,
        print_log=False,
        engine=engine,
    )
    strat = cerebro.run()[0]
    return strat, frame


class TestNoLookahead:
    """AC35-11: mutating bars after a cutoff must not change earlier decisions."""

    def test_perturbing_future_bars_preserves_past_signals(self):
        import backtrader as bt

        days = 6
        frame = make_m1_frame(days, sine_daily(days))
        cut = pd.Timestamp("2021-01-06 12:00")

        def run(frame_in):
            engine = strategy_mod.SimilarityEngine(frame_in, WINDOW, 15, 3, 0.6, 0.75, 2)
            cerebro = bt.Cerebro()
            cerebro.adddata(bt.feeds.PandasData(dataname=frame_in), name="T")
            cerebro.broker.setcash(100000.0)
            cerebro.addstrategy(
                SelfSimilarityStrategy,
                window_bars=WINDOW,
                horizon_bars=15,
                lookback_days=3,
                corr_threshold=0.6,
                prob_threshold=0.75,
                exit_multiple=50.0,
                min_matches=2,
                size=1.0,
                print_log=False,
                engine=engine,
            )
            return cerebro.run()[0]

        baseline = run(frame)
        perturbed = frame.copy()
        position = perturbed.index >= cut
        perturbed.loc[position, ["open", "high", "low", "close"]] *= 1.03
        mutated = run(perturbed)

        cut_iso = cut.isoformat()
        before_baseline = [s for s in baseline.signal_log if s["dt"] < cut_iso]
        before_mutated = [s for s in mutated.signal_log if s["dt"] < cut_iso]
        assert before_baseline
        assert before_baseline == before_mutated


class TestEndToEndTiming:
    def test_entry_next_open_exit_after_fifteen_bars(self):
        strat, frame = run_synthetic_backtest(exit_multiple=50.0)
        trades = strat.closed_trades
        assert trades, "synthetic repeating pattern must generate trades"
        first = trades[0]
        # first possible signal: day idx 2 (two candidate days satisfy
        # min_matches=2), tod 01:14 -> entry fills next open 01:15
        entry_dt = first["entry_dt"]
        exit_dt = first["exit_dt"]
        assert entry_dt == pd.Timestamp("2021-01-06 01:15")
        assert exit_dt == pd.Timestamp("2021-01-06 01:30")
        assert exit_dt - entry_dt == pd.Timedelta(minutes=15)
        assert first["entry_price"] == pytest.approx(frame.loc[entry_dt, "open"])
        assert first["exit_price"] == pytest.approx(frame.loc[exit_dt, "open"])

    def test_single_position_constraint(self):
        strat, _ = run_synthetic_backtest(exit_multiple=50.0)
        assert any(sig["reason"] == REASON_POSITION_OPEN for sig in strat.signal_log)
        # closed trades must not overlap: exit <= next entry
        for prev, nxt in zip(strat.closed_trades, strat.closed_trades[1:]):
            assert prev["exit_dt"] <= nxt["entry_dt"]

    def test_stop_or_take_closes_early_with_far_multiple(self):
        strat, frame = run_synthetic_backtest(exit_multiple=0.05)
        trades = strat.closed_trades
        assert trades
        # with a tiny multiple at least one trade must exit before the horizon
        early = [t for t in trades if t["exit_dt"] - t["entry_dt"] < pd.Timedelta(minutes=15)]
        assert early
        assert strat.stop_or_take_count > 0
        # no double close: closed trade count matches total entries
        assert len(trades) == strat.total_entries
