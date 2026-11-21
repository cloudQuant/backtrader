import pytest
import math
import backtrader as bt
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec
from backtrader.strategies.factor_strategy import FactorStrategy
from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec


@pytest.mark.parametrize("once", [False, True])
def test_sum_callback_strict_graph(monkeypatch, once):
    data = _frames(periods=60)["asset-0"].copy()
    research = _research_spec({"asset-0": data})
    calls = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.s = bt.ind.SumN(self.data.close, period=32)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.s[0]

    def custom(window):
        vals = list(window)
        if len(vals) != 32:
            return sum(vals)
        calls.append(vals)
        assert len(vals) == 32
        return 321.0

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(_research_feed(data, research, "asset-0"), name="asset-0")
    spec = FactorSpec(
        name="factor",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"factor": spec})
    monkeypatch.setattr(math, "fsum", custom)
    monkeypatch.setattr(bt.ind.SumN, "func", staticmethod(custom))
    s = c.run(preload=True)[0]
    panel = s.get_panel().factors["factor"].to_numpy(dtype="float64").ravel()
    assert len(calls) == 29
    assert all(float(x) == 321.0 for x in panel[31:])
