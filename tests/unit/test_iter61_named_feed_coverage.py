"""Field windows must follow the declared target and named-feed bindings."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import FactorIndicator, FactorSpec, ResearchSpec, align_to_grid
from backtrader.strategies.factor_strategy import FactorStrategy


class _Identity(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("source",)
    lookback_h = 2

    def next(self):
        for data, line in zip(self.target_datas, self.field_lines("source")):
            self.outputs[data].factor[0] = float(line[0])

    @classmethod
    def build(cls, ctx):
        return ctx.source * 1.0


class _Sum(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("left", "right")
    lookback_h = 2

    def next(self):
        for data, left, right in zip(
            self.target_datas, self.field_lines("left"), self.field_lines("right")
        ):
            self.outputs[data].factor[0] = float(left[0]) + float(right[0])

    @classmethod
    def build(cls, ctx):
        return ctx.left + ctx.right


class _DollarVolume(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("dollar_volume", "vwap", "volume")
    lookback_h = 2

    def next(self):
        for data, line in zip(self.target_datas, self.field_lines("dollar_volume")):
            self.outputs[data].factor[0] = float(line[0])

    @classmethod
    def build(cls, ctx):
        return ctx.dollar_volume * 1.0


class _AverageDollarVolume(_DollarVolume):
    formula_fields = ("adv2", "dollar_volume", "vwap", "volume")

    def next(self):
        for data, line in zip(self.target_datas, self.field_lines("adv2")):
            self.outputs[data].factor[0] = float(line[0])

    @classmethod
    def build(cls, ctx):
        return ctx.adv2 * 1.0


class _IdentityZero(_Identity):
    lookback_h = 0


class _ComputedCloseFeed(bt.feeds.PandasData):
    """A valid custom feed whose close is computed from another input line."""

    def _load(self):
        loaded = super()._load()
        if loaded:
            self.lines.close[0] = self.lines.open[0] * 2.0
        return loaded


def _frame(times, close):
    return pd.DataFrame(
        {
            "open": [50.0 + i for i in range(len(times))],
            "high": [80.0 + i for i in range(len(times))],
            "low": [20.0 + i for i in range(len(times))],
            "close": close,
            "volume": [1000.0 + i for i in range(len(times))],
        },
        index=times,
    )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize(
    "binding", ("target", "benchmark", "benchmark_zero", "both", "named_target", "derived", "adv")
)
def test_field_windows_follow_the_bound_feed(binding, mode, runonce):
    times = pd.date_range("2023-01-02 16:00", periods=18, freq="B", tz="UTC", name="close_time")
    target_close = [100.0 + i * i for i in range(len(times))]
    other_close = [40.0 + 3 * i for i in range(len(times))]
    bench_close = [10.0 + i * 0.25 for i in range(len(times))]
    target_close[5] = math.nan  # Existing target bar, with a missing close only.
    other_close[7] = math.nan
    bench_close[11] = math.nan
    frames = {
        "AAA": _frame(times, target_close),
        "BBB": _frame(times, other_close),
        "BENCH": _frame(times, bench_close).drop(index=times[9]),
    }
    frames["AAA"].loc[times[4], "volume"] = math.nan
    frames["BBB"].loc[times[6], "volume"] = math.nan
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=("AAA", "BBB"),
        source_timezone="UTC",
        snapshot_id="iter61-named-feed-coverage",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"AAA": "g1", "BBB": "g2"},
    )
    if binding == "both":
        indicator = _Sum
        bindings = {"left": "feed:target:close", "right": "feed:BENCH:close"}
    elif binding in ("derived", "adv"):
        indicator = _DollarVolume if binding == "derived" else _AverageDollarVolume
        bindings = {
            "dollar_volume": {"derive": "vwap_volume", "vwap": "vwap", "volume": "volume"},
            "vwap": {"kind": "direct", "source": "feed:BENCH:close"},
            "volume": "feed:target:volume",
        }
        if binding == "adv":
            bindings["adv2"] = {"derive": "adv", "source": "dollar_volume", "window": 2}
    else:
        indicator = _Identity
        source = {
            "target": "target",
            "benchmark": "BENCH",
            "benchmark_zero": "BENCH",
            "named_target": "BBB",
        }[binding]
        bindings = {"source": "feed:%s:close" % source}
    if binding == "benchmark_zero":
        indicator = _IdentityZero
    spec = FactorSpec(
        name="result", indicator=indicator, mode=mode, panel_line="factor", field_bindings=bindings
    )
    cerebro = bt.Cerebro(stdstats=False)
    for name, frame in frames.items():
        cerebro.adddata(align_to_grid(frame, research, name).feed, name=name)
    cerebro.addstrategy(FactorStrategy, research=research, factors={"result": spec})
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    result = strategy.get_panel().factors
    benchmark = frames["BENCH"].reindex(times)["close"].tolist()
    for asset in research.targets:
        target = frames[asset]["close"].tolist()
        observed = result.xs(asset, level="asset")["result"].tolist()
        expected_finite = []
        lookback = spec.lookback_h
        for i in range(2, len(times)):
            if binding == "target":
                inputs = [target]
            elif binding == "named_target":
                inputs = [other_close]
            elif binding in ("derived", "adv"):
                inputs = [benchmark, frames[asset]["volume"].tolist()]
            elif binding == "both":
                inputs = [target, benchmark]
            else:
                inputs = [benchmark]
            valid = all(
                math.isfinite(float(v)) for values in inputs for v in values[i - lookback : i + 1]
            )
            if valid and binding == "derived":
                wanted = inputs[0][i] * inputs[1][i]
            elif valid and binding == "adv":
                wanted = sum(inputs[0][j] * inputs[1][j] for j in (i - 1, i)) / 2.0
            else:
                wanted = sum(values[i] for values in inputs) if valid else math.nan
            got = observed[i]
            assert math.isfinite(got) == math.isfinite(wanted), (binding, mode, runonce, asset, i)
            if valid:
                assert got == pytest.approx(wanted), (binding, mode, runonce, asset, i)
                expected_finite.append(i)
        assert expected_finite
        # An unrelated target-close NaN must not suppress a BENCH-only factor.
        if binding in ("benchmark", "benchmark_zero"):
            assert math.isfinite(observed[5 if asset == "AAA" else 7])
            assert math.isnan(observed[9])  # The shared BENCH is missing this bar.
            if binding == "benchmark":
                assert math.isnan(observed[10])  # Its lookback window remains incomplete.


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize(
    "source",
    (
        "uppercase",
        "mapped",
        "mapped_index",
        "computed",
        "datetime_column",
        "datetime_column_naive",
        "other_open_time",
        "missing_metadata_field",
        "legacy_unaligned",
    ),
)
def test_named_source_alignment_metadata_and_legacy_fallback(source, mode, runonce):
    times = pd.date_range("2024-01-01 16:00", periods=12, freq="B", tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=("AAA",),
        source_timezone="UTC",
        snapshot_id="iter61-named-feed-alignment",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"AAA": "g"},
    )
    target = _frame(times, [100 + i for i in range(len(times))])
    values = [20.0 + i for i in range(len(times))]
    if source in (
        "uppercase",
        "mapped",
        "mapped_index",
        "other_open_time",
        "missing_metadata_field",
        "legacy_unaligned",
    ):
        values[5] = math.nan
    benchmark = _frame(times, values)
    if source == "uppercase":
        benchmark = benchmark.rename(columns={"close": "Close"})
    elif source in ("mapped", "mapped_index"):
        benchmark["altclose"] = benchmark["close"]
        benchmark["close"] = 999.0
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(align_to_grid(target, research, "AAA").feed, name="AAA")
    if source == "legacy_unaligned":
        bench_feed = bt.feeds.PandasData(dataname=benchmark)
    else:
        bench_research = research
        if source == "other_open_time":
            bench_research = ResearchSpec(
                grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=7)}, index=times),
                start=times[0],
                end=times[-1],
                targets=("AAA",),
                source_timezone="UTC",
                snapshot_id="other-open",
                price_basis="synthetic",
                calendar_id="synthetic",
                frequency="1session",
                feed_time_kind="close_time",
                groups={"AAA": "g"},
            )
        bench_feed = align_to_grid(benchmark, bench_research, "BENCH").feed
        if source == "missing_metadata_field":
            del bench_feed._factor_research_alignment_v2["field_present"]["close"]
        elif source in (
            "mapped",
            "mapped_index",
            "computed",
            "datetime_column",
            "datetime_column_naive",
        ):
            aligned = bench_feed
            cls = _ComputedCloseFeed if source == "computed" else bt.feeds.PandasData
            close_mapping = (
                "altclose"
                if source == "mapped"
                else (benchmark.columns.get_loc("altclose") if source == "mapped_index" else -1)
            )
            frame = aligned.p.dataname
            params = {}
            if source in ("datetime_column", "datetime_column_naive"):
                frame = frame.copy()
                frame["bar_close_time"] = (
                    times if source == "datetime_column" else times.tz_localize(None)
                )
                params["datetime"] = "bar_close_time"
            bench_feed = cls(dataname=frame, close=close_mapping, **params)
            bench_feed._factor_research_alignment_v2 = aligned._factor_research_alignment_v2
            if source == "computed":
                del bench_feed._factor_research_alignment_v2["field_present"]["close"]
    cerebro.adddata(bench_feed, name="BENCH")
    spec = FactorSpec(
        name="result",
        indicator=_Identity,
        mode=mode,
        panel_line="factor",
        field_bindings={"source": "feed:BENCH:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"result": spec})
    actual = cerebro.run(runonce=runonce, preload=True)[0].get_panel().factors["result"].tolist()
    if source == "missing_metadata_field":
        # Preserve the pre-existing fallback when a field has no mask; its
        # historical window cannot be proven from alignment metadata.
        assert math.isnan(actual[5])
        assert actual[6] == pytest.approx(values[6])
    elif source in ("uppercase", "mapped", "mapped_index", "other_open_time"):
        assert math.isfinite(actual[4])
        assert all(math.isnan(actual[i]) for i in (5, 6, 7))
        assert actual[8] == pytest.approx(values[8])
    elif source == "computed":
        assert all(math.isfinite(value) for value in actual)
        assert actual[6] == pytest.approx(2.0 * (50.0 + 6.0))
    elif source in ("datetime_column", "datetime_column_naive"):
        assert all(math.isfinite(value) for value in actual)
        assert actual[6] == pytest.approx(values[6])
    else:
        # Backtrader also accepts feeds without alignment metadata.  Preserve
        # their pre-existing behavior; they cannot prove a historical window.
        assert math.isfinite(actual[4])
        assert math.isnan(actual[5])
        assert actual[6] == pytest.approx(values[6])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize(
    "source", ("shifted_close", "short_grid", "short_field_mask", "short_presence_mask")
)
def test_named_source_requires_compatible_close_grid(source, mode, runonce):
    from backtrader.errors import DatasetError

    times = pd.date_range("2024-02-01 16:00", periods=12, freq="B", tz="UTC", name="close_time")

    def make_research(grid_times):
        return ResearchSpec(
            grid=pd.DataFrame({"open_time": grid_times - pd.Timedelta(hours=6)}, index=grid_times),
            start=grid_times[0],
            end=grid_times[-1],
            targets=("AAA",),
            source_timezone="UTC",
            snapshot_id="iter61-named-feed-close-grid",
            price_basis="synthetic",
            calendar_id="synthetic",
            frequency="1session",
            feed_time_kind="close_time",
            groups={"AAA": "g"},
        )

    research = make_research(times)
    target = _frame(times, [100.0 + i for i in range(len(times))])
    bench_times = times
    if source == "shifted_close":
        bench_times = times + pd.Timedelta(days=1)
    elif source == "short_grid":
        bench_times = times[:-1]
    benchmark = _frame(bench_times, [20.0 + i for i in range(len(bench_times))])
    bench_feed = align_to_grid(benchmark, make_research(bench_times), "BENCH").feed
    if source == "short_field_mask":
        fields = bench_feed._factor_research_alignment_v2["field_present"]
        fields["close"] = fields["close"][:-1]
    elif source == "short_presence_mask":
        metadata = bench_feed._factor_research_alignment_v2
        metadata["present"] = metadata["present"][:-1]
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(align_to_grid(target, research, "AAA").feed, name="AAA")
    cerebro.adddata(bench_feed, name="BENCH")
    spec = FactorSpec(
        name="result",
        indicator=_Identity,
        mode=mode,
        panel_line="factor",
        field_bindings={"source": "feed:BENCH:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"result": spec})
    with pytest.raises(DatasetError, match="factor source.*(close|length)"):
        cerebro.run(runonce=runonce, preload=True)


class _FeedClock(bt.Strategy):
    def __init__(self):
        self.seen = []

    def next(self):
        from datetime import timezone

        self.seen.append(bt.num2date(float(self.data.datetime[0]), tz=timezone.utc, naive=False))


def _clock_cases(times):
    local_naive = times.tz_convert("Asia/Shanghai").tz_localize(None)
    return {
        "utc_naive_no_tzinput": (times.tz_localize(None), None, 0),
        "local_naive_no_tzinput": (local_naive, None, 8),
        "local_naive_shanghai": (local_naive, "Asia/Shanghai", 0),
        "utc_naive_shanghai": (times.tz_localize(None), "Asia/Shanghai", -8),
        "aware_local_no_tzinput": (times.tz_convert("Asia/Shanghai"), None, 0),
        "aware_local_shanghai": (times.tz_convert("Asia/Shanghai"), "Asia/Shanghai", -8),
        "aware_later_shanghai": (times + pd.Timedelta(hours=8), "Asia/Shanghai", 0),
        "utc_naive_utc": (times.tz_localize(None), "UTC", 0),
    }


@pytest.mark.parametrize("preload", (False, True), ids=("streaming", "preloaded"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize(
    "case",
    (
        "utc_naive_no_tzinput",
        "local_naive_no_tzinput",
        "local_naive_shanghai",
        "utc_naive_shanghai",
        "aware_local_no_tzinput",
        "aware_local_shanghai",
        "aware_later_shanghai",
        "utc_naive_utc",
    ),
)
def test_named_feed_uses_its_actual_clock_not_research_source_timezone(
    case, mode, runonce, preload
):
    from backtrader.errors import DatasetError

    times = pd.date_range("2024-01-08 08:00", periods=8, freq="B", tz="UTC", name="close_time")
    source_times, tzinput, delta_hours = _clock_cases(times)[case]
    benchmark = _frame(source_times, [20.0 + i for i in range(len(times))])
    control = bt.Cerebro(stdstats=False)
    control.adddata(bt.feeds.PandasData(dataname=benchmark, tzinput=tzinput))
    control.addstrategy(_FeedClock)
    observed = control.run(runonce=False, preload=True)[0].seen
    assert tuple(observed) == tuple((times + pd.Timedelta(hours=delta_hours)).to_pydatetime())

    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=("AAA",),
        source_timezone="Asia/Shanghai",
        snapshot_id="named-feed-timezone-clock",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"AAA": "g"},
    )
    target = _frame(times, [100.0 + i for i in range(len(times))])
    aligned = align_to_grid(_frame(times, [20.0 + i for i in range(len(times))]), research, "BENCH")
    source_feed = bt.feeds.PandasData(dataname=benchmark, tzinput=tzinput)
    source_feed._factor_research_alignment_v2 = aligned.feed._factor_research_alignment_v2
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(align_to_grid(target, research, "AAA").feed, name="AAA")
    cerebro.adddata(source_feed, name="BENCH")
    spec = FactorSpec(
        name="result",
        indicator=_Identity,
        mode=mode,
        panel_line="factor",
        field_bindings={"source": "feed:BENCH:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"result": spec})
    if delta_hours:
        with pytest.raises(DatasetError, match="factor source.*close"):
            cerebro.run(runonce=runonce, preload=preload)
    else:
        result = cerebro.run(runonce=runonce, preload=preload)[0].get_panel().factors["result"]
        assert result.tolist() == pytest.approx([20.0 + i for i in range(len(times))])


@pytest.mark.parametrize("dataname", ("opaque", ["opaque"]), ids=("string", "list"))
@pytest.mark.parametrize("same_grid", (False, True), ids=("different_grid", "matching_grid"))
def test_custom_feed_callable_index_uses_metadata_fallback(dataname, same_grid):
    """Exercise the time-axis helper, not strict factor binding of opaque data."""
    from types import SimpleNamespace
    from backtrader.errors import DatasetError

    times = pd.date_range("2024-03-01 16:00", periods=6, freq="B", tz="UTC", name="close_time")
    holder = SimpleNamespace(_research=SimpleNamespace(grid_sha256="same", source_timezone="UTC"))
    data = SimpleNamespace(p=SimpleNamespace(dataname=dataname, datetime=None))
    metadata = {"grid_sha256": "same" if same_grid else "different"}
    if same_grid:
        FactorStrategy._validate_source_close_times(holder, data, metadata, times)
    else:
        with pytest.raises(DatasetError, match="factor source.*close"):
            FactorStrategy._validate_source_close_times(holder, data, metadata, times)


@pytest.mark.parametrize("preload", (False, True), ids=("streaming", "preloaded"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("filter_kind", ("none", "noop", "fromdate", "todate", "drop"))
def test_named_feed_uses_actual_delivery_clock(preload, runonce, mode, filter_kind, tmp_path):
    from backtrader.errors import DatasetError
    from backtrader.research.sink import CsvSink

    times = pd.date_range("2024-04-01 16:00", periods=8, freq="B", tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=("AAA",),
        source_timezone="UTC",
        snapshot_id="named-feed-filter",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"AAA": "g"},
    )
    target = _frame(times, [100.0 + i for i in range(len(times))])
    benchmark = _frame(times, [20.0 + i for i in range(len(times))])
    aligned = align_to_grid(benchmark, research, "BENCH")
    options = {}
    if filter_kind == "fromdate":
        options["fromdate"] = times[1].tz_localize(None).to_pydatetime()
    elif filter_kind == "todate":
        options["todate"] = times[-2].tz_localize(None).to_pydatetime()
    feed = bt.feeds.PandasData(dataname=aligned.feed.p.dataname, **options)
    feed._factor_research_alignment_v2 = aligned.feed._factor_research_alignment_v2
    if filter_kind == "noop":
        feed.addfilter_simple(lambda data: False)
    elif filter_kind == "drop":
        skipped = bt.date2num(times[3].to_pydatetime())
        feed.addfilter_simple(lambda data: float(data.datetime[0]) == skipped)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(align_to_grid(target, research, "AAA").feed, name="AAA")
    cerebro.adddata(feed, name="BENCH")
    spec = FactorSpec(
        name="result",
        indicator=_IdentityZero,
        mode=mode,
        panel_line="factor",
        field_bindings={"source": "feed:BENCH:close"},
    )
    output = tmp_path / "panel"
    sink = CsvSink(output) if filter_kind == "drop" else None
    cerebro.addstrategy(FactorStrategy, research=research, factors={"result": spec}, sink=sink)
    if filter_kind in ("fromdate", "todate", "drop"):
        with pytest.raises(DatasetError, match="factor source.*(close|clock)"):
            cerebro.run(runonce=runonce, preload=preload)
        if sink is not None:
            assert sink._closed
            assert not output.exists()
    else:
        result = cerebro.run(runonce=runonce, preload=preload)[0].get_panel().factors["result"]
        assert result.tolist() == pytest.approx([20.0 + i for i in range(len(times))])


@pytest.mark.parametrize("preload", (False, True), ids=("streaming", "preloaded"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("filtered", (False, True), ids=("aligned", "filtered"))
def test_named_target_feed_clock_is_checked(preload, runonce, mode, filtered):
    from backtrader.errors import DatasetError

    times = pd.date_range("2024-05-01 16:00", periods=8, freq="B", tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=("AAA", "BBB"),
        source_timezone="UTC",
        snapshot_id="named-target-filter",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"AAA": "g1", "BBB": "g2"},
    )
    cerebro = bt.Cerebro(stdstats=False)
    for name, base in (("AAA", 100.0), ("BBB", 20.0)):
        source = _frame(times, [base + i for i in range(len(times))])
        aligned = align_to_grid(source, research, name)
        if name == "BBB" and filtered:
            feed = bt.feeds.PandasData(
                dataname=aligned.feed.p.dataname,
                fromdate=times[1].tz_localize(None).to_pydatetime(),
            )
            feed._factor_research_alignment_v2 = aligned.feed._factor_research_alignment_v2
        else:
            feed = aligned.feed
        cerebro.adddata(feed, name=name)
    spec = FactorSpec(
        name="result",
        indicator=_IdentityZero,
        mode=mode,
        panel_line="factor",
        field_bindings={"source": "feed:BBB:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"result": spec})
    if filtered:
        with pytest.raises(DatasetError, match="factor source.*(close|clock)"):
            cerebro.run(runonce=runonce, preload=preload)
    else:
        panel = cerebro.run(runonce=runonce, preload=preload)[0].get_panel().factors
        for asset in research.targets:
            assert panel.xs(asset, level="asset")["result"].tolist() == pytest.approx(
                [20.0 + i for i in range(len(times))]
            )


@pytest.mark.parametrize("lookahead", (0, 1))
@pytest.mark.parametrize("source_aligned", (False, True), ids=("raw_extra", "aligned"))
def test_named_source_window_end_and_lookahead(lookahead, source_aligned):
    times = pd.date_range("2024-06-03 16:00", periods=8, freq="B", tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[2],
        end=times[5],
        targets=("AAA",),
        source_timezone="UTC",
        snapshot_id="named-source-end",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"AAA": "g"},
    )
    target = _frame(times, [100.0 + i for i in range(len(times))])
    benchmark = _frame(times, [20.0 + i for i in range(len(times))])
    cerebro = bt.Cerebro(stdstats=False, lookahead=lookahead)
    cerebro.adddata(align_to_grid(target, research, "AAA").feed, name="AAA")
    bench = (
        align_to_grid(benchmark, research, "BENCH").feed
        if source_aligned
        else bt.feeds.PandasData(dataname=benchmark)
    )
    cerebro.adddata(bench, name="BENCH")
    spec = FactorSpec(
        name="result",
        indicator=_IdentityZero,
        mode="native",
        panel_line="factor",
        field_bindings={"source": "feed:BENCH:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"result": spec})
    result = cerebro.run(runonce=True, preload=True)[0].get_panel().factors["result"]
    assert result.tolist() == pytest.approx([22.0, 23.0, 24.0, 25.0])


@pytest.mark.parametrize("preload", (False, True), ids=("streaming", "preloaded"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("offset_hours", (0, 1), ids=("matching_prefix", "shifted_prefix"))
def test_named_source_metadata_with_future_bars_is_rejected(preload, runonce, mode, offset_hours):
    from backtrader.errors import DatasetError

    times = pd.date_range("2024-07-01 16:00", periods=10, freq="B", tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[2],
        end=times[5],
        targets=("AAA",),
        source_timezone="UTC",
        snapshot_id="named-feed-future-bars",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"AAA": "g"},
    )
    target = _frame(times, [100.0 + i for i in range(len(times))])
    prices = [20.0 + i for i in range(len(times))]
    marker = align_to_grid(_frame(times, prices), research, "BENCH").feed
    assert len(marker._factor_research_alignment_v2["field_present"]["close"]) == 6
    source_times = times + pd.Timedelta(hours=offset_hours)
    source = bt.feeds.PandasData(dataname=_frame(source_times, prices))
    source._factor_research_alignment_v2 = marker._factor_research_alignment_v2
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(align_to_grid(target, research, "AAA").feed, name="AAA")
    cerebro.adddata(source, name="BENCH")
    spec = FactorSpec(
        name="result",
        indicator=_Identity,
        mode=mode,
        panel_line="factor",
        field_bindings={"source": "feed:BENCH:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"result": spec})
    # Copying the private mask onto a longer feed is not the public aligned
    # feed contract: non-once scheduling would continue beyond research.end.
    # Both the matching-prefix and shifted-prefix variants fail closed.
    with pytest.raises(DatasetError, match="factor source.*close"):
        cerebro.run(runonce=runonce, preload=preload)


@pytest.mark.parametrize("preload", (False, True), ids=("streaming", "preloaded"))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize(
    "variant", ("aligned_gap", "noop_metadata", "filtered_metadata", "sparse_raw")
)
def test_target_source_clock_preserves_aligned_gaps_and_legacy_fallback(
    preload, runonce, mode, variant, tmp_path
):
    from backtrader.errors import FactorComputationError
    from backtrader.research.sink import CsvSink

    times = pd.date_range("2024-08-01 16:00", periods=8, freq="B", tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=("AAA", "BBB"),
        source_timezone="UTC",
        snapshot_id="target-source-filter",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"AAA": "g1", "BBB": "g2"},
    )
    cerebro = bt.Cerebro(stdstats=False)
    frame_a = _frame(times, [100.0 + i for i in range(len(times))])
    frame_b = _frame(times, [20.0 + i for i in range(len(times))])
    cerebro.adddata(align_to_grid(frame_a, research, "AAA").feed, name="AAA")
    if variant == "sparse_raw":
        feed = bt.feeds.PandasData(dataname=frame_b.drop(index=times[3]))
    elif variant == "aligned_gap":
        feed = align_to_grid(frame_b.drop(index=times[3]), research, "BBB").feed
    else:
        aligned = align_to_grid(frame_b, research, "BBB").feed
        feed = bt.feeds.PandasData(dataname=aligned.p.dataname)
        feed._factor_research_alignment_v2 = aligned._factor_research_alignment_v2
        if variant == "noop_metadata":
            feed.addfilter_simple(lambda data: False)
        else:
            skipped = bt.date2num(times[3].to_pydatetime())
            feed.addfilter_simple(lambda data: float(data.datetime[0]) == skipped)
    cerebro.adddata(feed, name="BBB")
    spec = FactorSpec(
        name="result",
        indicator=_Identity,
        mode=mode,
        panel_line="factor",
        field_bindings={"source": "feed:target:close"},
    )
    output = tmp_path / "panel"
    sink = CsvSink(output) if variant in ("filtered_metadata", "sparse_raw") else None
    cerebro.addstrategy(FactorStrategy, research=research, factors={"result": spec}, sink=sink)
    if variant in ("filtered_metadata", "sparse_raw"):
        # Both remain rejected by the existing graph-clock guard. Unaligned
        # target feeds have no metadata proof of their historical windows.
        with pytest.raises(FactorComputationError) as exc:
            cerebro.run(runonce=runonce, preload=preload)
        assert isinstance(exc.value.__cause__, RuntimeError)
        assert "factor next() time does not match" in str(exc.value.__cause__)
        assert sink._closed and not output.exists()
    else:
        factors = cerebro.run(runonce=runonce, preload=preload)[0].get_panel().factors
        result = factors.xs("BBB", level="asset")["result"].tolist()
        if variant == "aligned_gap":
            assert result[:3] == pytest.approx([20.0, 21.0, 22.0])
            assert all(math.isnan(result[i]) for i in (3, 4, 5))
            assert result[6:] == pytest.approx([26.0, 27.0])
        else:
            assert result == pytest.approx([20.0 + i for i in range(len(times))])
