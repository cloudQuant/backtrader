"""R71-038 regression coverage for ASCtrend MRO period selection."""

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.as_ctrend_indicator import ASCtrendIndicator


RISK = 4
MINPERIOD = 12
DEFAULT_WPR_INDEX = 2
WPR_PERIODS = (3, 4, 3 + RISK * 2)
SCENARIOS = (
    ("mro1-only", (110.0,) * 20, True, False, 0),
    ("mro2-only", (90.0,) * 20, False, True, 1),
    (
        "both",
        (100.0,) * 9 + (110.0,) * 3 + (90.0,) * 8,
        True,
        True,
        1,
    ),
    ("neither", (100.0,) * 20, False, False, DEFAULT_WPR_INDEX),
)


def _make_frame(closes):
    """Build deterministic OHLC bars whose WPR ranges are known."""
    return pd.DataFrame(
        {
            "open": closes,
            "high": [110.0] * len(closes),
            "low": [90.0] * len(closes),
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D"),
    )


def _oracle_wpr_score(frame, end_index, period):
    """Return 100 - abs(WPR), independently from the indicator helper."""
    if end_index < period:
        wpr = 0.0
    else:
        start = end_index - period + 1
        highs = [float(value) for value in frame["high"].iloc[start : end_index + 1]]
        lows = [float(value) for value in frame["low"].iloc[start : end_index + 1]]
        close = float(frame["close"].iloc[end_index])
        highest = max(highs)
        lowest = min(lows)
        wpr = 0.0 if highest == lowest else -100.0 * (highest - close) / (highest - lowest)
    return 100.0 - abs(wpr)


def _oracle_period_selections(frame):
    """Apply MRO1 then MRO2 as independent overrides of the default index."""
    selections = []
    for current in range(MINPERIOD - 1, len(frame)):
        mro1 = False
        for bars_ago in range(1, RISK * 2 + 1):
            index = current - bars_ago
            if index < 0:
                break
            if _oracle_wpr_score(frame, index, WPR_PERIODS[0]) > 67 + RISK:
                mro1 = True
                break

        mro2 = False
        for bars_ago in range(1, RISK * 2 + 1):
            index = current - bars_ago
            if index < 0:
                break
            if _oracle_wpr_score(frame, index, WPR_PERIODS[1]) < 33 - RISK:
                mro2 = True
                break

        selected = DEFAULT_WPR_INDEX
        if mro1:
            selected = 0
        if mro2:
            selected = 1
        selections.append((mro1, mro2, selected))
    return selections


def _run_cerebro(frame, runonce):
    """Run the production indicator path and observe its selected WPR index."""
    result = {}

    class SelectionProbe(ASCtrendIndicator):
        def __init__(self):
            super().__init__()
            self._selected_period_indices = []

        def _get_wpr_val(self, period_idx, ago):
            if ago == 0:
                self._selected_period_indices.append(period_idx)
            return super()._get_wpr_val(period_idx, ago)

    class ASCtrendProbeStrategy(bt.Strategy):
        def __init__(self):
            self.indicator = SelectionProbe(self.data, risk=RISK)

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            result["selections"] = list(self.indicator._selected_period_indices)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ASCtrendProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    return result


@pytest.mark.parametrize("runonce", (False, True))
@pytest.mark.parametrize(
    "scenario, closes, expected_mro1, expected_mro2, expected_index",
    SCENARIOS,
    ids=[scenario[0] for scenario in SCENARIOS],
)
def test_as_ctrend_mro_conditions_select_period_from_independent_oracle(
    runonce, scenario, closes, expected_mro1, expected_mro2, expected_index
):
    """The four independent MRO cases retain their intended period selection."""
    frame = _make_frame(closes)
    oracle = _oracle_period_selections(frame)
    result = _run_cerebro(frame, runonce)

    assert result["minperiod"] == MINPERIOD
    assert len(result["selections"]) == len(frame) - MINPERIOD + 1
    assert oracle[-1] == (expected_mro1, expected_mro2, expected_index)
    assert result["selections"] == [selected for _, _, selected in oracle]
