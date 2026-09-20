"""Functional regression for the Iteration 35 self-similarity strategy.

Runs the example strategy end-to-end on a two-month slice of the real
XAUUSD_M1.csv data with a permissive correlation threshold (0.3) and asserts
the metrics frozen at implementation time (2026-09-20). With the default
0.6 threshold the same slice produces zero trades by design (measured
max|corr| median on real data is ~0.26); 0.3 is used so the regression
exercises the full entry/exit path.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def result():
    run_mod = importlib.import_module("examples.016_self_similarity.run")
    cfg = run_mod.load_yaml_config(REPO / "examples" / "016_self_similarity" / "config.yaml")
    cfg["params"]["corr_threshold"] = 0.3
    cfg["data"]["fromdate"] = "2021-09-01"
    cfg["data"]["todate"] = "2021-10-31"
    # keep the run hermetic: disable TradeLogger file output in the test env
    cfg["logging"]["trade_logger"] = False
    cfg["logging"]["signals_jsonl"] = None
    return run_mod.run_single(cfg, write_results=False)


class TestSelfSimilarityFunctional:
    def test_data_slice_loaded(self, result):
        assert result["rows"] == 58467
        assert result["data"]["fromdate"] == "2021-09-01 00:00:00"

    def test_trades_generated(self, result):
        assert result["trade_num"] == 6
        assert result["buy_count"] == 6
        assert result["sell_count"] == 0

    def test_pnl_frozen(self, result):
        assert result["sum_profit"] == pytest.approx(-7.366865761865451, abs=1e-9)
        assert result["final_value"] == pytest.approx(99992.63313423812, abs=1e-9)

    def test_win_loss_split(self, result):
        assert result["win_count"] == 3
        assert result["loss_count"] == 3

    def test_exit_mix_frozen(self, result):
        assert result["stop_count"] == 1
        assert result["take_count"] == 2

    def test_signal_diagnostics_frozen(self, result):
        assert result["signal_count"] == 58393
        assert result["signal_skip_count"] == 58387
        assert result["avg_selected_matches"] == pytest.approx(1.318988243676523, abs=1e-9)
        assert result["forced_liquidation_count"] == 0

    def test_drawdown_consistent_with_pnl(self, result):
        # tiny loss, tiny drawdown; sanity scale check only
        assert 0.0 <= result["max_drawdown"] < 1e-3
