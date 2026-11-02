from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import pytest

import backtrader as bt
import backtrader.research.factor_strategy as factor_strategy_module
from backtrader.research import align_to_grid
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.sink import MemorySink, PanelContext
from backtrader.research.specs import FactorSpec, ResearchSpec

_UNSET = object()


class _CloseFactor(FactorIndicator):
    lines = ("factor",)
    panel_mode = "next"
    formula_fields = ("close",)

    @classmethod
    def lookback_h(cls) -> int:
        return 0

    def __init__(self) -> None:
        super().__init__()
        self._closes = self.field_lines("close")

    def next(self) -> None:
        for data, close in zip(self.target_datas, self._closes):
            self.outputs[data].factor[0] = close[0]


class _DateLine:
    def __init__(self, value: float) -> None:
        self.value = value

    def __getitem__(self, index: int) -> float:
        assert index == 0
        return self.value


class _Data:
    def __init__(self, number: float) -> None:
        self.datetime = _DateLine(number)
        self.open = _DateLine(10.0)
        self.close = _DateLine(11.0)


def _inputs():
    index = pd.date_range(
        "2025-01-01 16:00:00", periods=4, freq="D", tz="UTC", name="close_time"
    )
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)
    research = ResearchSpec(
        grid=grid,
        start=index[1],
        end=index[2],
        targets=("AAA",),
        source_timezone="UTC",
        snapshot_id="g7-test",
        price_basis="USD close, unadjusted",
        calendar_id="g7-calendar",
        frequency="1day",
    )
    close = np.array([10.0, 11.0, 12.0, 13.0])
    source = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": np.array([100.0, 110.0, 120.0, 130.0]),
        },
        index=index,
    )
    return index, research, source


def _run_strategy(
    runonce: bool,
    *,
    sink=_UNSET,
    incomplete_metadata: bool = False,
    strategy_cls=FactorStrategy,
):
    index, research, source = _inputs()
    aligned = align_to_grid(source, research, "AAA")
    if incomplete_metadata:
        aligned.feed._factor_research_alignment_v2["prices_open"] = None

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(aligned.feed, name="AAA")
    factor = FactorSpec(
        name="close_factor",
        indicator=_CloseFactor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
    )
    options = {} if sink is _UNSET else {"sink": sink}
    cerebro.addstrategy(
        strategy_cls, research=research, factors={"close_factor": factor}, **options
    )
    strategy = cerebro.run(runonce=runonce)[0]
    return index, strategy


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_default_aligned_strategy_uses_dense_sink_without_time_asset_lists(
    runonce: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_close = MemorySink.close
    close_states = []

    def capture_close(sink: MemorySink) -> None:
        close_states.append(
            (
                sink._dense_expected_rows,
                sink._row_count,
                len(sink._times),
                len(sink._assets),
                len(sink._open),
                len(sink._close),
            )
        )
        original_close(sink)

    real_num2date = factor_strategy_module.num2date
    converted = []

    def count_num2date(value, **kwargs):
        converted.append(float(value))
        return real_num2date(value, **kwargs)

    monkeypatch.setattr(MemorySink, "close", capture_close)
    monkeypatch.setattr(factor_strategy_module, "num2date", count_num2date)
    index, strategy = _run_strategy(runonce)

    assert close_states == [(2, 2, 0, 0, 2, 2)]
    assert len(converted) == 3
    assert list(strategy.get_panel().factors.index) == [
        (index[1], "AAA"),
        (index[2], "AAA"),
    ]
    assert list(strategy.get_panel().factors["close_factor"]) == [11.0, 12.0]


def _multi_inputs():
    index = pd.date_range(
        "2025-02-01 16:00:00", periods=6, freq="D", tz="UTC", name="close_time"
    )
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)
    research = ResearchSpec(
        grid=grid,
        start=index[2],
        end=index[4],
        targets=("BBB", "AAA"),
        source_timezone="UTC",
        snapshot_id="g7-multi-test",
        price_basis="USD close, unadjusted",
        calendar_id="g7-calendar",
        frequency="1day",
    )
    frames = {}
    for asset, base in (("AAA", 10.0), ("BBB", 100.0)):
        closes = base + np.arange(len(index), dtype="float64")
        frames[asset] = pd.DataFrame(
            {
                "open": closes - 0.5,
                "high": closes + 0.5,
                "low": closes - 1.0,
                "close": closes,
                "volume": 100.0 + closes,
            },
            index=index,
        )
    frames["BBB"] = frames["BBB"].drop(index[3])
    return index, research, frames


def _run_multi_strategy(runonce: bool, *, sink=_UNSET):
    index, research, frames = _multi_inputs()
    aligned = {asset: align_to_grid(frame, research, asset) for asset, frame in frames.items()}
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    # Add in the opposite order from the declared research target order.
    cerebro.adddata(aligned["AAA"].feed, name="AAA")
    cerebro.adddata(aligned["BBB"].feed, name="BBB")
    factor = FactorSpec(
        name="close_factor",
        indicator=_CloseFactor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
    )
    options = {} if sink is _UNSET else {"sink": sink}
    cerebro.addstrategy(
        FactorStrategy, research=research, factors={"close_factor": factor}, **options
    )
    strategy = cerebro.run(runonce=runonce)[0]
    return index, strategy


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_multitarget_dense_and_explicit_sinks_build_identical_complete_panel(
    runonce: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = []
    original_close = MemorySink.close

    def capture_close(sink: MemorySink) -> None:
        snapshots.append(
            (
                sink._dense_expected_rows,
                sink._row_count,
                len(sink._times),
                len(sink._assets),
                len(sink._open),
                len(sink._close),
            )
        )
        original_close(sink)

    monkeypatch.setattr(MemorySink, "close", capture_close)
    index, default_strategy = _run_multi_strategy(runonce)
    _, explicit_strategy = _run_multi_strategy(runonce, sink=MemorySink())
    default_panel = default_strategy.get_panel()
    explicit_panel = explicit_strategy.get_panel()

    expected_index = pd.MultiIndex.from_product(
        [index[2:5], ("BBB", "AAA")], names=("time", "asset")
    )
    assert default_panel.factors.index.equals(expected_index)
    assert list(default_panel.grid.index) == list(index)
    assert list(default_panel.prices_open.index) == list(index)
    assert list(default_panel.prices_close.index) == list(index)
    assert pd.isna(default_panel.factors.loc[(index[3], "BBB"), "close_factor"])
    assert default_panel.factors.loc[(index[3], "AAA"), "close_factor"] == 13.0
    assert pd.isna(default_panel.prices_open.loc[index[3], "BBB"])
    assert pd.isna(default_panel.prices_close.loc[index[3], "BBB"])
    assert snapshots == [(6, 6, 0, 0, 6, 6), (None, 6, 6, 6, 6, 6)]

    pd.testing.assert_frame_equal(default_panel.factors, explicit_panel.factors)
    pd.testing.assert_frame_equal(default_panel.grid, explicit_panel.grid)
    pd.testing.assert_frame_equal(default_panel.prices_open, explicit_panel.prices_open)
    pd.testing.assert_frame_equal(default_panel.prices_close, explicit_panel.prices_close)
    pd.testing.assert_frame_equal(default_panel.universe, explicit_panel.universe)
    assert default_panel.start == explicit_panel.start
    assert default_panel.end == explicit_panel.end
    assert default_panel.target_order == explicit_panel.target_order == ("BBB", "AAA")
    assert default_panel.factor_order == explicit_panel.factor_order == ("close_factor",)
    assert default_panel.directions == explicit_panel.directions
    assert default_panel.groups == explicit_panel.groups


@pytest.mark.parametrize(
    ("sink", "incomplete_metadata"),
    [(MemorySink(), False), (None, True)],
    ids=["caller-owned-sink", "incomplete-alignment"],
)
def test_nonprivate_or_incomplete_collection_keeps_ordinary_sink_path(
    sink: Optional[MemorySink], incomplete_metadata: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = []
    original_close = MemorySink.close

    def capture_close(instance: MemorySink) -> None:
        snapshots.append(
            (instance._dense_expected_rows, len(instance._times), len(instance._assets))
        )
        original_close(instance)

    # Capture the pre-close state while leaving the ordinary close contract intact.
    monkeypatch.setattr(MemorySink, "close", capture_close)
    index, strategy = _run_strategy(False, sink=sink, incomplete_metadata=incomplete_metadata)

    assert snapshots == [(None, 2, 2)]
    assert list(strategy.get_panel().factors.index) == [
        (index[1], "AAA"),
        (index[2], "AAA"),
    ]


def test_factor_strategy_subclass_keeps_one_argument_feed_time_override() -> None:
    class _LegacyDateStrategy(FactorStrategy):
        feed_time_calls = []

        def _current_feed_time(self, data):
            type(self).feed_time_calls.append(data)
            return FactorStrategy._current_feed_time(data)

    _LegacyDateStrategy.feed_time_calls = []
    index, strategy = _run_strategy(False, strategy_cls=_LegacyDateStrategy)

    assert len(_LegacyDateStrategy.feed_time_calls) == 3
    assert all(data is strategy.datas[0] for data in _LegacyDateStrategy.feed_time_calls)
    assert list(strategy.get_panel().factors.index) == [
        (index[1], "AAA"),
        (index[2], "AAA"),
    ]


def test_ordinary_sink_finalize_keeps_partial_row_error_order() -> None:
    index, research, _ = _inputs()
    sink = MemorySink()
    with pytest.raises(TypeError):
        sink.on_point(
            index[1].to_pydatetime(),
            "AAA",
            {"close_factor": object()},
            10.0,
            11.0,
            True,
        )

    assert len(sink._times) == 1
    assert len(sink._assets) == 1
    assert sink._row_count == 0
    context = PanelContext(
        grid=research.grid,
        start=research.start,
        end=research.end,
        target_order=("AAA",),
        factor_order=("close_factor",),
        directions={"close_factor": 1},
    )
    with pytest.raises(ValueError) as error:
        sink.finalize(context)
    assert "no grid points" not in str(error.value)


def test_feed_date_conversion_falls_back_when_float_dates_differ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = datetime(2025, 1, 1, tzinfo=timezone.utc)
    feed = datetime(2025, 1, 2, tzinfo=timezone.utc)
    calls = []
    numbers = {1.0: primary, 2.0: feed}

    def convert(number, **kwargs):
        calls.append(number)
        return numbers[number]

    monkeypatch.setattr(factor_strategy_module, "num2date", convert)

    assert FactorStrategy._current_feed_time(_Data(2.0), 1.0, primary) == feed
    assert calls == [2.0]


def test_current_feed_time_keeps_single_argument_and_none_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = datetime(2025, 1, 2, tzinfo=timezone.utc)
    calls = []

    def convert(number, **kwargs):
        calls.append((number, kwargs))
        return expected

    monkeypatch.setattr(factor_strategy_module, "num2date", convert)

    assert FactorStrategy._current_feed_time(_Data(2.0)) == expected
    assert calls == [(2.0, {"tz": timezone.utc, "naive": False})]

    class _InvalidDateLine:
        def __getitem__(self, index: int) -> float:
            raise IndexError(index)

    invalid_data = _Data(0.0)
    invalid_data.datetime = _InvalidDateLine()
    assert FactorStrategy._current_feed_time(invalid_data) is None
    assert calls == [(2.0, {"tz": timezone.utc, "naive": False})]


def test_dense_memory_sink_matches_list_path_when_context_prices_are_unavailable() -> None:
    index, research, _ = _inputs()
    # The sink still has observed price buffers if mutable alignment metadata
    # becomes incomplete before finalization.
    sink = MemorySink()
    sink._enable_dense_product_index(2)
    for time, close in zip(index[1:3], (11.0, 12.0)):
        sink.on_point(time, "AAA", {"close_factor": close}, close - 0.5, close, True)

    from backtrader.research.sink import PanelContext

    panel_context = PanelContext(
        grid=research.grid,
        start=research.start,
        end=research.end,
        target_order=("AAA",),
        factor_order=("close_factor",),
        directions={"close_factor": 1},
        universe=pd.DataFrame({"AAA": [True, True]}, index=index[1:3]),
        groups=research.groups,
        prices_open=None,
        prices_close=None,
    )
    dense_panel = sink.finalize(panel_context)

    reference = MemorySink()
    for time, close in zip(index[1:3], (11.0, 12.0)):
        reference.on_point(time, "AAA", {"close_factor": close}, close - 0.5, close, True)
    reference_panel = reference.finalize(panel_context)

    pd.testing.assert_frame_equal(dense_panel.factors, reference_panel.factors)
    pd.testing.assert_frame_equal(dense_panel.prices_open, reference_panel.prices_open)
    pd.testing.assert_frame_equal(dense_panel.prices_close, reference_panel.prices_close)
    assert len(sink._times) == len(sink._assets) == 0
    assert len(sink._open) == len(sink._close) == 2
