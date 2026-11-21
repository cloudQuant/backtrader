import backtrader as bt
import pandas as pd
import pytest

@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize(
    "field,bar,should_fail", [("high", 12, True), ("low", 12, True), ("high", 2, False)]
)
def test_strict_factor_preserves_legacy_input_window(field, bar, should_fail, runonce):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    n = 30
    index = pd.date_range("2024-01-01", periods=n, freq="min", tz="UTC", name="close_time")
    frame = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
            "openinterest": [0.0] * n,
        },
        index=index,
    )
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(minutes=1)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="test",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1min",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.ind.StochasticHistogramIndicator(
                self.data, k_period=3, slowing=1, d_period=1
            )

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.main[0]

    feed = align_to_grid(frame, research, "asset").feed
    original = feed._load

    def injected_load():
        ok = original()
        if ok and len(feed) == bar:
            line = getattr(feed.lines, field)
            line.array[line.idx] = float("inf")
        return ok

    feed._load = injected_load
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=runonce)
    cerebro.adddata(feed, name="asset")
    spec = FactorSpec(
        name="test",
        indicator=Factor,
        panel_line="factor",
        field_bindings={k: "feed:target:" + k for k in Factor.formula_fields},
        mode="native",
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"test": spec})
    if should_fail:
        with pytest.raises(FactorComputationError) as caught:
            cerebro.run()
        assert isinstance(caught.value.__cause__, ArithmeticError)
    else:
        cerebro.run()
