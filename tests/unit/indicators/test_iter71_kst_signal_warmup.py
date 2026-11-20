"""Regression tests for the KST signal warmup contract (R71-155)."""

import math

import backtrader as bt
import pandas as pd
import pytest


_KST_PARAMS = {
    "rp1": 10,
    "rp2": 15,
    "rp3": 20,
    "rp4": 30,
    "rma1": 10,
    "rma2": 10,
    "rma3": 10,
    "rma4": 10,
    "rsignal": 9,
    "rfactors": (1.0, 2.0, 3.0, 4.0),
}
_KST_FIRST_INDEX = max(
    _KST_PARAMS[f"rp{index}"] + _KST_PARAMS[f"rma{index}"] - 1
    for index in range(1, 5)
)


def _closes(length):
    """Return non-flat deterministic prices for independent formula checks."""
    return [
        100.0 + 0.4 * index + 3.0 * math.sin(index / 3.7) + 0.07 * (index % 7) ** 2
        for index in range(length)
    ]


def _frame(closes):
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )


def _reference_kst(closes, params=_KST_PARAMS):
    """Calculate ROC smoothing and signal windows without Backtrader helpers."""
    nan = float("nan")
    rcmas = []
    for index in range(1, 5):
        roc_period = params[f"rp{index}"]
        average_period = params[f"rma{index}"]
        roc = [nan] * len(closes)
        for bar in range(roc_period, len(closes)):
            previous = closes[bar - roc_period]
            roc[bar] = 0.0 if previous == 0.0 else 100.0 * (closes[bar] - previous) / previous

        rcma = [nan] * len(closes)
        first_average = roc_period + average_period - 1
        for bar in range(first_average, len(closes)):
            window = roc[bar - average_period + 1 : bar + 1]
            rcma[bar] = sum(window) / average_period
        rcmas.append(rcma)

    kst = [nan] * len(closes)
    factors = params["rfactors"]
    for bar in range(_KST_FIRST_INDEX, len(closes)):
        values = [rcma[bar] for rcma in rcmas]
        if all(math.isfinite(value) for value in values):
            kst[bar] = sum(factor * value for factor, value in zip(factors, values))

    signal = [nan] * len(closes)
    signal_period = params["rsignal"]
    for bar in range(len(closes)):
        start = bar - signal_period + 1
        if start >= 0:
            window = kst[start : bar + 1]
            if len(window) == signal_period and all(math.isfinite(value) for value in window):
                signal[bar] = sum(window) / signal_period

    return kst, signal


def _reference_sma(values, period, first_index):
    result = [float("nan")] * len(values)
    for bar in range(first_index, len(values)):
        window = values[bar - period + 1 : bar + 1]
        if len(window) == period and all(math.isfinite(value) for value in window):
            result[bar] = sum(window) / period
    return result


def _run_kst(closes, runonce):
    result = {}

    class KSTProbe(bt.Strategy):
        def __init__(self):
            self.kst = bt.indicators.KST(self.data.close, **_KST_PARAMS)
            self.kst_sma = bt.indicators.SMA(self.kst.kst, period=3)
            self.signal_sma = bt.indicators.SMA(self.kst.signal, period=3)

        def stop(self):
            result.update(
                {
                    "kst_minperiod": self.kst._minperiod,
                    "line_minperiods": [line._minperiod for line in self.kst.lines],
                    "kst_sma_minperiod": self.kst_sma._minperiod,
                    "signal_sma_minperiod": self.signal_sma._minperiod,
                    "kst": list(self.kst.kst.array),
                    "signal": list(self.kst.signal.array),
                    "kst_sma": list(self.kst_sma.array),
                    "signal_sma": list(self.signal_sma.array),
                }
            )

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(closes)))
    cerebro.addstrategy(KSTProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _assert_series_matches(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert math.isfinite(actual_value)
            assert actual_value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("runonce", (False, True))
@pytest.mark.parametrize(
    "length, expected_signal_count, expected_downstream_count",
    ((47, 0, 0), (48, 1, 0), (49, 2, 0), (50, 3, 1)),
)
def test_kst_warmup_boundaries_and_short_history(
    runonce, length, expected_signal_count, expected_downstream_count
):
    """The signal and its downstream SMA become valid at their declared bars."""
    closes = _closes(length)
    expected_kst, expected_signal = _reference_kst(closes)
    result = _run_kst(closes, runonce=runonce)

    assert result["kst_minperiod"] == 48
    assert result["line_minperiods"] == [48, 48]
    assert result["kst_sma_minperiod"] == result["signal_sma_minperiod"] == 50
    _assert_series_matches(result["kst"], expected_kst)
    _assert_series_matches(result["signal"], expected_signal)

    assert sum(math.isfinite(value) for value in result["signal"]) == expected_signal_count
    assert sum(math.isfinite(value) for value in result["kst_sma"]) == expected_downstream_count
    assert sum(math.isfinite(value) for value in result["signal_sma"]) == expected_downstream_count


@pytest.mark.parametrize("runonce", (False, True))
def test_kst_full_sequence_matches_independent_formula_and_downstream_minperiod(runonce):
    """Both Cerebro modes preserve all KST history and honor downstream warmup."""
    closes = _closes(72)
    expected_kst, expected_signal = _reference_kst(closes)
    result = _run_kst(closes, runonce=runonce)
    downstream_first_index = 48 + 3 - 2

    assert result["kst_minperiod"] == 48
    assert result["line_minperiods"] == [48, 48]
    assert result["kst_sma_minperiod"] == result["signal_sma_minperiod"] == 50
    _assert_series_matches(result["kst"], expected_kst)
    _assert_series_matches(result["signal"], expected_signal)
    _assert_series_matches(
        result["kst_sma"], _reference_sma(expected_kst, 3, downstream_first_index)
    )
    _assert_series_matches(
        result["signal_sma"], _reference_sma(expected_signal, 3, downstream_first_index)
    )
