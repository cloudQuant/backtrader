"""Compare selected indicators only within their declared effective period.

These checks do not validate the formulas, pre-warmup outputs or recovery after
missing data. Equal NaNs establish parity only, not a successful calculation.
"""

import math

import backtrader as bt
import pandas as pd
import pytest


_INDICATORS = (
    "Color3rdGenXMAIndicator",
    "OsHMAIndicator",
    "JMASlopeIndicator",
    "RFTLIndicator",
    # SpreadZScore is in the R71-037 follow-up inventory, though not contrib.
    "SpreadZScore",
)


def _frames(*, missing):
    count = 350
    close = [
        100.0 + i * 0.13 + (i * 7 % 13) * 0.47 + math.sin(i * 0.3) * 2.2
        for i in range(count)
    ]
    open_ = [value - math.sin(i * 0.57) * 1.4 for i, value in enumerate(close)]
    high = [max(a, b) + 1.0 + (i % 3) * 0.2 for i, (a, b) in enumerate(zip(open_, close))]
    low = [min(a, b) - 0.9 - (i % 4) * 0.1 for i, (a, b) in enumerate(zip(open_, close))]
    first = {"open": open_, "high": high, "low": low, "close": close, "volume": [1000.0] * count}
    second = {key: list(values) for key, values in first.items()}
    second["close"] = [value * 0.94 + math.sin(i * 0.09) for i, value in enumerate(close)]
    if missing:
        # Index 320 is after every default minperiod, including Color3rdGen's.
        for key in ("open", "high", "low", "close"):
            first[key][320] = math.nan
    index = pd.date_range("2020-01-01", periods=count)
    return pd.DataFrame(first, index=index), pd.DataFrame(second, index=index)


def _run(name, runonce, *, missing):
    first, second = _frames(missing=missing)

    class Probe(bt.Strategy):
        def __init__(self):
            indicator_type = getattr(bt.indicators, name)
            if name == "SpreadZScore":
                self.indicator = indicator_type(self.data0, self.data1)
            else:
                self.indicator = indicator_type(self.data0)

        def stop(self):
            self.result = (
                self.indicator._minperiod,
                {
                    alias: list(line.array)
                    for alias, line in zip(
                        self.indicator.lines.getlinealiases(), self.indicator.lines
                    )
                },
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=first))
    if name == "SpreadZScore":
        cerebro.adddata(bt.feeds.PandasData(dataname=second))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


@pytest.mark.parametrize("name", _INDICATORS)
@pytest.mark.parametrize("missing", [False, True], ids=["finite", "one-missing-ohlc"])
def test_public_lines_match_from_declared_minperiod(name, missing):
    next_minperiod, next_lines = _run(name, False, missing=missing)
    once_minperiod, once_lines = _run(name, True, missing=missing)
    assert next_minperiod == once_minperiod
    assert 1 <= next_minperiod <= 350
    if missing:
        assert next_minperiod - 1 <= 320
    assert next_lines.keys() == once_lines.keys()
    for alias in next_lines:
        step, batch = next_lines[alias], once_lines[alias]
        assert len(step) == len(batch) == 350
        assert any(math.isfinite(value) for value in step[next_minperiod - 1 :]), alias
        for index in range(next_minperiod - 1, len(step)):
            if math.isnan(step[index]):
                assert math.isnan(batch[index]), f"{alias} at index {index}"
            else:
                assert batch[index] == pytest.approx(
                    step[index], rel=1e-12, abs=1e-12
                ), f"{alias} at index {index}"
