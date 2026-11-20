"""Regression tests for the automatic date formatter (R71-123)."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from dateutil import tz as dateutil_tz

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg", force=True)

import backtrader as bt
from backtrader.plot import Plot
from backtrader.plot import locator as locator_module
from backtrader.plot.formatters import MyDateFormatter
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.dates import AutoDateFormatter as MatplotlibAutoDateFormatter
from matplotlib.figure import Figure


class _NoopStrategy(bt.Strategy):
    """Strategy used for the repository's public NVDA sample data."""


def _run_nvda_strategy():
    data_path = Path(__file__).resolve().parents[2] / "datas" / "nvda-1999-2014.txt"
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(
        bt.feeds.GenericCSVData(
            dataname=str(data_path),
            dtformat="%Y-%m-%d",
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
            fromdate=datetime.datetime(2010, 1, 1),
            todate=datetime.datetime(2010, 6, 30),
        ),
        name="NVDA",
    )
    cerebro.addstrategy(_NoopStrategy)
    return cerebro.run()[0]


def _formatter_from_plotter(plotter):
    strategy = _run_nvda_strategy()
    figures = plotter.plot(strategy, iplot=False)
    expected_type = (
        locator_module.AutoDateFormatter
        if plotter.p.scheme.fmt_x_ticks is None
        else MyDateFormatter
    )
    formatters = [
        axis.xaxis.get_major_formatter()
        for figure in figures
        for axis in figure.axes
        if isinstance(axis.xaxis.get_major_formatter(), expected_type)
    ]
    assert formatters
    return strategy, plotter, formatters[0]


def _make_agg_auto_formatter(dates, tz=None):
    figure = Figure()
    FigureCanvasAgg(figure)
    axis = figure.add_subplot(111).xaxis
    locator = locator_module.AutoDateLocator(dates, tz=tz)
    axis.set_major_locator(locator)
    formatter = locator_module.AutoDateFormatter(dates, locator, tz=tz)
    axis.set_major_formatter(formatter)
    return formatter


def test_auto_date_formatter_returns_default_date_label_on_agg_plot():
    strategy, plotter, formatter = _formatter_from_plotter(Plot(fmt_x_ticks=None))
    index = 25
    datetime_value = bt.num2date(plotter.pinf.xreal[index])
    matplotlib_value = matplotlib.dates.date2num(datetime_value)
    expected = MatplotlibAutoDateFormatter.__call__(
        formatter, matplotlib_value, index
    )

    assert isinstance(formatter, locator_module.AutoDateFormatter)
    assert isinstance(formatter(index, index), str)
    assert formatter(index, index) == expected
    assert "<super:" not in formatter(index, index)
    assert "2010" in formatter(index, index)
    assert bt.num2date(plotter.pinf.xreal[index]) == datetime_value
    assert len(strategy.data) > index


def test_plot_custom_tick_format_keeps_custom_date_formatter():
    strategy, plotter, formatter = _formatter_from_plotter(
        Plot(fmt_x_ticks="%Y-%m")
    )
    index = 25
    expected = bt.num2date(plotter.pinf.xreal[index]).strftime("%Y-%m")

    assert isinstance(formatter, MyDateFormatter)
    assert formatter(index, index) == expected
    assert len(strategy.data) > index


def test_auto_date_formatter_clamps_negative_and_out_of_range_indices():
    strategy, plotter, formatter = _formatter_from_plotter(Plot(fmt_x_ticks=None))
    dates = plotter.pinf.xreal

    for requested_index, actual_index in (
        (-8, 0),
        (-len(dates) - 9, 0),
        (len(dates) + 9, len(dates) - 1),
    ):
        date_value = bt.num2date(dates[actual_index], tz=formatter._tz, naive=False)
        matplotlib_value = matplotlib.dates.date2num(date_value)
        expected = MatplotlibAutoDateFormatter.__call__(
            formatter, matplotlib_value, requested_index
        )

        assert formatter(requested_index, requested_index) == expected
    assert len(strategy.data) == len(dates)


def test_auto_date_formatter_preserves_timezone_conversion_from_data():
    strategy = _run_nvda_strategy()
    dates = list(strategy.lines.datetime.plot())
    utc_formatter = _make_agg_auto_formatter(dates)
    plus_two = datetime.timezone(datetime.timedelta(hours=2))
    local_formatter = _make_agg_auto_formatter(dates, tz=plus_two)
    for formatter in (utc_formatter, local_formatter):
        formatter.scaled = {}
        formatter.defaultfmt = "%Y-%m-%d %H:%M"
    index = 0
    local_datetime = bt.num2date(dates[index], tz=plus_two, naive=False)
    matplotlib_value = matplotlib.dates.date2num(local_datetime)
    expected = MatplotlibAutoDateFormatter.__call__(
        local_formatter, matplotlib_value, index
    )

    assert local_datetime.date() != bt.num2date(dates[index]).date()
    assert local_formatter(index, index) == expected
    assert local_formatter(index, index) != utc_formatter(index, index)


def test_auto_date_formatter_accepts_timezone_name_across_dst_transition():
    strategy = _run_nvda_strategy()
    dates = list(strategy.lines.datetime.plot())
    timezone_name = "America/New_York"
    timezone_object = dateutil_tz.gettz(timezone_name)
    assert timezone_object is not None

    string_formatter = _make_agg_auto_formatter(dates, tz=timezone_name)
    object_formatter = _make_agg_auto_formatter(dates, tz=timezone_object)
    for formatter in (string_formatter, object_formatter):
        formatter.scaled = {}
        formatter.defaultfmt = "%Y-%m-%d %H:%M %z"

    daily_dates = [bt.num2date(value).date() for value in dates]
    winter_index = daily_dates.index(datetime.date(2010, 3, 12))
    summer_index = daily_dates.index(datetime.date(2010, 3, 15))
    winter_label = string_formatter(winter_index, winter_index)
    summer_label = string_formatter(summer_index, summer_index)

    assert winter_label == object_formatter(winter_index, winter_index)
    assert summer_label == object_formatter(summer_index, summer_index)
    assert winter_label.endswith("-0500")
    assert summer_label.endswith("-0400")


def test_auto_date_formatter_with_empty_dates_returns_a_label_without_error():
    formatter = _make_agg_auto_formatter([])

    label = formatter(0, 0)

    assert isinstance(label, str)
    assert "<super:" not in label
