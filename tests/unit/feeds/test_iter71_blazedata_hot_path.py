"""R71-063: BlazeData hot-path mappings retain their runtime semantics."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
import warnings

import backtrader as bt
from backtrader.linebuffer import LineBuffer

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from backtrader.feeds.blaze import BlazeData


START = dt.datetime(2026, 11, 21)


def _rows(count=3):
    return [
        (
            START + dt.timedelta(days=index),
            10.0 + index,
            20.0 + index,
            30.0 + index,
            5.0 + index,
            40.0 + index,
            6.0 + index,
            7.0 + index,
        )
        for index in range(count)
    ]


class _Capture(bt.Strategy):
    def __init__(self):
        self.rows = []

    def next(self):
        data = self.data
        self.rows.append(
            tuple(
                float(getattr(data, field)[0])
                for field in ("open", "high", "low", "close", "volume", "openinterest")
            )
        )


def _run(feed, strategy_cls=_Capture):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(feed)
    cerebro.addstrategy(strategy_cls)
    (strategy,) = cerebro.run(preload=False, runonce=False)
    return strategy


def test_cerebro_preserves_column_values_and_runtime_parameter_changes():
    class ChangeColumn(_Capture):
        def next(self):
            super().next()
            if len(self.rows) == 1:
                # ParameterAccessor is deliberately dynamic: the old loader
                # uses the new column for every subsequent row.
                self.data.p.close = 5

    feed = BlazeData(
        dataname=_rows(),
        datetime=0,
        open=1,
        high=3,
        low=4,
        close=2,
        volume=6,
        openinterest=7,
    )

    strategy = _run(feed, ChangeColumn)

    assert [row[3] for row in strategy.rows] == [20.0, 41.0, 42.0]
    assert [row[4] for row in strategy.rows] == [6.0, 7.0, 8.0]
    assert [row[0:3] for row in strategy.rows] == [
        (10.0, 30.0, 5.0),
        (11.0, 31.0, 6.0),
        (12.0, 32.0, 7.0),
    ]


def test_cerebro_resolves_current_line_buffer_after_start():
    class ReplaceCloseAfterStart(BlazeData):
        def start(self):
            super().start()
            close_index = self.lines.getlinealiases().index("close")
            self.lines.lines[close_index] = LineBuffer()

    feed = ReplaceCloseAfterStart(
        dataname=_rows(),
        datetime=0,
        open=1,
        high=3,
        low=4,
        close=2,
        volume=6,
        openinterest=7,
    )

    strategy = _run(feed)

    assert [row[3] for row in strategy.rows] == [20.0, 21.0, 22.0]
    assert [row[4] for row in strategy.rows] == [6.0, 7.0, 8.0]


def test_cerebro_keeps_datafields_list_live_after_start():
    class OmitVolume(_Capture):
        def next(self):
            super().next()
            if len(self.rows) == 1:
                self.data.datafields = list(self.data.datafields)
                self.data.datafields.remove("volume")

    feed = BlazeData(
        dataname=_rows(),
        datetime=0,
        open=1,
        high=3,
        low=4,
        close=2,
        volume=6,
        openinterest=7,
    )

    strategy = _run(feed, OmitVolume)

    assert strategy.rows[0][4] == 6.0
    # LineBuffer advances leave the omitted field at its default zero value.
    assert strategy.rows[1][4] == 0.0
    assert strategy.rows[2][4] == 0.0


def test_cerebro_skips_negative_column_indices_and_supports_restart():
    rows_a = _rows(3)
    feed = BlazeData(
        dataname=rows_a,
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=-1,
        openinterest=-1,
    )
    strategy = _run(feed)

    assert [row[:4] for row in strategy.rows] == [
        (10.0, 20.0, 30.0, 5.0),
        (11.0, 21.0, 31.0, 6.0),
        (12.0, 22.0, 32.0, 7.0),
    ]
    assert all(row[4] == 0.0 and row[5] == 0.0 for row in strategy.rows)

    # Restarting the same feed after changing params before start() uses new mapping.
    feed2 = BlazeData(
        dataname=_rows(2),
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=6,
        openinterest=7,
    )
    feed2.p.close = 5
    strategy2 = _run(feed2)
    assert [row[3] for row in strategy2.rows] == [40.0, 41.0]
    assert [row[4] for row in strategy2.rows] == [6.0, 7.0]


def test_tuple_datafields_and_direct_load_without_start():
    class TupleFieldsBlazeData(BlazeData):
        datafields = ("datetime", "open", "high", "low", "close", "volume", "openinterest")

    feed = TupleFieldsBlazeData(
        dataname=_rows(2),
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=6,
        openinterest=7,
    )
    feed._start()
    feed._rows = iter(_rows(2))
    feed._field_plan = None

    feed.forward()
    assert feed._load() is True
    assert float(feed.lines.close[0]) == 5.0
    assert float(feed.lines.volume[0]) == 6.0

    feed.forward()
    assert feed._load() is True
    assert float(feed.lines.close[0]) == 6.0
    assert float(feed.lines.volume[0]) == 7.0

    feed.forward()
    assert feed._load() is False


def test_nonstandard_params_and_shadowed_line_attribute_fall_back_safely():
    feed = BlazeData(dataname=_rows(2))
    feed._start()
    feed.start()

    # Replace params with a plain namespace (non-ParameterAccessor).
    feed.params = SimpleNamespace(
        datetime=0, open=1, high=2, low=3, close=5, volume=-1, openinterest=-1
    )
    feed.forward()
    assert feed._load() is True
    assert feed._field_plan is None
    assert float(feed.lines.close[0]) == 40.0

    # Replacing a line slot in lines.lines in place stays live on the fast path.
    feed2 = BlazeData(dataname=_rows(2))
    feed2._start()
    feed2.start()
    custom_close = LineBuffer()
    custom_close.forward()
    feed2.lines.lines[0] = custom_close
    feed2.forward()
    assert feed2._load() is True
    assert feed2._field_plan is not None
    assert float(custom_close[0]) == 5.0

    # Injecting a shadowing attribute directly into lines.__dict__ bypasses the fast path.
    feed3 = BlazeData(dataname=_rows(2))
    feed3._start()
    feed3.start()
    shadow_close = LineBuffer()
    shadow_close.forward()
    feed3.lines.__dict__["close"] = shadow_close
    feed3.forward()
    assert feed3._load() is True
    assert feed3._field_plan is None
    assert float(feed3.lines.close[0]) == 5.0


def test_removed_param_manager_key_falls_back_without_dropping_row():
    feed = BlazeData(
        dataname=_rows(2),
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=6,
        openinterest=7,
    )
    feed._start()
    feed.start()
    assert feed._field_plan is not None

    # Remove 'close' from _values (descriptor default is still 4) mid-stream.
    del feed.params._param_manager._values["close"]

    feed.forward()
    assert feed._load() is True
    assert float(feed.lines.open[0]) == 10.0
    assert float(feed.lines.close[0]) == 5.0
    assert float(feed.lines.volume[0]) == 6.0

    feed.forward()
    assert feed._load() is True
    assert float(feed.lines.open[0]) == 11.0
    assert float(feed.lines.close[0]) == 6.0

