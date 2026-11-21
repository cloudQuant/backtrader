"""Cerebro coverage for XrsiDeMarkerHistogram's RSI source selector."""

import math

import backtrader as bt
import pandas as pd
import pytest


_PRICE_MODES = {
    "close": ("close", "price_close"),
    "open": ("open", "price_open", "OPEN"),
    "high": ("high", "price_high"),
    "low": ("low", "price_low"),
    "median": ("median", "price_median"),
    "typical": ("typical", "price_typical"),
    "weighted": ("weighted", "price_weighted"),
    "simpl": ("simpl", "price_simpl"),
    "quarter": ("quarter", "price_quarter"),
}


def _frame():
    count = 90
    close = [
        100.0 + index * 0.31 + math.sin(index * 0.41) * 2.1
        for index in range(count)
    ]
    open_ = [
        close[index] + (4.0 if index % 2 else -3.0) + math.sin(index * 0.17)
        for index in range(count)
    ]
    high = [max(open_[index], close[index]) + 1.0 for index in range(count)]
    low = [min(open_[index], close[index]) - 0.8 for index in range(count)]
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0] * count,
        },
        index=pd.date_range("2020-01-01", periods=count),
    )
    return frame


def _price_line(data, mode):
    """Independent fixture-side implementation of the contrib selector."""
    mode = str(mode).lower()
    if mode in ("price_open", "open"):
        return data.open
    if mode in ("price_high", "high"):
        return data.high
    if mode in ("price_low", "low"):
        return data.low
    if mode in ("price_median", "median"):
        return (data.high + data.low) / 2.0
    if mode in ("price_typical", "typical"):
        return (data.high + data.low + data.close) / 3.0
    if mode in ("price_weighted", "weighted"):
        return (2.0 * data.close + data.high + data.low) / 4.0
    if mode in ("price_simpl", "simpl"):
        return (data.open + data.close) / 2.0
    if mode in ("price_quarter", "quarter"):
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


def _run(runonce):
    period = 5
    modes = [mode for aliases in _PRICE_MODES.values() for mode in aliases]
    modes.append("unknown-mode")

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicators = {
                mode: bt.indicators.XrsiDeMarkerHistogram(
                    self.data,
                    ind_period=period,
                    rsi_price=mode,
                    xma_method="SMA",
                    x_length=1,
                )
                for mode in modes
            }
            self.demarker = bt.indicators.DeMarker(self.data, period=period)
            self.reference_rsi = {
                mode: bt.indicators.RSI(_price_line(self.data, mode), period=period)
                for mode in modes
            }

        def stop(self):
            self.result = {
                "minperiod": self.indicators["open"]._minperiod,
                "values": {
                    mode: list(indicator.value.array)
                    for mode, indicator in self.indicators.items()
                },
                "rsi": {
                    mode: list(indicator.rsi.array)
                    for mode, indicator in self.reference_rsi.items()
                },
                "demarker": list(self.demarker.demarker.array),
            }

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame()))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_rsi_price_selects_the_requested_source_and_matches_rsi_reference(runonce):
    result = _run(runonce)
    start = result["minperiod"] - 1

    assert result["minperiod"] == 11
    assert any(
        math.isfinite(open_value)
        and math.isfinite(close_value)
        and not math.isclose(open_value, close_value, rel_tol=1e-12, abs_tol=1e-12)
        for open_value, close_value in zip(
            result["values"]["open"], result["values"]["close"]
        )
    )

    for canonical, aliases in _PRICE_MODES.items():
        expected_source = aliases[0]
        expected_rsi = result["rsi"][expected_source]
        expected = [
            (rsi + 100.0 * demarker) / 2.0
            for rsi, demarker in zip(expected_rsi, result["demarker"])
        ]

        for mode in aliases:
            actual = result["values"][mode]
            assert len(actual) == len(expected)
            for index in range(start, len(expected)):
                assert actual[index] == pytest.approx(
                    expected[index], rel=1e-12, abs=1e-12
                ), f"{mode} at index {index}"

    assert result["values"]["unknown-mode"][start:] == pytest.approx(
        result["values"]["close"][start:], rel=1e-12, abs=1e-12
    )
