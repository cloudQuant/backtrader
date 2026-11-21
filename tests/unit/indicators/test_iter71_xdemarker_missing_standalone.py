import math
import pandas as pd
import pytest
import backtrader as bt


def rows():
    out = []
    for i in range(90):
        c = 100 + i * 0.37 + (i * 7 % 9) * 0.83
        out.append(
            {
                "open": c - (i % 3) * 0.11,
                "high": c + 1 + (i % 3) * 0.2,
                "low": c - 0.8 - (i % 4) * 0.1,
                "close": c,
                "volume": 10 + i % 7,
                "openinterest": 20 + i % 5,
            }
        )
    return out


def ref(rs):
    result = [math.nan] * len(rs)
    for t in range(7, len(rs)):
        raw = []
        for q in (t - 1, t):
            pairs = [
                (rs[k]["high"], rs[k - 1]["high"], rs[k]["low"], rs[k - 1]["low"])
                for k in range(q - 2, q + 1)
            ]
            if any(not math.isfinite(x) for pair in pairs for x in pair):
                raw.append(math.nan)
                continue
            up = sum(max(h - hp, 0.0) for h, hp, low, lp in pairs)
            dn = sum(max(lp - low, 0.0) for h, hp, low, lp in pairs)
            d = up / (up + dn) if up + dn > 0 else 0.5
            raw.append((d * 100.0 - 50.0) * rs[q]["volume"])
        if all(math.isfinite(x) for x in raw):
            result[t] = sum(raw) / 2
    return result


def run(rs, once):
    frame = pd.DataFrame(rs, index=pd.date_range("2025-01-01", periods=len(rs), freq="D"))

    class S(bt.Strategy):
        def __init__(self):
            self.x = bt.ind.XDeMarkerHistogramVolDirectIndicator(
                self.data, de_marker_period=3, ma_length=2
            )

    e = bt.Cerebro(stdstats=False, runonce=once)
    e.adddata(bt.feeds.PandasData(dataname=frame))
    e.addstrategy(S)
    s = e.run()[0]
    return {k: list(getattr(s.x.lines, k).array) for k in ("value", "color_zone", "color_direct")}


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("field", ["high", "low"])
@pytest.mark.parametrize("missing", [False, True])
def test_formula_and_missing(once, field, missing):
    rs = rows()
    if missing:
        rs[50][field] = math.nan
    expected = ref(rs)
    got = run(rs, once)
    for i in range(7, len(rs)):
        if math.isnan(expected[i]):
            assert all(math.isnan(got[k][i]) for k in got), (i, {k: got[k][i] for k in got})
        else:
            assert got["value"][i] == pytest.approx(expected[i], rel=1e-12, abs=1e-12)
            assert math.isfinite(got["color_zone"][i]) and math.isfinite(got["color_direct"][i])
    if missing:
        assert all(math.isnan(got["value"][i]) for i in range(50, 55))
        assert math.isfinite(got["value"][55])


@pytest.mark.parametrize("once", [False, True])
def test_strict_missing_propagates_and_recovers(once):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import (
        _frames,
        _research_feed,
        _research_spec,
    )

    data = _frames(periods=40)["asset-0"].copy()
    data.loc[data.index[12], "high"] = math.nan
    research = _research_spec({"asset-0": data})
    found = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.ind.XDeMarkerHistogramVolDirectIndicator(
                self.data, de_marker_period=3, ma_length=2
            )
            found.append(self.child)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.value[0]

    e = bt.Cerebro(stdstats=False, runonce=once)
    e.adddata(_research_feed(data, research, "asset-0"), name="asset-0")
    spec = FactorSpec(
        name="f",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    e.addstrategy(FactorStrategy, research=research, factors={"f": spec})
    e.run(preload=True)
    assert all(math.isnan(found[0].value.array[i]) for i in range(12, 17))
    assert math.isfinite(found[0].value.array[17])
