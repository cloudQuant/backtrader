"""Regression tests for Bokeh negative end slicing (R71-025)."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

pytest.importorskip("bokeh")
matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg", force=True)

import backtrader as bt
from backtrader.bokeh import BokehPlot
from backtrader.plot import Plot


class _NoopStrategy(bt.Strategy):
    """Strategy used to run the repository's real NVDA sample history."""


def _run_real_nvda_history():
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


@pytest.mark.parametrize("end", (-1, -5), ids=("last-bar", "last-five-bars"))
def test_bokeh_negative_end_matches_matplotlib_slice_on_real_nvda_data(end):
    strategy = _run_real_nvda_history()
    total = len(strategy.lines.datetime.plot())

    matplotlib_plotter = Plot()
    matplotlib_figures = matplotlib_plotter.plot(
        strategy, iplot=False, start=0, end=end
    )
    expected_end = max(0, total + 1 + end)

    assert matplotlib_figures
    assert matplotlib_plotter.pinf.pstart == 0
    assert matplotlib_plotter.pinf.pend == expected_end
    assert matplotlib_plotter.pinf.psize == expected_end

    bokeh_plotter = BokehPlot(style="bar")
    bokeh_plotter.plot(strategy, iplot=False, start=0, end=end)
    figurepage = bokeh_plotter._app.get_figurepage(0)

    assert figurepage is not None
    assert len(figurepage._data) == matplotlib_plotter.pinf.psize
    assert list(figurepage._data["close"]) == [
        float(value) for value in strategy.data.close.plotrange(0, expected_end)
    ]


def test_bokeh_negative_start_selects_last_bars_without_backend_equivalence_claim():
    strategy = _run_real_nvda_history()
    total = len(strategy.data)
    start = -5

    bokeh_plotter = BokehPlot(style="bar")
    bokeh_plotter.plot(strategy, iplot=False, start=start)
    figurepage = bokeh_plotter._app.get_figurepage(0)
    expected_start = total + start

    assert figurepage is not None
    assert len(figurepage._data) == 5
    assert list(figurepage._data["close"]) == [
        float(value) for value in strategy.data.close.plotrange(expected_start, total)
    ]


def test_bokeh_end_minus_n_minus_one_is_empty_slice_with_matplotlib_observation():
    strategy = _run_real_nvda_history()
    total = len(strategy.data)
    end = -(total + 1)

    matplotlib_plotter = Plot()
    matplotlib_plotter.plot(strategy, iplot=False, start=0, end=end)
    assert matplotlib_plotter.pinf.pend == 0
    assert matplotlib_plotter.pinf.psize == 0
    # LineBuffer.plot(size=0) means "use the full buffer"; this is a
    # Matplotlib renderer detail and is not equated with the Bokeh slice.
    assert matplotlib_plotter.pinf.xlen == total

    bokeh_plotter = BokehPlot(style="bar")
    bokeh_plotter.plot(strategy, iplot=False, start=0, end=end)
    figurepage = bokeh_plotter._app.get_figurepage(0)

    assert figurepage is not None
    assert figurepage._data.empty


def test_bokeh_end_minus_n_minus_two_matches_matplotlib_slice_on_real_history():
    strategy = _run_real_nvda_history()
    total = len(strategy.data)
    end = -(total + 2)

    matplotlib_plotter = Plot()
    matplotlib_plotter.plot(strategy, iplot=False, start=0, end=end)
    expected_end = matplotlib_plotter.pinf.pend
    assert expected_end == total - 1

    bokeh_plotter = BokehPlot(style="bar")
    bokeh_plotter.plot(strategy, iplot=False, start=0, end=end)
    figurepage = bokeh_plotter._app.get_figurepage(0)

    assert figurepage is not None
    assert len(figurepage._data) == expected_end
    assert list(figurepage._data["close"]) == [
        float(value) for value in strategy.data.close.plotrange(0, expected_end)
    ]


@pytest.mark.parametrize("end_kind", ("date", "datetime"))
def test_bokeh_date_and_datetime_end_match_matplotlib_on_real_nvda_data(end_kind):
    strategy = _run_real_nvda_history()
    dtime = strategy.lines.datetime.plot()
    boundary = bt.num2date(dtime[25])
    end = boundary.date() if end_kind == "date" else boundary

    matplotlib_plotter = Plot()
    matplotlib_plotter.plot(strategy, iplot=False, start=0, end=end)
    expected_end = matplotlib_plotter.pinf.pend

    bokeh_plotter = BokehPlot(style="bar")
    bokeh_plotter.plot(strategy, iplot=False, start=0, end=end)
    figurepage = bokeh_plotter._app.get_figurepage(0)

    assert figurepage is not None
    assert len(figurepage._data) == expected_end
    assert list(figurepage._data["close"]) == [
        float(value) for value in strategy.data.close.plotrange(0, expected_end)
    ]
