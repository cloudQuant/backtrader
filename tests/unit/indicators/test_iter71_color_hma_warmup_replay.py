"""ColorHMA uses complete Hull windows from the first declared callback."""

import math

import pandas as pd
import pytest

import backtrader as bt


def _weighted(values):
    return sum((index + 1) * value for index, value in enumerate(values)) / sum(
        range(1, len(values) + 1)
    )


def _reference(closes, period):
    half = max(period // 2, 1)
    root = max(math.isqrt(period), 1)
    dma = []
    values = [math.nan] * len(closes)
    direction = [math.nan] * len(closes)
    for index in range(period - 1, len(closes)):
        short = _weighted(closes[index - half + 1 : index + 1])
        long = _weighted(closes[index - period + 1 : index + 1])
        dma.append(2.0 * short - long)
        if len(dma) < root:
            continue
        current = _weighted(dma[-root:])
        values[index] = current
        previous = values[index - 1]
        if not math.isfinite(current) or not math.isfinite(previous):
            continue
        if current > previous:
            direction[index] = 1.0
        elif current < previous:
            direction[index] = -1.0
        else:
            prior = direction[index - 1]
            direction[index] = prior if math.isfinite(prior) else 0.0
    return values, direction


def _frame(kind="varying"):
    closes = [100.0 + i * 0.15 + math.sin(i * 0.73) * 4.0 for i in range(120)]
    if kind == "flat":
        closes = [100.0] * len(closes)
    elif kind == "missing":
        closes[60] = math.nan
    return pd.DataFrame(
        {
            "open": closes,
            "high": [x + 1 for x in closes],
            "low": [x - 1 for x in closes],
            "close": closes,
            "volume": [1.0] * len(closes),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="h"),
    )


def _same(actual, expected):
    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("period", [2, 5, 13, 25])
@pytest.mark.parametrize("kind", ["varying", "flat", "missing"])
def test_formula_warmup_and_recovery(runonce, period, kind):
    data = _frame(kind)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.ColorHMA(self.data, period=period)
            self.down = bt.ind.SMA(self.ind.hma, period=2)
            self.calls = []

        def next(self):
            self.calls.append(len(self.data))

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Strategy)
    s = c.run()[0]
    required = period + math.isqrt(period)
    assert s.ind._minperiod == required
    assert s.down._minperiod == required + 1
    assert s.calls[0] == required + 1
    hma, direction = _reference(list(data.close), period)
    for index in range(required - 1, len(data)):
        _same(float(s.ind.hma.array[index]), hma[index])
        _same(float(s.ind.direction.array[index]), direction[index])
    assert len(s.ind._dma_history) <= math.isqrt(period)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("period", [5, 13])
def test_intraday_replay_recomputes_current_bar(runonce, period):
    rows = []
    times = []
    for day in range(32):
        for hour in (9, 10, 11):
            close = 100 + day * 0.15 + math.sin((day * 3 + hour) * 0.73) * 4.0
            rows.append({"open": close, "high": close + 1, "low": close - 1, "close": close})
            times.append(pd.Timestamp("2024-01-01") + pd.Timedelta(days=day, hours=hour))
    data = pd.DataFrame(rows, index=times)
    data["volume"] = 1.0

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.ColorHMA(self.data, period=period)
            self.closes = []
            self.observed = []

        def prenext(self):
            self.sample()

        def nextstart(self):
            self.sample()

        def next(self):
            self.sample()

        def sample(self):
            count = len(self.data)
            if len(self.closes) < count:
                self.closes.append(float(self.data.close[0]))
            else:
                self.closes[-1] = float(self.data.close[0])
            if count >= self.ind._minperiod:
                hma, direction = _reference(self.closes, period)
                self.observed.append(
                    (float(self.ind.hma[0]), float(self.ind.direction[0]), hma[-1], direction[-1])
                )

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.replaydata(bt.feeds.PandasData(dataname=data), timeframe=bt.TimeFrame.Days)
    c.addstrategy(Strategy)
    s = c.run()[0]
    assert len(s.observed) >= 30
    for actual_hma, actual_dir, expected_hma, expected_dir in s.observed:
        _same(actual_hma, expected_hma)
        _same(actual_dir, expected_dir)


@pytest.mark.parametrize("exactbars", [0, 1])
@pytest.mark.parametrize("period", [5, 13])
def test_streaming_with_bounded_history(exactbars, period):
    data = _frame("varying")
    expected_hma, expected_direction = _reference(list(data.close), period)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.ColorHMA(self.data, period=period)
            self.values = []

        def next(self):
            self.values.append(
                (len(self.data) - 1, float(self.ind.hma[0]), float(self.ind.direction[0]))
            )

    c = bt.Cerebro(stdstats=False, runonce=False, preload=False, exactbars=exactbars)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    assert strategy.values[0][0] == period + math.isqrt(period) - 1
    for index, actual_hma, actual_direction in strategy.values:
        _same(actual_hma, expected_hma[index])
        _same(actual_direction, expected_direction[index])


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("case", ["missing", "positive_infinity", "negative_infinity"])
def test_real_strict_factor_missing_and_injected_infinity(runonce, case):
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    data = _frame("varying").iloc[:45].copy()
    data.index = data.index.tz_localize("UTC").rename("close_time")
    if case == "missing":
        data.iloc[20, data.columns.get_loc("close")] = math.nan
    index = data.index
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=1)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="colorhma-strict",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1h",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )
    seen = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.ind.ColorHMA(self.data, period=5)
            seen.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.hma[0]

    feed = align_to_grid(data, research, "asset").feed
    load = feed._load

    def inject():
        result = load()
        if result and len(feed) == 21 and case != "missing":
            sign = 1.0 if case == "positive_infinity" else -1.0
            feed.lines.close.array[feed.lines.close.idx] = sign * math.inf
        return result

    feed._load = inject
    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(feed, name="asset")
    spec = FactorSpec(
        name="hma",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={"hma": spec})
    if case != "missing":
        with pytest.raises(FactorComputationError) as caught:
            c.run(preload=True)
        assert isinstance(caught.value.__cause__, ArithmeticError)
        return
    c.run(preload=True)
    factor = seen[-1]
    assert not factor._factor_strict_context.failed
    assert math.isnan(float(factor.child.hma.array[20]))
    assert math.isfinite(float(factor.child.hma.array[26]))


@pytest.mark.parametrize("runonce", [False, True])
def test_indicator_source_warmup_carries_input_period(runonce):
    data = _frame("varying")

    class Strategy(bt.Strategy):
        def __init__(self):
            self.source = bt.ind.SMA(self.data.close, period=3)
            self.ind = bt.ind.ColorHMA(self.source, period=5)
            self.calls = []

        def next(self):
            self.calls.append(len(self.data))

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    assert strategy.ind._minperiod == 9
    assert strategy.calls[0] == 9
    source = [math.nan, math.nan] + [
        sum(data.close.iloc[index - 2 : index + 1]) / 3 for index in range(2, len(data))
    ]
    hma, direction = _reference(source, 5)
    for index in range(8, len(data)):
        _same(float(strategy.ind.hma.array[index]), hma[index])
        _same(float(strategy.ind.direction.array[index]), direction[index])


@pytest.mark.parametrize("runonce", [False, True])
def test_subclass_next_is_not_called_during_warmup(runonce):
    class Hooked(bt.ind.ColorHMA):
        def __init__(self):
            self.next_calls = []
            super().__init__()

        def next(self):
            self.next_calls.append(len(self.data))
            super().next()

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = Hooked(self.data, period=13)

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=_frame()))
    c.addstrategy(Strategy)
    indicator = c.run()[0].ind
    assert indicator.next_calls == list(range(16, 121))


@pytest.mark.parametrize("slices", [[(12, 20)], [(12, 15), (15, 20)]])
def test_indicator_source_segmented_recalculation_restores_cursors(slices):
    data = _frame("varying")

    class Strategy(bt.Strategy):
        def __init__(self):
            self.source = bt.ind.SMA(self.data.close, period=3)
            self.ind = bt.ind.ColorHMA(self.source, period=5)

    c = bt.Cerebro(stdstats=False, runonce=True)
    c.adddata(bt.feeds.PandasData(dataname=data))
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    indicator = strategy.ind
    lines = [*strategy.source.lines, *indicator.lines]
    positions = [(line.idx, line.lencount) for line in lines]
    history = list(indicator._dma_history)
    last_bar = indicator._last_dma_bar
    expected = [[float(value) for value in line.array] for line in indicator.lines]
    for start, end in slices:
        for index in range(start, end):
            indicator.hma.array[index] = math.nan
            indicator.direction.array[index] = math.nan
        indicator.once(start, end)
    assert [(line.idx, line.lencount) for line in lines] == positions
    assert indicator._dma_history == history
    assert indicator._last_dma_bar == last_bar
    for line, expected_line in zip(indicator.lines, expected):
        for actual, reference in zip(line.array, expected_line):
            _same(float(actual), reference)


@pytest.mark.parametrize("runonce", [False, True])
def test_shared_indicator_source_on_slower_feed(runonce):
    slow = _frame("varying").iloc[:40].copy()
    slow.index = pd.date_range("2024-01-01", periods=len(slow), freq="D")
    fast = slow.reindex(pd.date_range("2024-01-01", periods=157, freq="6h")).ffill()

    class Strategy(bt.Strategy):
        def __init__(self):
            self.source = bt.ind.SMA(self.data1.close, period=3)
            self.first = bt.ind.ColorHMA(self.source, period=5)
            self.second = bt.ind.ColorHMA(self.source, period=13)
            self.sibling = bt.ind.SMA(self.source, period=4)
            self.down = bt.ind.SMA(self.first.hma, period=2)

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=fast))
    c.adddata(bt.feeds.PandasData(dataname=slow))
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    source = [math.nan, math.nan] + [
        sum(slow.close.iloc[index - 2 : index + 1]) / 3 for index in range(2, len(slow))
    ]
    assert (strategy.first._minperiod, strategy.second._minperiod, strategy.down._minperiod) == (
        9,
        18,
        10,
    )
    for indicator, period in ((strategy.first, 5), (strategy.second, 13)):
        hma, direction = _reference(source, period)
        for index in range(indicator._minperiod - 1, len(slow)):
            _same(float(indicator.hma.array[index]), hma[index])
            _same(float(indicator.direction.array[index]), direction[index])
    for index in range(5, len(slow)):
        expected = sum(source[index - 3 : index + 1]) / 4
        _same(float(strategy.sibling.array[index]), expected)


def test_failed_indicator_source_batch_restores_input_cursor():
    seen = []

    class Failing(bt.ind.ColorHMA):
        def next(self):
            if len(self.data) == 12:
                raise RuntimeError("synthetic callback failure")
            super().next()

    class Strategy(bt.Strategy):
        def __init__(self):
            self.source = bt.ind.SMA(self.data.close, period=3)
            self.ind = Failing(self.source, period=5)
            seen.append(self)

    c = bt.Cerebro(stdstats=False, runonce=True)
    c.adddata(bt.feeds.PandasData(dataname=_frame()))
    c.addstrategy(Strategy)
    with pytest.raises(RuntimeError, match="synthetic callback failure"):
        c.run()
    assert all((line.idx, line.lencount) == (-1, 0) for line in seen[0].source.lines)


def test_failed_segment_restores_cursor_and_rolling_state():
    class Failing(bt.ind.ColorHMA):
        def __init__(self):
            self.fail = False
            super().__init__()

        def next(self):
            if self.fail and len(self.data) == 13:
                raise RuntimeError("synthetic segment failure")
            super().next()

    class Strategy(bt.Strategy):
        def __init__(self):
            self.source = bt.ind.SMA(self.data.close, period=3)
            self.ind = Failing(self.source, period=5)

    c = bt.Cerebro(stdstats=False, runonce=True)
    c.adddata(bt.feeds.PandasData(dataname=_frame()))
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    indicator = strategy.ind
    lines = [*strategy.source.lines, *indicator.lines]
    positions = [(line.idx, line.lencount) for line in lines]
    history = list(indicator._dma_history)
    last_bar = indicator._last_dma_bar
    indicator.fail = True
    with pytest.raises(RuntimeError, match="synthetic segment failure"):
        indicator.once(12, 16)
    assert [(line.idx, line.lencount) for line in lines] == positions
    assert indicator._dma_history == history
    assert indicator._last_dma_bar == last_bar
