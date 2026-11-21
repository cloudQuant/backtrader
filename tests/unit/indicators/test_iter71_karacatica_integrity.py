"""Independent direction/ATR reference for Karacatica, including missing bars."""

import importlib.util
import math
from pathlib import Path
import sys
import backtrader as bt
import pandas as pd
import pytest
from backtrader.indicators.contrib.karacatica_indicator import KaracaticaIndicator

PERIOD = 5
ROOT = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "backtrader").is_dir() and (p / "tests" / "functional").is_dir()
)
STRATEGY = (
    ROOT / "tests/functional/strategies/volatility_systems/test_0029_0916_karacatica.py"
)


def data_frame(n=130, *, missing=None, freq="h"):
    close = [
        100 + math.sin(i * 0.43) * 4 + i * 0.03 + math.sin(i * 0.13) for i in range(n)
    ]
    high = [x + 1 + 0.2 * math.sin(i * 0.2) for i, x in enumerate(close)]
    low = [x - 1 - 0.1 * math.cos(i * 0.3) for i, x in enumerate(close)]
    data = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": [10.0] * n},
        index=pd.date_range("2024-01-01", periods=n, freq=freq),
    )
    if missing:
        field, index = missing
        data.iloc[index, data.columns.get_loc(field)] = math.nan
    return data


def reference(data):
    n = len(data)
    buy = [math.nan] * n
    sell = [math.nan] * n
    direction = 0
    for i in range(PERIOD + 1, n):
        rows = []
        valid = math.isfinite(float(data.close.iloc[i]))
        for j in range(i - PERIOD + 1, i + 1):
            row = (
                float(data.high.iloc[j]),
                float(data.low.iloc[j]),
                float(data.high.iloc[j - 1]),
                float(data.low.iloc[j - 1]),
                float(data.close.iloc[j - 1]),
            )
            rows.append(row)
            valid &= all(math.isfinite(x) for x in row)
        if not valid:
            continue
        p = []
        m = []
        tr = []
        for hi, lo, prev_hi, prev_lo, prev_close in rows:
            up = hi - prev_hi
            down = prev_lo - lo
            p.append(up if up > down and up > 0 else 0.0)
            m.append(down if down > up and down > 0 else 0.0)
            tr.append(max(hi - lo, abs(hi - prev_close), abs(prev_close - lo)))
        tr_total = sum(tr)
        atr = tr_total / PERIOD
        plus = 100 * sum(p) / tr_total if tr_total else 0.0
        minus = 100 * sum(m) / tr_total if tr_total else 0.0
        buy[i] = sell[i] = 0.0
        if (
            data.close.iloc[i] > data.close.iloc[i - PERIOD]
            and plus > minus
            and direction != 1
        ):
            buy[i] = data.low.iloc[i] - atr * 0.75
            direction = 1
        if (
            data.close.iloc[i] < data.close.iloc[i - PERIOD]
            and plus < minus
            and direction != 2
        ):
            sell[i] = data.high.iloc[i] + atr * 0.75
            direction = 2
    return buy, sell


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
            self.ind = KaracaticaIndicator(self.datas[-1], iperiod=PERIOD)

    c = bt.Cerebro(stdstats=False, runonce=once)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Probe)
    return c.run()[0].ind


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize(
    "missing",
    [None, ("high", 40), ("low", 40), ("close", 40)],
    ids=["finite", "high", "low", "close"],
)
def test_complete_window_and_direction_recovery(once, missing):
    data = data_frame(missing=missing)
    ind = run(data, once)
    assert ind._minperiod == PERIOD + 2
    expected = reference(data)
    equal(list(ind.buy_arrow.array), expected[0])
    equal(list(ind.sell_arrow.array), expected[1])
    if missing:
        assert math.isnan(ind.buy_arrow.array[43]) and math.isnan(
            ind.sell_arrow.array[43]
        )
        assert any(
            math.isfinite(x) and x != 0
            for x in list(ind.buy_arrow.array)[50:] + list(ind.sell_arrow.array)[50:]
        )


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_secondary_feed(once):
    data = data_frame(80, missing=("close", 40), freq="3h")
    ind = run(data, once, data_frame(240))
    expected = reference(data)
    equal(list(ind.buy_arrow.array), expected[0])
    equal(list(ind.sell_arrow.array), expected[1])


def load_strategy():
    spec = importlib.util.spec_from_file_location("public_karacatica_test", STRATEGY)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m.ExpKaracaticaStrategy


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_real_strategy_does_not_buy_on_missing_previous_close(once):
    class Observed(load_strategy()):
        def __init__(self):
            super().__init__()
            self.orders = []

        def next(self):
            if len(self.signal_data) < 41:
                return
            super().next()

        def buy(self, *a, **kw):
            self.orders.append((len(self.signal_data) - 1, "buy"))
            return super().buy(*a, **kw)

        def sell(self, *a, **kw):
            self.orders.append((len(self.signal_data) - 1, "sell"))
            return super().sell(*a, **kw)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=data_frame()))
    c.adddata(bt.feeds.PandasData(dataname=data_frame(missing=("close", 40))))
    c.addstrategy(Observed, iperiod=PERIOD)
    strategy = c.run()[0]
    assert not [(i, side) for i, side in strategy.orders if 40 <= i <= 45]
    assert any(i > 45 for i, _ in strategy.orders)


def test_replay_each_revision_matches_visible_bar_history():
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = KaracaticaIndicator(self.data, iperiod=PERIOD)
            self.rows = []

        def next(self):
            n = len(self.data)
            d = {
                f: list(getattr(self.data, f).get(size=n))
                for f in ("open", "high", "low", "close", "volume")
            }
            self.rows.append(
                (
                    n,
                    pd.DataFrame(d),
                    float(self.ind.buy_arrow[0]),
                    float(self.ind.sell_arrow[0]),
                )
            )

    c = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    c.replaydata(
        bt.feeds.PandasData(
            dataname=data_frame(180, missing=("close", 80), freq="min")
        ),
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    c.addstrategy(Probe)
    rows = c.run()[0].rows
    assert rows and any(x[0] == y[0] for x, y in zip(rows, rows[1:]))
    saw_missing = False
    for n, data, buy, sell in rows:
        expected = reference(data)
        saw_missing |= math.isnan(expected[0][-1])
        equal([buy], [expected[0][-1]])
        equal([sell], [expected[1][-1]])
    assert saw_missing


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize(
    "length", [1, 6, 7, 8, 12], ids=["one", "before", "first", "next", "later"]
)
def test_short_history(once, length):
    data = data_frame(length)
    ind = run(data, once)
    expected = reference(data)
    equal(list(ind.buy_arrow.array), expected[0])
    equal(list(ind.sell_arrow.array), expected[1])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_flat_window_remains_no_signal(once):
    data = data_frame(40)
    for field in ("open", "high", "low", "close"):
        data.loc[:, field] = 100.0
    ind = run(data, once)
    expected = reference(data)
    equal(list(ind.buy_arrow.array), expected[0])
    equal(list(ind.sell_arrow.array), expected[1])
    assert list(ind.buy_arrow.array)[PERIOD + 1 :] == [0.0] * (len(data) - PERIOD - 1)


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
def test_strict_missing_is_not_a_signal_and_recovers(once):
    from backtrader.errors import FactorComputationContext

    data = data_frame(missing=("close", 40))

    class Probe(bt.Strategy):
        def __init__(self):
            self._factor_strict_context = FactorComputationContext(
                "karacatica", phase="next"
            )
            self.ind = KaracaticaIndicator(self.data, iperiod=PERIOD)

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Probe)
    ind = c.run()[0].ind
    expected = reference(data)
    equal(list(ind.buy_arrow.array), expected[0])
    equal(list(ind.sell_arrow.array), expected[1])


@pytest.mark.parametrize("once", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("output", ["buy_arrow", "sell_arrow"])
def test_real_factor_graph_rejects_finite_intermediate_overflow(once, output):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    data = data_frame(30)
    data.index = data.index.tz_localize("UTC")
    data.loc[:, "high"] = 1e308
    data.loc[:, "low"] = -1e308
    data.loc[:, "close"] = 0.0
    index = data.index.rename("close_time")
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=1)}, index=index)
    research = ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=("asset-0",),
        source_timezone="UTC",
        snapshot_id="karacatica-oracle",
        price_basis="synthetic",
        calendar_id="hourly",
        frequency="1h",
        feed_time_kind="close_time",
        groups={"asset-0": "market"},
    )

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = KaracaticaIndicator(self.data, iperiod=PERIOD)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = getattr(self.child.lines, output)[0]

    c = bt.Cerebro(stdstats=False, runonce=once)
    c.adddata(align_to_grid(data, research, "asset-0").feed, name="asset-0")
    spec = FactorSpec(
        name="karacatica",
        indicator=Factor,
        panel_line="factor",
        field_bindings={f: f"feed:target:{f}" for f in Factor.required_fields},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"karacatica": spec})
    with pytest.raises(FactorComputationError) as caught:
        c.run(preload=True)
    assert isinstance(caught.value.__cause__, ArithmeticError)
