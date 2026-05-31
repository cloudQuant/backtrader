"""Benchmark for the vectorized (runonce) LineBuffer arithmetic hot path.

Exercises ``LineOwnOperation.once`` / ``LinesOperation._once_op`` — the
per-element operation loops that compute things like ``sma - ema`` in batch
mode. Used as the no-regression guard for R2-S4 (PERF203 try/except hoisting).

Marked ``slow`` so it only runs in the full suite / nightly, not the PR fast gate.
"""

import time

import numpy as np
import pandas as pd
import pytest

import backtrader as bt


def _run_once_workload(n=50000):
    idx = pd.date_range("2020-01-01", periods=n, freq="min")
    base = 100 + np.cumsum(np.random.randn(n)) * 0.1
    df = pd.DataFrame(
        {
            "open": base,
            "high": base + 0.5,
            "low": base - 0.5,
            "close": base,
            "volume": np.random.randint(1, 100, n).astype(float),
            "openinterest": 0.0,
        },
        index=idx,
    )

    class _S(bt.Strategy):
        def __init__(self):
            sma = bt.indicators.SMA(self.data.close, period=20)
            ema = bt.indicators.EMA(self.data.close, period=20)
            # binary + unary line operations -> the once() hot loops
            self.diff = sma - ema
            self.scaled = (sma + ema) / 2.0
            self.absd = abs(self.data.close - sma)

        def next(self):
            pass

    cerebro = bt.Cerebro(runonce=True, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(_S)
    cerebro.run()


@pytest.mark.slow
def test_runonce_lineops_baseline_under_30s():
    """50k bars with several line operations should finish well under 30s.

    Generous ceiling (CI runners vary widely); the point is to catch a gross
    regression in the vectorized once() path, not to assert a tight number.
    """
    np.random.seed(42)
    _run_once_workload()  # warmup
    start = time.perf_counter()
    _run_once_workload()
    elapsed = time.perf_counter() - start
    assert elapsed < 30.0, f"runonce lineops elapsed {elapsed:.2f}s exceeds 30s baseline"
