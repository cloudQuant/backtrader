"""Public Cerebro checks for CandlesticksBW's indicator-visible inputs."""

import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicators.contrib.candlesticks_bw import CandlesticksBW


def _frame(n=160):
    closes = [100 + 0.04 * i + 3 * math.sin(i * 0.19) + math.cos(i * 0.07)
              for i in range(n)]
    opens = [v + (0.4 if i % 2 else -0.4) for i, v in enumerate(closes)]
    return pd.DataFrame({
        "open": opens,
        "high": [max(o, c) + 0.5 + (i % 3) * 0.1 for i, (o, c) in enumerate(zip(opens, closes))],
        "low": [min(o, c) - 0.5 - (i % 4) * 0.1 for i, (o, c) in enumerate(zip(opens, closes))],
        "close": closes,
        "volume": [100.] * n,
    }, index=pd.date_range("2024-01-01", periods=n, freq="min"))


def _reference(open_, close, highs, lows):
    # Reverse the captured history into chronological order and compute AO and
    # AC independently from the indicator's exposed sub-indicators.
    medians = [(h + l) / 2.0 for h, l in zip(highs[::-1], lows[::-1])]
    def ao(end):
        return sum(medians[end - 4:end + 1]) / 5.0 - sum(medians[end - 33:end + 1]) / 34.0
    ao_values = [ao(i) for i in range(33, 39)]
    current, previous = ao_values[-1], ao_values[-2]
    ac_current = current - sum(ao_values[1:]) / 5.0
    ac_previous = previous - sum(ao_values[:5]) / 5.0
    color = _color(current, previous, ac_current, ac_previous, open_, close)
    return current, previous, ac_current, ac_previous, color


def _color(current, previous, ac_current, ac_previous, open_, close):
    if not all(math.isfinite(value) for value in (current, previous, ac_current, ac_previous, open_, close)):
        return math.nan
    if current >= previous and ac_current >= ac_previous:
        color = 0.0 if open_ <= close else 1.0
    elif current <= previous and ac_current <= ac_previous:
        color = 5.0 if open_ >= close else 4.0
    else:
        color = 2.0 if open_ <= close else 3.0
    return color


def _run(frame, runonce, *, replay=False):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = CandlesticksBW(self.data)
            self.rows = []

        def next(self):
            highs = [float(self.data.high[-i]) for i in range(39)]
            lows = [float(self.data.low[-i]) for i in range(39)]
            self.rows.append((len(self.data), float(self.data.open[0]), float(self.data.close[0]),
                              highs, lows, float(self.ind.ao[0]), float(self.ind.ao[-1]),
                              float(self.ind.ac[0]), float(self.ind.ac[-1]), float(self.ind.color[0])))

    engine = bt.Cerebro(stdstats=False)
    feed = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes)
    if replay:
        engine.replaydata(feed, timeframe=bt.TimeFrame.Minutes, compression=3)
    else:
        engine.adddata(feed)
    engine.addstrategy(Probe)
    return engine.run(runonce=runonce, preload=True)[0].rows


def _check(rows):
    for length, open_, close, highs, lows, ao0, ao1, ac0, ac1, color in rows:
        expected = _reference(open_, close, highs, lows)
        for actual, ref in zip((ao0, ao1, ac0, ac1, color), expected):
            if math.isnan(ref):
                assert math.isnan(actual), (length, actual, ref)
            else:
                assert actual == pytest.approx(ref, rel=1e-11, abs=1e-11), (length, actual, ref)


@pytest.mark.parametrize("runonce", [False, True])
def test_clean_matches_independent_full_ao_ac_formula(runonce):
    rows = _run(_frame(), runonce)
    assert rows[0][0] == 40
    _check(rows)
    assert {row[-1] for row in rows} == {0., 1., 2., 3., 4., 5.}


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_missing_input_is_not_a_color_and_recovers(runonce, field):
    frame = _frame()
    frame.loc[frame.index[70], field] = math.nan
    rows = _run(frame, runonce)
    _check(rows)
    invalid = [row for row in rows if not all(math.isfinite(x) for x in
               (row[1], row[2], row[5], row[6], row[7], row[8]))]
    assert invalid and all(math.isnan(row[-1]) for row in invalid)
    assert math.isfinite(rows[-1][-1])


def test_replay_color_matches_observed_ao_ac():
    rows = _run(_frame(240), False, replay=True)
    assert len(rows) > len({row[0] for row in rows})
    for length, open_, close, _, _, ao0, ao1, ac0, ac1, color in rows:
        expected = _color(ao0, ao1, ac0, ac1, open_, close)
        assert color == expected, (length, color, expected)


@pytest.mark.parametrize("runonce", [False, True])
def test_missing_window_in_real_factor_context_does_not_error(runonce):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    frame = _frame()
    frame.index = frame.index.tz_localize("UTC")
    frame.loc[frame.index[70], "high"] = math.nan
    index = frame.index.rename("close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(minutes=1)}, index=index),
        start=index[0], end=index[-1], targets=("asset",), source_timezone="UTC",
        snapshot_id="cbw-strict-test", price_basis="synthetic",
        calendar_id="synthetic", frequency="1min", feed_time_kind="close_time",
        groups={"asset": "market"},
    )
    seen, values = [], []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("open", "high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = CandlesticksBW(self.data)
            seen.append(self)

        def next(self):
            value = float(self.child.color[0])
            values.append(value)
            self.outputs[self.datas[0]].factor[0] = value

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(align_to_grid(frame, research, "asset").feed, name="asset")
    bindings = {field: "feed:target:" + field for field in Factor.formula_fields}
    spec = FactorSpec(name="cbw", indicator=Factor, panel_line="factor",
                      field_bindings=bindings, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"cbw": spec})
    engine.run(preload=True)
    assert seen and not seen[0]._factor_strict_context.failed
    assert any(math.isnan(value) for value in values)
    assert math.isfinite(values[-1])
