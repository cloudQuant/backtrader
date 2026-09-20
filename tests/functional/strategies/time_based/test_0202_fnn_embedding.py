"""Functional regression for the Iteration 35-1 FNN-embedding strategy.

Runs the example end-to-end on a two-week slice of the real XAUUSD_M1.csv
data with permissive gates (sim 0.3 / prob 0.6 / no cost gate) so the full
entry/exit/bracket path exercises, and asserts the metrics frozen at
implementation time (2026-09-20). With the default cost gate (k_cost 1.5)
the same slice produces zero trades — the cost-infeasibility outcome the
design (D351-15.5) requires to be recorded, never loosened.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def result():
    run_mod = importlib.import_module("examples.017_fnn_embedding.run")
    cfg = run_mod.load_yaml_config(REPO / "examples" / "017_fnn_embedding" / "config.yaml")
    cfg["data"]["fromdate"] = "2021-09-01"
    cfg["data"]["todate"] = "2021-09-15"
    # permissive gates to exercise the full trade path (see module docstring)
    cfg["params"]["sim_threshold"] = 0.3
    cfg["params"]["prob_threshold"] = 0.6
    cfg["params"]["min_matches"] = 5
    cfg["params"]["k_cost"] = 0.0
    cfg["training"]["epochs"] = 30
    # keep the run hermetic: disable file output in the test env
    cfg["logging"]["trade_logger"] = False
    cfg["logging"]["signals_jsonl"] = None
    return run_mod.run_single(cfg, write_results=False, enable_logging=False)


class TestFnnEmbeddingFunctional:
    def test_data_slice_loaded(self, result):
        assert result["rows"] == 13459
        assert result["data"]["fromdate"] == "2021-09-01 00:00:00"

    def test_trades_generated(self, result):
        assert result["trade_num"] == 1175
        assert result["buy_count"] == 6
        assert result["sell_count"] == 1169

    def test_pnl_frozen(self, result):
        assert result["sum_profit"] == pytest.approx(-840.6436478244193, abs=1e-9)
        assert result["final_value"] == pytest.approx(99159.35635217615, abs=1e-9)

    def test_win_loss_split(self, result):
        assert result["win_count"] == 151
        assert result["loss_count"] == 1024

    def test_exit_mix_frozen(self, result):
        assert result["stop_count"] == 471
        assert result["take_count"] == 529
        assert result["forced_liquidation_count"] == 0

    def test_signal_diagnostics_frozen(self, result):
        assert result["signal_count"] == 6554
        assert result["signal_skip_count"] == 5379
        assert result["avg_selected_matches"] == pytest.approx(28.351330049261083, abs=1e-9)
        assert result["avg_top_sim"] == pytest.approx(0.990117934889394, abs=1e-9)

    def test_library_and_encoder_state(self, result):
        assert result["lib_size"] == 12055
        assert result["retrain_count"] == 0
        assert result["encoder_versions_used"] == ["step000"]

    def test_drawdown_consistent_with_pnl(self, result):
        assert 0.0 <= result["max_drawdown"] < 0.02
