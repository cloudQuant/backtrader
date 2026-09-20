"""Unit tests for the Iteration 35-1 FNN-embedding example.

Covers the numeric oracles defined in the iteration-35-1 design document
(D351-03 ~ D351-08) and the acceptance scenarios AC351-02 ~ AC351-12 that
are verifiable without the real XAUUSD data file.
"""

from __future__ import annotations

import importlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]

strategy_mod = importlib.import_module("examples.017_fnn_embedding.fnn_embedding_strategy")
autoenc_mod = importlib.import_module("examples.017_fnn_embedding.fnn_autoencoder")

DECISION_LONG = strategy_mod.DECISION_LONG
DECISION_SHORT = strategy_mod.DECISION_SHORT
DECISION_SKIP = strategy_mod.DECISION_SKIP
REASON_INSUFFICIENT = strategy_mod.REASON_INSUFFICIENT
REASON_COST_BELOW = strategy_mod.REASON_COST_BELOW
REASON_PROB_BELOW = strategy_mod.REASON_PROB_BELOW

compute_feature_matrix = strategy_mod.compute_feature_matrix
rolling_normalize = strategy_mod.rolling_normalize
wilson_lower = strategy_mod.wilson_lower
build_decision = strategy_mod.build_decision
stop_take_prices_floored = strategy_mod.stop_take_prices_floored
EmbeddingLibrary = strategy_mod.EmbeddingLibrary
validate_ohlcv = strategy_mod.DataValidationError

train_autoencoder = autoenc_mod.train_autoencoder


# ---------------------------------------------------------------------------
# Synthetic frame helpers (load_mt5_csv compatible)
# ---------------------------------------------------------------------------


def make_synthetic_frame(n_rows: int = 40, start: str = "2021-01-04 00:00") -> pd.DataFrame:
    """Deterministic per-minute frame: the first 15 bars are the oracle
    window (close 100..114, open close-0.5, high close+0.5, low close-1.0,
    tickvol 1..15); remaining bars extend the pattern."""
    idx = pd.date_range(start, periods=n_rows, freq="1min")
    close = np.array([100.0 + i for i in range(n_rows)])
    open_ = close - 0.5
    high = close + 0.5
    low = close - 1.0
    tickvol = np.array([float(i + 1) for i in range(n_rows)])
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "tickvol": tickvol,
            "volume": tickvol,
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# AC351-01 data validation
# ---------------------------------------------------------------------------


class TestDataValidation:
    def test_rejects_empty(self):
        with pytest.raises(validate_ohlcv):
            strategy_mod.validate_ohlcv(pd.DataFrame())

    def test_rejects_low_above_high(self):
        frame = make_synthetic_frame(10)
        frame.iloc[3, frame.columns.get_loc("high")] = 1.0
        with pytest.raises(validate_ohlcv):
            strategy_mod.validate_ohlcv(frame)


# ---------------------------------------------------------------------------
# AC351-02 feature oracle (D351-03 frozen list; hand-computed constants)
# ---------------------------------------------------------------------------


class TestFeatureOracle:
    def test_hand_computed_oracle(self):
        W, H = 15, 15
        feats, end_dts, label_fr, ready_dts = compute_feature_matrix(
            make_synthetic_frame(40), W, stride=1, horizon_bars=H
        )
        # ends 14..23: last window needs label rows end+1+H <= 39
        assert len(feats) == 10
        assert str(end_dts[0]) == "2021-01-04 00:14:00"
        f = feats[0]

        # f1/f2/f3: segment log returns at splits 7/15 and 10/15.
        assert f[0] == pytest.approx(math.log(107.0 / 100.0), abs=1e-10)
        assert f[1] == pytest.approx(math.log(110.0 / 107.0), abs=1e-10)
        assert f[2] == pytest.approx(math.log(114.0 / 110.0), abs=1e-10)

        # f5: all log returns positive -> RSI = 100 (within the EPS floor).
        assert f[4] == pytest.approx(100.0, abs=1e-6)

        # f6: momentum.
        assert f[5] == pytest.approx(0.14, abs=1e-12)

        # f7: close position within [99, 114.5] range.
        assert f[6] == pytest.approx(15.0 / 15.5, abs=1e-12)

        # f8/f9/f10: constant candle anatomy 1/3 each.
        assert f[7] == pytest.approx(1.0 / 3.0, abs=1e-12)
        assert f[8] == pytest.approx(1.0 / 3.0, abs=1e-12)
        assert f[9] == pytest.approx(1.0 / 3.0, abs=1e-12)

        # f4/f11/f12: independent recomputation (second implementation path).
        lr = np.diff(np.log(np.array([100.0 + i for i in range(15)])))
        assert f[3] == pytest.approx(float(lr.std(ddof=1)) * math.sqrt(14), abs=1e-10)
        log_vol = np.log(np.arange(1, 16, dtype=float) + 1.0)  # ln(v+1), design D351-03
        assert f[10] == pytest.approx(float(log_vol.mean()), abs=1e-12)
        front = log_vol[:7].mean()
        back = log_vol[7:].mean()
        assert f[11] == pytest.approx(back / (front + 1e-12), abs=1e-12)

        # label: ln(open[end+1+H] / open[end+1]) with row-index convention.
        # end=14 -> open[30]=129.5 over open[15]=114.5 (open = close - 0.5).
        assert label_fr[0] == pytest.approx(math.log(129.5 / 114.5), abs=1e-12)
        assert str(ready_dts[0]) == "2021-01-04 00:30:00"

    def test_window_invalid_on_gap(self):
        frame = make_synthetic_frame(200)
        frame = frame.drop(index=frame.index[100])  # one-minute gap
        feats, *_ = compute_feature_matrix(frame, 15, stride=1, horizon_bars=15)
        # windows that contained the gap are dropped
        assert len(feats) == 200 - 1 - 15 - 16 + 1 - (15 - 1)

    def test_window_rejects_cross_day(self):
        # day 1: 00:00..23:59, day 2 starts fresh -> windows crossing
        # midnight must not exist
        frame = make_synthetic_frame(2880, start="2021-01-04 00:00")
        feats, end_dts, *_ = compute_feature_matrix(frame, 75, stride=1, horizon_bars=15)
        days = pd.DatetimeIndex(end_dts).date
        assert len(set(days)) == 2  # both days contribute windows
        # no window ends in the first W-1 minutes of day 2
        d2 = pd.DatetimeIndex(end_dts)[days == pd.Timestamp("2021-01-05").date()]
        assert all(t.hour * 60 + t.minute >= 74 for t in d2)


# ---------------------------------------------------------------------------
# AC351-03 rolling normalisation, no lookahead
# ---------------------------------------------------------------------------


class TestRollingNormalize:
    def test_no_lookahead(self):
        rng = np.random.default_rng(7)
        X = rng.normal(0.0, 1.0, size=(3000, 12))
        base, valid = rolling_normalize(X, 2000, 500)
        X2 = X.copy()
        X2[2500:] *= 3.0
        alt, _ = rolling_normalize(X2, 2000, 500)
        assert np.array_equal(base[:2500], alt[:2500])
        assert valid[:499].sum() == 0  # below norm_min
        assert valid[500:].all()

    def test_zero_std_feature_zeroed(self):
        X = np.ones((600, 12))
        X[:, 0] = 5.0  # constant -> zero std -> zeroed output
        out, valid = rolling_normalize(X, 200, 100)
        assert np.all(out[150:, 0] == 0.0)


# ---------------------------------------------------------------------------
# AC351-04 autoencoder determinism
# ---------------------------------------------------------------------------


class TestAutoencoder:
    def test_training_deterministic(self):
        rng = np.random.default_rng(3)
        X = rng.normal(0.0, 1.0, size=(500, 12)).astype(np.float32)
        state1, meta1 = train_autoencoder(
            X, embed_dim=4, epochs=15, lr=1e-3, batch=64, patience=5, seed=42
        )
        state2, meta2 = train_autoencoder(
            X, embed_dim=4, epochs=15, lr=1e-3, batch=64, patience=5, seed=42
        )
        for key in state1:
            assert np.array_equal(state1[key].numpy(), state2[key].numpy())
        assert meta1["final_loss"] == pytest.approx(meta2["final_loss"], abs=0.0)

    def test_forward_consistent(self):
        autoenc_mod.make_deterministic(42)
        model = autoenc_mod.Autoencoder(embed_dim=4)
        x = np.random.default_rng(1).normal(size=(3, 12)).astype(np.float32)
        e1 = autoenc_mod.EncoderBundle(model, "t").encode_matrix(x)
        e2 = autoenc_mod.EncoderBundle(model, "t").encode_matrix(x)
        assert np.array_equal(e1, e2)
        assert e1.shape == (3, 4)


# ---------------------------------------------------------------------------
# AC351-06/07/08 retrieval oracle + decorrelation + lazy labels
# ---------------------------------------------------------------------------


def make_mini_library():
    """Six-sample library with hand-set embeddings (design D351-06.4)."""
    times = [
        f"2021-01-04 0{h}:{m:02d}" for h, m in [(8, 0), (8, 1), (8, 40), (9, 20), (10, 0), (10, 40)]
    ]
    end_dts = pd.DatetimeIndex([pd.Timestamp(t) for t in times])
    features = np.arange(6 * 12, dtype=np.float32).reshape(6, 12) / 100.0
    labels = np.array([0.001, -0.001, 0.002, 0.003, -0.002, 0.001])
    ready = end_dts + pd.Timedelta(minutes=16)
    lib = EmbeddingLibrary(features, np.ones(6, bool), end_dts, labels, ready)
    lib.embeddings = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 1.0, 0.0],
            [-1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
        ],
        dtype=np.float32,
    )
    return lib


class TestRetrieval:
    def test_mini_library_oracle(self):
        lib = make_mini_library()
        t0 = pd.Timestamp("2021-01-04 12:30")
        pos, sims = lib.query(t0, np.array([1.0, 0.0, 0.0]), 0.5, 3, 75, 15)
        # expected: e1 (1.0), e5 (1.0), e3 (0.70711); e6 (0.577) 4th, cut by top_n
        assert list(pos) == [0, 4, 2]
        assert sims[0] == pytest.approx(1.0, abs=1e-7)
        assert sims[1] == pytest.approx(1.0, abs=1e-7)
        assert sims[2] == pytest.approx(math.sqrt(2) / 2, abs=1e-7)

    def test_decorrelation_distance(self):
        lib = make_mini_library()
        # move e5 next to e1 (within dedup gap of 37 minutes) -> dropped
        end = list(lib.end_dts)
        end[4] = pd.Timestamp("2021-01-04 08:20")
        lib.end_dts = pd.DatetimeIndex(end)
        lib._end_ns = strategy_mod._ns_int64(lib.end_dts)
        lib._end_epoch_min = lib._end_ns // 60_000_000_000
        ready = list(lib.label_ready_dts)
        ready[4] = end[4] + pd.Timedelta(minutes=16)
        lib.label_ready_dts = pd.DatetimeIndex(ready)
        lib.label_ready_ns = strategy_mod._ns_int64(lib.label_ready_dts)
        pos, sims = lib.query(
            pd.Timestamp("2021-01-04 12:30"), np.array([1.0, 0.0, 0.0]), 0.5, 5, 75, 15
        )
        mins = [int(lib._end_epoch_min[p]) for p in pos]
        for i in range(len(mins)):
            for j in range(i + 1, len(mins)):
                assert abs(mins[i] - mins[j]) >= 37

    def test_lazy_labels_and_exclusion(self):
        lib = make_mini_library()
        v = np.array([1.0, 0.0, 0.0])
        # t0 = 08:50: label_ready cuts at 08:50 (rows ending 08:00/08:01 only
        # have realised labels); exclusion (>= 90 min) rejects both.
        pos, _ = lib.query(pd.Timestamp("2021-01-04 08:50"), v, -1.0, 5, 75, 15)
        assert len(pos) == 0
        # t0 = 08:20: 08:01 row not yet realised (ready 08:17 is realised!)
        # -> 08:00 (ready 08:16) passes labels but fails exclusion (20 min).
        pos, _ = lib.query(pd.Timestamp("2021-01-04 08:20"), v, -1.0, 5, 75, 15)
        assert len(pos) == 0


# ---------------------------------------------------------------------------
# AC351-09/10/11 Wilson oracle, cost gate, direction mapping
# ---------------------------------------------------------------------------


class TestDecisionChain:
    @pytest.mark.parametrize(
        "p_hat,n,expected",
        [
            (0.80, 20, 0.5840),
            (0.90, 50, 0.7864),
            (0.80, 30, 0.6269),
            (0.90, 30, 0.7438),
        ],
    )
    def test_wilson_oracle(self, p_hat, n, expected):
        assert wilson_lower(p_hat, n) == pytest.approx(expected, abs=1e-4)

    def test_cost_gate_boundaries(self):
        gate = 1.5 * (2 * 0.0002 + 0.00015)  # 8.25e-4
        assert gate == pytest.approx(8.25e-4, abs=1e-12)
        # er below gate -> COST_BELOW even with perfect probability
        assert build_decision(50, 0.99, 8.24e-4, gate, 0.75, 10) == (
            DECISION_SKIP,
            REASON_COST_BELOW,
        )
        # er at the gate passes to the probability stage
        assert build_decision(50, 0.60, 8.25e-4, gate, 0.75, 10) == (
            DECISION_SKIP,
            REASON_PROB_BELOW,
        )
        assert build_decision(50, 0.80, 9e-4, gate, 0.75, 10) == (DECISION_LONG, "")

    def test_insufficient_matches_first(self):
        assert build_decision(9, 0.99, 9e-4, 0.0, 0.75, 10) == (DECISION_SKIP, REASON_INSUFFICIENT)

    def test_direction_symmetry(self):
        # p_low >= 0.75 -> LONG; p_low <= 0.25 -> SHORT; else PROB_BELOW
        assert build_decision(50, 0.80, 9e-4, 0.0, 0.75, 10)[0] == DECISION_LONG
        assert build_decision(50, 0.20, 9e-4, 0.0, 0.75, 10)[0] == DECISION_SHORT
        assert build_decision(50, 0.50, 9e-4, 0.0, 0.75, 10) == (DECISION_SKIP, REASON_PROB_BELOW)

    def test_adj_sign_mapping(self):
        # four-quadrant equivalence: sign(sim - neutral) * fr
        neutral = 0.5
        cases = [
            (0.9, +0.001, +1),  # positively similar, up history -> long bias
            (0.9, -0.001, -1),
            (0.3, +0.001, -1),  # anti-similar mirrors
            (0.3, -0.001, +1),
        ]
        for sim, fr, expected_sign in cases:
            adj = np.sign(sim - neutral) * fr
            assert np.sign(adj) == expected_sign


# ---------------------------------------------------------------------------
# AC351-12 floored bracket prices (D351-08.2 oracle)
# ---------------------------------------------------------------------------


class TestFlooredBracket:
    def test_floor_active(self):
        take, stop = stop_take_prices_floored(
            entry=2000.0,
            expected_return=1e-4,
            exit_multiple=3.0,
            atr_fast=0.80,
            spread_dollar=0.30,
            atr_floor=1.0,
            spread_floor=1.5,
            is_long=True,
        )
        m = math.log(2000.80 / 2000.0)
        assert take == pytest.approx(2000.0 * math.exp(m), rel=1e-6)
        assert stop == pytest.approx(2000.0 * math.exp(-m), rel=1e-6)
        assert take == pytest.approx(2000.80, abs=1e-3)
        assert stop == pytest.approx(1999.20, abs=1e-3)

    def test_floor_inactive_falls_back_to_multiple(self):
        take, stop = stop_take_prices_floored(
            entry=2000.0,
            expected_return=1e-4,
            exit_multiple=3.0,
            atr_fast=0.05,
            spread_dollar=0.30,
            atr_floor=1.0,
            spread_floor=1.5,
            is_long=True,
        )
        m = 3.0e-4  # nominal dominates: floor = max(0.05, 0.45) = 0.45 -> ln(1.000225) < 3e-4
        assert take == pytest.approx(2000.0 * math.exp(m), rel=1e-6)
        assert stop == pytest.approx(2000.0 * math.exp(-m), rel=1e-6)

    def test_short_mirrored(self):
        take, stop = stop_take_prices_floored(
            entry=2000.0,
            expected_return=1e-4,
            exit_multiple=3.0,
            atr_fast=0.80,
            spread_dollar=0.30,
            atr_floor=1.0,
            spread_floor=1.5,
            is_long=False,
        )
        assert take < 2000.0 < stop
