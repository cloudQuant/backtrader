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
    pytest.importorskip("torch", reason="PyTorch is optional for FNN example tests")
    run_mod = importlib.import_module("examples.backtest.017_fnn_embedding.run")
    cfg = run_mod.load_yaml_config(
        REPO / "examples" / "backtest" / "017_fnn_embedding" / "config.yaml"
    )
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
