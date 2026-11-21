"""Compare +DI proxy to directional movements with complete OHLC windows."""

import math
import backtrader as bt
import pandas as pd
import pytest
from backtrader.indicators.contrib.laguerre_plus_di_proxy import LaguerrePlusDiProxy

P = 3


def make_frame(count=60, *, missing=None, freq="D"):
    high = [103 + 0.4 * i + math.sin(i * 0.35) for i in range(count)]
    low = [99 + 0.2 * i + math.sin(i * 0.45) for i in range(count)]
    data = pd.DataFrame(
        {
            "open": [(h + l) / 2 for h, l in zip(high, low)],
            "high": high,
            "low": low,
            "close": [(h + l) / 2 for h, l in zip(high, low)],
            "volume": [1.0] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq=freq),
    )
    if missing is not None:
        field, index = missing
        data.iloc[index, data.columns.get_loc(field)] = math.nan
    return data


def reference(data, period=P):
    out = [math.nan] * len(data)
    for i in range(period + 2, len(data)):
        gains = losses = trsum = 0.0
        valid = True
        for j in range(i - period + 1, i + 1):
            h, hprev = data.high.iloc[j], data.high.iloc[j - 1]
            l, lprev = data.low.iloc[j], data.low.iloc[j - 1]
            prevclose = data.close.iloc[j - 1]
            if not all(math.isfinite(x) for x in (h, hprev, l, lprev, prevclose)):
                valid = False
                break
            up = h - hprev
            down = lprev - l
            gains += up if up > down and up > 0 else 0.0
            losses += down if down > up and down > 0 else 0.0
            trsum += max(h - l, abs(h - prevclose), abs(l - prevclose))
        if valid:
            if trsum <= 1e-12:
                out[i] = 0.5
            else:
                positive = 100 * gains / trsum
                negative = 100 * losses / trsum
                out[i] = (
                    0.5 if positive + negative <= 1e-12 else gains / (gains + losses)
                )
    return out


def equal(actual, expected):
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual, expected)):
        if math.isnan(e):
            assert math.isnan(a), (i, a, e)
        else:
            assert a == pytest.approx(e, rel=1e-11, abs=1e-11), (i, a, e)


def run(data, once, primary=None):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = LaguerrePlusDiProxy(self.datas[-1], period=P)

    c = bt.Cerebro(stdstats=False, runonce=once, preload=True)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Probe)
    return c.run()[0].ind


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize(
    "missing",
    [None, ("high", 18), ("low", 18), ("close", 18)],
    ids=["finite", "high", "low", "close"],
)
def test_complete_window(once, missing):
    data = make_frame(missing=missing)
    ind = run(data, once)
    assert ind._minperiod == P + 3
    equal(list(ind.value.array), reference(data))
    if missing:
        assert math.isnan(ind.value.array[19])
        assert math.isfinite(ind.value.array[23])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_second_feed(once):
    data = make_frame(40, missing=("high", 18), freq="3D")
    ind = run(data, once, make_frame(120))
    equal(list(ind.value.array), reference(data))


def test_replay_per_revision():
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = LaguerrePlusDiProxy(self.data, period=P)
            self.rows = []

        def next(self):
            n = len(self.data)
            d = {
                field: list(getattr(self.data, field).get(size=n))
                for field in ("open", "high", "low", "close", "volume")
            }
            self.rows.append((n, pd.DataFrame(d), float(self.ind.value[0])))

    c = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    c.replaydata(
        bt.feeds.PandasData(
            dataname=make_frame(100, missing=("close", 40), freq="min")
        ),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    c.addstrategy(Probe)
    rows = c.run()[0].rows
    assert rows and any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    expect = [reference(data)[-1] for _, data, _ in rows]
    assert any(math.isnan(x) for x in expect)
    equal([v for _, _, v in rows], expect)


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_nan_does_not_turn_into_sell_vote(once):
    data = make_frame(missing=("high", 18))
    ind = run(data, once)
    value = ind.value.array[18]
    # The public NeuroNirvaman strategy maps >0.5 to -1 and <0.5 to +1.
    vote = -1 if value > 0.5 else 1 if value < 0.5 else 0
    assert math.isnan(value)
    assert vote == 0


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("strict", [False, True], ids=["ordinary", "strict"])
def test_finite_input_subtraction_overflow_does_not_signal(once, strict):
    from backtrader.errors import FactorComputationContext, FactorComputationError

    data = make_frame(20)
    data.loc[:, "high"] = 1e308
    data.loc[:, "low"] = -1e308
    data.loc[:, "close"] = 0.0

    class Probe(bt.Strategy):
        def __init__(self):
            if strict:
                self._factor_strict_context = FactorComputationContext(
                    "plusdi", phase="next"
                )
            self.ind = LaguerrePlusDiProxy(self.data, period=P)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Probe)
    if strict:
        with pytest.raises(FactorComputationError):
            c.run()
    else:
        values = list(c.run()[0].ind.value.array)
        assert all(math.isnan(v) for v in values[P + 2 :])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_flat_window_retains_neutral_value(once):
    data = make_frame(20)
    for field in ("open", "high", "low", "close"):
        data.loc[:, field] = 100.0
    values = list(run(data, once).value.array)
    assert values[P + 2 :] == [0.5] * (len(data) - P - 2)


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_incomplete_window_does_not_create_sell_order(once):
    class SignalStrategy(bt.Strategy):
        def __init__(self):
            self.ind = LaguerrePlusDiProxy(self.data, period=P)
            self.order_count = 0

        def next(self):
            if len(self.data) == 19 and self.ind.value[0] > 0.5:
                self.sell()
                self.order_count += 1

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=make_frame(missing=("high", 18))))
    c.addstrategy(SignalStrategy)
    assert c.run()[0].order_count == 0


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_factor_graph_rejects_finite_input_overflow(once):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    data = make_frame(20)
    data.index = data.index.tz_localize("UTC")
    data.loc[:, "high"] = 1e308
    data.loc[:, "low"] = -1e308
    data.loc[:, "close"] = 0.0
    index = data.index.rename("close_time")
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)
    research = ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=("asset-0",),
        source_timezone="UTC",
        snapshot_id="plusdi-oracle",
        price_basis="synthetic",
        calendar_id="daily",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"asset-0": "market"},
    )

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = LaguerrePlusDiProxy(self.data, period=P)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.value[0]

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(data, research, "asset-0").feed, name="asset-0")
    spec = FactorSpec(
        name="plusdi",
        indicator=Factor,
        panel_line="factor",
        field_bindings={f: f"feed:target:{f}" for f in Factor.required_fields},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"plusdi": spec})
    with pytest.raises(FactorComputationError):
        c.run(preload=True)
