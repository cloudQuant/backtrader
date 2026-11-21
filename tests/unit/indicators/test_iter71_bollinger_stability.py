import datetime as dt
import math
import statistics

import pandas as pd
import pytest

import backtrader as bt
from backtrader.errors import FactorComputationError
from backtrader.indicators.bollinger import _population_stddev
from backtrader.research import align_to_grid
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec, ResearchSpec
from backtrader.strategies.factor_strategy import FactorStrategy


class Feed(bt.feed.DataBase):
    params = (("samples", ()),)

    def __init__(self):
        super().__init__()
        self.index = 0

    def _load(self):
        if self.index == len(self.p.samples):
            return False
        timestamp, value = self.p.samples[self.index]
        self.index += 1
        self.datetime[0] = bt.date2num(timestamp)
        self.open[0] = self.high[0] = self.low[0] = self.close[0] = value
        self.volume[0], self.openinterest[0] = 1.0, 0.0
        return True


class Capture(bt.Strategy):
    params = (("movav", None), ("period", 3), ("factor", 2))

    def __init__(self):
        kw = {} if self.p.movav is None else {"movav": self.p.movav}
        self.bb = bt.ind.BollingerBands(
            self.datas[-1].close, period=self.p.period, devfactor=self.p.factor, **kw
        )
        self.rows = []

    def prenext(self):
        self.next()

    def next(self):
        d = self.datas[-1]
        if len(d):
            self.rows.append((len(d), d.close[0], self.bb.mid[0], self.bb.top[0], self.bb.bot[0]))


def calc(values, once=False, movav=None, factor=2):
    c = bt.Cerebro(stdstats=False)
    c.adddata(
        Feed(
            samples=[
                (dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i), v)
                for i, v in enumerate(values)
            ]
        )
    )
    c.addstrategy(Capture, movav=movav, factor=factor)
    return c.run(runonce=once)[0]


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("movav", [None, bt.ind.MovAv.Simple, bt.ind.MovAv.EMA, bt.ind.MovAv.WMA])
def test_offset_and_moving_average(once, movav):
    vals = [1e8 + i for i in range(12)]
    result = calc(vals, once, movav)
    for row in result.rows[2:]:
        assert row[3] - row[2] == pytest.approx(2 * math.sqrt(2 / 3), abs=1.1e-8)
        assert row[2] - row[4] == pytest.approx(2 * math.sqrt(2 / 3), abs=1.1e-8)


@pytest.mark.parametrize("once", [False, True])
def test_constant_and_nan_recovery(once):
    rows = calc([42] * 4 + [math.nan] + [42] * 4, once).rows
    assert rows[2][2:] == pytest.approx((42, 42, 42))
    assert all(math.isnan(v) for row in rows[4:7] for v in row[2:])
    assert rows[7][2:] == pytest.approx((42, 42, 42))


@pytest.mark.parametrize(
    "values",
    [
        [1e8, 1e8 + 1, 1e8 + 2],
        [1e154, 1e154 + 1e140, 1e154 + 2e140],
        [-1e308, 0, 1e308],
        [1e308, 1e308, 1e308],
        [1e-300, 2e-300, 3e-300],
        [5e-324, 5e-324, 1e-323],
    ],
)
def test_reference_extremes(values):
    expected = statistics.pstdev(values)
    assert _population_stddev(values, len(values)) == pytest.approx(expected, rel=5e-15, abs=5e-324)


@pytest.mark.parametrize("once", [False, True])
def test_extreme_finite_path_through_engine(once):
    result = calc([-1e308, 0.0, 1e308], once, factor=1)
    assert result.rows[-1][2] == 0.0
    assert result.rows[-1][3] == pytest.approx(math.sqrt(2 / 3) * 1e308, rel=3e-15)
    assert result.rows[-1][4] == pytest.approx(-math.sqrt(2 / 3) * 1e308, rel=3e-15)


def test_secondary_feed_replay():
    values = [1e8 + i for i in range(10)]
    c = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    c.adddata(
        Feed(
            samples=[
                (dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(hours=i), float(i))
                for i in range(len(values) * 30)
            ]
        )
    )
    samples = [
        (
            dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i, hours=j),
            v + j * 0.25,
        )
        for i, v in enumerate(values)
        for j in range(3)
    ]
    c.replaydata(
        Feed(samples=samples, timeframe=bt.TimeFrame.Minutes, compression=60),
        timeframe=bt.TimeFrame.Days,
    )
    c.addstrategy(Capture)
    s = c.run(preload=False, runonce=False)[0]
    assert len(s.rows) > 30
    for n, current, mid, top, bot in s.rows:
        if n >= 3:
            window = [values[n - 3] + 0.5, values[n - 2] + 0.5, current]
            sd = statistics.pstdev(window)
            assert top - mid == pytest.approx(2 * sd, abs=1.1e-8)
            assert mid - bot == pytest.approx(2 * sd, abs=1.1e-8)


def test_subnormal_rounding_regression():
    values = [5e-324, 5e-324, 1e-323]
    assert _population_stddev(values, 3) == statistics.pstdev(values) == 0.0


@pytest.mark.parametrize("ind_class", [bt.ind.BollingerBands, bt.ind.BollingerBandsPct])
def test_once_segment_preserves_surrounding_arrays_and_empty_noop(ind_class):
    vals = [100.0 + math.sin(i * 0.5) * 3 for i in range(16)]

    class S(bt.Strategy):
        def __init__(self):
            self.bb = ind_class(self.data, period=3)

    c = bt.Cerebro(stdstats=False)
    c.adddata(
        Feed(
            samples=[
                (dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i), v)
                for i, v in enumerate(vals)
            ]
        )
    )
    c.addstrategy(S)
    obj = c.run(runonce=True)[0].bb
    expected = [list(line.array) for line in obj.lines]
    for line in obj.lines:
        for i in range(len(line.array)):
            line.array[i] = -4321.0
    obj.once(5, 10)
    for line, want in zip(obj.lines, expected):
        assert all(x == -4321.0 for x in line.array[:5])
        assert list(line.array[5:10]) == pytest.approx(want[5:10], nan_ok=True)
        assert all(x == -4321.0 for x in line.array[10:])
    before = [list(line.array) for line in obj.lines]
    obj.p.devfactor = float("inf")
    obj.once(8, 8)
    assert [list(line.array) for line in obj.lines] == before


# Real strict-factor integration: source data and research grid are local to this
# test, so no external probe or test-helper module is required.


def _run_factor(values, indicator_cls, selected, devfactor, runonce, *, retained=None):
    index = pd.date_range("2024-01-01", periods=len(values), freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=index,
    )
    close_time = index.rename("close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": close_time - pd.Timedelta(hours=6)}, index=close_time),
        start=close_time[0],
        end=close_time[-1],
        targets=("asset-0",),
        source_timezone="UTC",
        snapshot_id="bb-stability-synthetic",
        price_basis="synthetic unadjusted",
        calendar_id="synthetic-daily",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"asset-0": "market"},
    )

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = indicator_cls(self.data, period=2, devfactor=devfactor)
            if retained is not None:
                retained.append(self.child)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = getattr(self.child, selected)[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(align_to_grid(frame, research, "asset-0").feed, name="asset-0")
    spec = FactorSpec(
        name="bb",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    engine.addstrategy(FactorStrategy, research=research, factors={"bb": spec})
    return engine.run(preload=True)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("selected", ["mid", "top"])
@pytest.mark.parametrize(
    "values,factor",
    [
        ([-9e307, 9e307] * 12 + [-9e307], 3),
        ([math.nan] * 25, math.inf),
    ],
)
def test_strict_bb_rejects_overflow_with_any_selected_output(runonce, selected, values, factor):
    with pytest.raises(FactorComputationError) as error:
        _run_factor(values, bt.ind.BollingerBands, selected, factor, runonce)
    assert isinstance(error.value.__cause__, ArithmeticError)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("selected", ["mid", "pctb"])
@pytest.mark.parametrize(
    "values,factor",
    [
        ([-9e307, 9e307] * 12 + [-9e307], 1),
        ([-1.6e308, 1.6e308] * 12 + [-1.6e308], 0.5),
    ],
)
def test_strict_pctb_rejects_intermediate_overflow(runonce, selected, values, factor):
    with pytest.raises(FactorComputationError) as error:
        _run_factor(values, bt.ind.BollingerBandsPct, selected, factor, runonce)
    assert isinstance(error.value.__cause__, ArithmeticError)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize(
    "indicator_cls,selected",
    [
        (bt.ind.BollingerBands, "mid"),
        (bt.ind.BollingerBands, "top"),
        (bt.ind.BollingerBandsPct, "mid"),
        (bt.ind.BollingerBandsPct, "pctb"),
    ],
)
@pytest.mark.parametrize("kind", ["nan", "flat"])
def test_strict_nan_and_flat_remain_valid(runonce, indicator_cls, selected, kind):
    values = [100.0] * 25 if kind == "flat" else [100.0 + i * 0.2 for i in range(25)]
    if kind == "nan":
        values[12] = math.nan
    _run_factor(values, indicator_cls, selected, 1, runonce)


@pytest.mark.parametrize(
    "indicator_cls,selected",
    [
        (bt.ind.BollingerBands, "mid"),
        (bt.ind.BollingerBandsPct, "pctb"),
    ],
)
def test_strict_empty_interval_neither_revalidates_nor_rewrites(indicator_cls, selected):
    retained = []
    _run_factor([100.0 + i for i in range(25)], indicator_cls, selected, 1, True, retained=retained)
    child = retained[0]
    before = [list(line.array) for line in child.lines]
    child.p.devfactor = math.inf
    child.once(10, 10)
    for line, previous in zip(child.lines, before):
        assert list(line.array) == pytest.approx(previous, nan_ok=True)
