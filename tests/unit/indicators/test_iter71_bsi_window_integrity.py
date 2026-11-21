"""Window and missing-value regression tests for BSIIndicator."""

import datetime as dt
import math

import backtrader as bt
import pytest


N = 40
PARAMS = {"range_period": 3, "slowing": 2, "avg_period": 2}


def source_data(field):
    result = {key: [] for key in ("high", "low", "close", "volume", "openinterest")}
    for i in range(N):
        close = 100 + math.sin(i * 0.8) * 3 + i * 0.05
        result["close"].append(close)
        result["high"].append(close + 1.3 + (i % 3) * 0.2)
        result["low"].append(close - 1.0 - (i % 4) * 0.1)
        result["volume"].append(100.0 + i)
        result["openinterest"].append(80.0 + i)
    if field is not None:
        result[field][15] = math.nan
    return result


def expected_component(data, index, ago, volume_mode):
    positive = negative = total_range = 0.0
    for k in range(PARAMS["slowing"]):
        offset = ago + k
        bars = range(index - offset - PARAMS["range_period"] + 1, index - offset + 1)
        highs = [data["high"][n] for n in bars]
        lows = [data["low"][n] for n in bars]
        pos = index - offset
        close = data["close"][pos]
        previous = data["close"][pos - 1]
        high, low = data["high"][pos], data["low"][pos]
        used = highs + lows + [close, previous, high, low]
        if volume_mode == "NONE":
            volume = 1.0
        else:
            field = "openinterest" if volume_mode == "VOLUME" else "volume"
            volumes = [data[field][n] for n in bars]
            used += volumes
            if any(math.isnan(x) for x in used):
                return math.nan
            maximum = max(volumes)
            volume = data[field][pos] / maximum if maximum else 0.0
        if any(math.isnan(x) for x in used):
            return math.nan
        hh, ll = max(highs), min(lows)
        spread = high - low
        width = max(hh - ll, 1e-12)
        if not previous - spread * 0.2 > close:
            ratio = 1.0 if low == ll else (hh - low) / width
            positive += (close - low) * ratio * volume
        if not previous + spread * 0.2 < close:
            ratio = 1.0 if high == hh else (high - ll) / width
            negative -= (high - close) * ratio * volume
        total_range += width
    return (positive + negative) / total_range * 100.0 if total_range else 0.0


def expected(data, index, mode):
    values = [expected_component(data, index, ago, mode) for ago in range(PARAMS["avg_period"])]
    return sum(values) / len(values)


def matches(value, expected_value):
    if math.isnan(expected_value):
        assert math.isnan(value)
    else:
        assert value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("mode", ["NONE", "TICK", "VOLUME"])
@pytest.mark.parametrize("missing", [None, "high", "low", "close", "volume", "openinterest"])
def test_bsi_window_and_color_match_independent_reference(once, mode, missing):
    data = source_data(missing)
    samples = []

    class Feed(bt.feed.DataBase):
        def __init__(self):
            super().__init__()
            self.i = 0

        def _load(self):
            if self.i >= N:
                return False
            i = self.i
            self.datetime[0] = bt.date2num(dt.datetime(2024, 1, 1) + dt.timedelta(minutes=i))
            self.open[0] = data["close"][i]
            for name in ("high", "low", "close", "volume", "openinterest"):
                getattr(self.lines, name)[0] = data[name][i]
            self.i += 1
            return True

    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.BSIIndicator(self.data, volume_mode=mode, **PARAMS)

        def next(self):
            samples.append((len(self.data) - 1, float(self.ind.bsi[0]), float(self.ind.color[0])))

    cerebro = bt.Cerebro(stdstats=False, runonce=once)
    cerebro.adddata(Feed())
    cerebro.addstrategy(Strategy)
    strategy = cerebro.run(preload=once)[0]
    assert strategy.ind._minperiod == 10
    assert samples[0][0] == 9
    previous = None
    for index, bsi, color in samples:
        wanted = expected(data, index, mode)
        matches(bsi, wanted)
        if math.isnan(wanted):
            wanted_color = math.nan
        elif previous is None:
            wanted_color = 1.0
        elif math.isnan(previous):
            wanted_color = math.nan
        elif previous > wanted:
            wanted_color = 0.0
        elif previous < wanted:
            wanted_color = 2.0
        else:
            wanted_color = 1.0
        matches(color, wanted_color)
        previous = wanted


@pytest.mark.parametrize("once", [False, True])
def test_strict_inf_is_not_hidden_by_earlier_nan(once):
    import pandas as pd
    from backtrader.errors import FactorComputationError
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    index = pd.date_range("2024-01-01", periods=30, freq="min", tz="UTC", name="close_time")
    data = source_data(None)
    frame = pd.DataFrame({name: values[:30] for name, values in data.items()}, index=index)
    frame["open"] = frame.close
    spec = ResearchSpec(
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
        formula_fields = required_fields = ("high", "low", "close", "volume")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.ind = bt.ind.BSIIndicator(self.data, volume_mode="TICK", **PARAMS)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.ind.bsi[0]

    feed = align_to_grid(frame, spec, "asset").feed
    original = feed._load

    def injected():
        success = original()
        if success and len(feed) == 12:
            feed.high.array[feed.high.idx] = math.nan
            feed.low.array[feed.low.idx] = math.inf
        return success

    feed._load = injected
    cerebro = bt.Cerebro(stdstats=False, runonce=once, preload=once)
    cerebro.adddata(feed, name="asset")
    factor = FactorSpec(
        name="test",
        indicator=Factor,
        panel_line="factor",
        mode="native",
        field_bindings={key: "feed:target:" + key for key in Factor.formula_fields},
    )
    cerebro.addstrategy(FactorStrategy, research=spec, factors={"test": factor})
    with pytest.raises(FactorComputationError) as caught:
        cerebro.run()
    assert isinstance(caught.value.__cause__, ArithmeticError)


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("exit_case", ["none", "stop", "take_profit"])
def test_original_strategy_gates_missing_signal_and_keeps_protective_exit(
    once, exit_case, monkeypatch
):
    import importlib.util
    import sys
    from pathlib import Path

    import pandas as pd

    path = (
        Path(__file__).resolve().parents[2]
        / "functional"
        / "strategies"
        / "trend_following"
        / "test_0250_0862_bsi.py"
    )
    module_spec = importlib.util.spec_from_file_location("bsi_strategy_integrity", path)
    module = importlib.util.module_from_spec(module_spec)
    monkeypatch.setitem(sys.modules, module_spec.name, module)
    module_spec.loader.exec_module(module)

    index = pd.date_range("2024-01-01", periods=N, freq="min")
    signal = pd.DataFrame(source_data("high"), index=index)
    signal["open"] = signal.close
    base = pd.DataFrame(source_data(None), index=index)
    base["open"] = base.close
    if exit_case == "stop":
        base.loc[index[15], ["close", "high"]] = [120.0, 121.0]
    elif exit_case == "take_profit":
        base.loc[index[15], ["close", "low"]] = [80.0, 79.0]

    events = []
    observed = {}

    class Probe(module.ExpBSIStrategy):
        def buy(self, *args, **kwargs):
            events.append(("buy", len(self.signal_data) - 1))
            return super().buy(*args, **kwargs)

        def sell(self, *args, **kwargs):
            events.append(("sell", len(self.signal_data) - 1))
            return super().sell(*args, **kwargs)

        def close(self, *args, **kwargs):
            events.append(("close", len(self.signal_data) - 1))
            return super().close(*args, **kwargs)

        def next(self):
            bar = len(self.signal_data) - 1
            if bar == 15:
                observed[bar] = (
                    float(self.ind.color[0]),
                    float(self.ind.color[-1]),
                    self.position.size,
                )
            return super().next()

    cerebro = bt.Cerebro(stdstats=False, runonce=once, preload=once)
    cerebro.broker.setcash(1_000_000)
    cerebro.adddata(bt.feeds.PandasData(dataname=base))
    cerebro.adddata(bt.feeds.PandasData(dataname=signal))
    cerebro.addstrategy(
        Probe,
        range_period=3,
        slowing=2,
        avg_period=2,
        volume_mode="TICK",
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=1000,
        fixed_lot=0.1,
        point=0.01,
    )
    cerebro.run()
    current, previous, position = observed[15]
    assert math.isnan(current) and previous == 2.0 and position == pytest.approx(-0.1)
    assert ("sell", 14) in events
    at_missing_bar = [name for name, bar in events if bar == 15]
    if exit_case == "none":
        assert at_missing_bar == []
        assert any(bar >= 22 for _, bar in events)
    else:
        assert at_missing_bar == ["close", "buy"]
