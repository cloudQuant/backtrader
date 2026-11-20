"""R71-124 regression coverage for Matplotlib and Plotly range slicing."""

from __future__ import annotations

import datetime

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg", force=True)
pytest.importorskip("plotly")
pandas = pytest.importorskip("pandas")

import backtrader as bt
from backtrader.plot import PlotlyPlot
from backtrader.plot import Plot as MatplotlibPlot


class _NoopStrategy(bt.Strategy):
    pass


class _HeadlessPlotlyPlot(PlotlyPlot):
    """Keep real Plotly rendering while suppressing browser display."""

    def show(self):
        pass


def _run_synthetic_strategy():
    dates = pandas.date_range("2024-01-01", periods=20, freq="D")
    closes = [100.0 + index for index in range(len(dates))]
    frame = pandas.DataFrame(
        {
            "Open": [value - 0.5 for value in closes],
            "High": [value + 1.0 for value in closes],
            "Low": [value - 1.0 for value in closes],
            "Close": closes,
            "Volume": [1000 + index for index in range(len(dates))],
            "OpenInterest": [0] * len(dates),
        },
        index=dates,
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="SYNTH")
    cerebro.addstrategy(_NoopStrategy)
    cerebro.run()
    return cerebro, dates.to_pydatetime(), closes


def _plot(cerebro, backend, start=None, end=None):
    if backend == "matplotlib":
        plotter = MatplotlibPlot()
        figures = cerebro.plot(
            plotter=plotter,
            backend="matplotlib",
            use="Agg",
            iplot=False,
            start=start,
            end=end,
        )
    else:
        plotter = _HeadlessPlotlyPlot(style="line", volume=False)
        figures = cerebro.plot(
            plotter=plotter,
            backend="plotly",
            iplot=False,
            start=start,
            end=end,
        )
    assert figures and figures[0]
    return plotter, figures[0][0]


def _selected_values(plotter, figure, backend):
    if backend == "matplotlib":
        return list(plotter.pinf.xreal), plotter.pinf

    trace = next((trace for trace in figure.data if trace.name == "SYNTH"), None)
    if trace is None:
        return [], None
    return list(trace.x), list(trace.y)


@pytest.mark.parametrize("backend", ("matplotlib", "plotly"))
@pytest.mark.parametrize(
    ("start", "end", "first", "last"),
    (
        (-5, None, 15, 20),
        (-1, -1, 19, 20),
        (-10, -5, 10, 16),
        (-100, None, 0, 20),
    ),
    ids=("last-five", "last-bar", "negative-bounds", "extreme-negative-start"),
)
def test_cerebro_plot_backends_normalize_negative_start(
    backend, start, end, first, last
):
    cerebro, dates, closes = _run_synthetic_strategy()

    plotter, figure = _plot(cerebro, backend, start=start, end=end)
    selected, details = _selected_values(plotter, figure, backend)

    if backend == "matplotlib":
        assert (details.pstart, details.pend, details.psize) == (
            first,
            last,
            last - first,
        )
        assert selected == pytest.approx(
            [bt.date2num(value) for value in dates[first:last]]
        )
    else:
        assert selected == list(dates[first:last])
        trace = next(trace for trace in figure.data if trace.name == "SYNTH")
        assert list(trace.y) == closes[first:last]


@pytest.mark.parametrize("backend", ("matplotlib", "plotly"))
@pytest.mark.parametrize(
    ("start", "end"),
    ((-5, -6), (0, -21), (0, -22), (30, None)),
    ids=(
        "empty-negative-window",
        "empty-at-zero",
        "extreme-negative-end",
        "start-after-data",
    ),
)
def test_cerebro_plot_backends_handle_empty_and_out_of_range_windows(
    backend, start, end
):
    cerebro, _, _ = _run_synthetic_strategy()

    plotter, figure = _plot(cerebro, backend, start=start, end=end)

    if backend == "matplotlib":
        assert plotter.pinf.psize == 0
        # LineBuffer.plot(size=0) reports from pstart to the buffer end, while
        # the actual requested window stays empty and draws no axes.
        assert plotter.pinf.xlen == max(0, 20 - plotter.pinf.pstart)
        assert not plotter.pinf.daxis
    else:
        assert not figure.data


@pytest.mark.parametrize("backend", ("matplotlib", "plotly"))
@pytest.mark.parametrize("boundary_kind", ("date", "datetime"))
def test_cerebro_plot_backends_preserve_date_start_and_end(
    backend, boundary_kind
):
    cerebro, dates, closes = _run_synthetic_strategy()
    first, last = 4, 12
    start_dt, end_dt = dates[first], dates[last]
    if boundary_kind == "date":
        start, end = start_dt.date(), end_dt.date()
    else:
        start, end = start_dt, end_dt

    plotter, figure = _plot(cerebro, backend, start=start, end=end)
    selected, details = _selected_values(plotter, figure, backend)

    if backend == "matplotlib":
        assert (details.pstart, details.pend, details.psize) == (
            first,
            last + 1,
            last + 1 - first,
        )
        assert selected == pytest.approx(
            [bt.date2num(value) for value in dates[first : last + 1]]
        )
    else:
        assert selected == list(dates[first : last + 1])
        trace = next(trace for trace in figure.data if trace.name == "SYNTH")
        assert list(trace.y) == closes[first : last + 1]


@pytest.mark.parametrize(
    ("fmt_x_ticks", "expected"),
    (("%Y", "2024"), ("", "")),
    ids=("custom-format", "empty-custom-format"),
)
def test_single_bar_matplotlib_tick_uses_custom_tick_format(fmt_x_ticks, expected):
    cerebro, _, _ = _run_synthetic_strategy()
    plotter = MatplotlibPlot(volume=False, fmt_x_ticks=fmt_x_ticks)

    figures = cerebro.plot(
        plotter=plotter,
        backend="matplotlib",
        use="Agg",
        iplot=False,
        start=-1,
        end=-1,
    )
    figure = figures[0][0]
    formatter_output = figure.axes[-1].xaxis.get_major_formatter()(0)

    assert formatter_output == expected
