#!/usr/bin/env python
"""Integration tests for Bokeh plotting through `cerebro.plot()`.

This module focuses on the bokeh backend path added in
`docs/PLOT_BACKEND_UNIFICATION_ITERATION_PLAN.md`: `backend='bokeh'` is
selected by `cerebro.plot()` and `BokehPlot` follows the same contract as
`Plot` / `PlotlyPlot` (`plot -> show -> savefig`).
"""

from __future__ import annotations

import datetime
import os
import logging

import pytest

pytest.importorskip("bokeh")

import backtrader as bt
from backtrader.bokeh import BokehPlot
from backtrader.bokeh import plot_adapter


class BokehSmokeStrategy(bt.Strategy):
    """Minimal strategy for smoke testing bokeh plotting."""

    params = (("fast_period", 10), ("slow_period", 30))

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)

    def next(self):
        if not self.position and self.sma_fast > self.sma_slow:
            self.buy()
        elif self.position and self.sma_fast < self.sma_slow:
            self.close()


def _build_nasdaq_data(start=None, end=None):
    """Build a short sample feed used by bokeh integration tests."""
    data_path = os.path.join(os.path.dirname(__file__), "..", "datas", "nvda-1999-2014.txt")

    return bt.feeds.GenericCSVData(
        dataname=data_path,
        dtformat="%Y-%m-%d",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=start,
        todate=end,
    )


def _run_strategy(start=None, end=None):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(_build_nasdaq_data(start=start, end=end), name="NVDA")
    cerebro.addstrategy(BokehSmokeStrategy)
    return cerebro.run()


def _run_cerebro_with_bokeh(start=None, end=None):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(_build_nasdaq_data(start=start, end=end), name="NVDA")
    cerebro.addstrategy(BokehSmokeStrategy)
    cerebro.run()
    return cerebro


class TestBokehPlotter:
    """Test bokeh plotter behavior on cerebro and adapter contract."""

    def test_bokehplotter_import(self):
        plotter = BokehPlot(style="candle")
        assert plotter is not None

    def test_bokehplotter_plot_show_and_savefig(self, tmp_path):
        results = _run_strategy(
            start=datetime.datetime(2010, 1, 1), end=datetime.datetime(2010, 6, 30)
        )
        strategy = results[0]

        plotter = BokehPlot(style="candle")

        plotter.plot(strategy, iplot=False)
        figs = plotter.show()
        assert len(figs) == 1
        assert figs[0] is not None

        out = tmp_path / "bokeh_smoke_chart.html"
        plotter.savefig(figs[0], str(out))
        assert out.exists()

    def test_bokehplotter_start_end_slice(self):
        results = _run_strategy(
            start=datetime.datetime(2010, 1, 1), end=datetime.datetime(2010, 6, 30)
        )
        strategy = results[0]

        plotter = BokehPlot(style="bar")
        plotter.plot(strategy, iplot=False, start=5, end=30)
        plotter.show()

        dtime = strategy.lines.datetime.plot()
        expected_len = len(dtime[5:30])
        figpage = plotter._app.get_figurepage(0)
        assert figpage is not None
        assert figpage._data is not None
        assert len(figpage._data) == expected_len

    def test_bokehplotter_datetime_start_end_slice(self):
        results = _run_strategy(
            start=datetime.datetime(2010, 1, 1), end=datetime.datetime(2010, 6, 30)
        )
        strategy = results[0]
        dtime = strategy.lines.datetime.plot()

        plotter = BokehPlot(style="bar")
        plotter.plot(
            strategy,
            iplot=False,
            start=bt.num2date(dtime[5]),
            end=bt.num2date(dtime[30]),
        )
        plotter.show()

        figpage = plotter._app.get_figurepage(0)
        assert figpage is not None
        assert figpage._data is not None
        assert len(figpage._data) == len(dtime[5:31])

    def test_bokehplotter_plot_parameter_warnings(self, caplog):
        results = _run_strategy(
            start=datetime.datetime(2010, 1, 1), end=datetime.datetime(2010, 6, 30)
        )
        strategy = results[0]

        plotter = BokehPlot(style="candle")

        with caplog.at_level(logging.WARNING):
            plotter.plot(strategy, numfigs=2, use="some", unknown_arg=1, iplot=False)

        msg = " ".join(rec.getMessage() for rec in caplog.records)
        assert "numfigs=2 will be ignored" in msg
        assert "use parameter from cerebro.plot()" in msg
        assert "Unsupported plot() kwargs ignored: unknown_arg" in msg

    def test_bokehplotter_unknown_init_kwargs_warn(self, caplog):
        with caplog.at_level(logging.WARNING):
            BokehPlot(style="bar", unknown_flag=True)
        msg = " ".join(rec.getMessage() for rec in caplog.records)
        assert "Ignoring unsupported BacktraderBokeh kwargs for adapter" in msg

    def test_bokehplotter_missing_bokeh_dependency(self, monkeypatch):
        monkeypatch.setattr(plot_adapter, "BOKEH_AVAILABLE", False)
        with pytest.raises(ImportError, match="bokeh is required for backend='bokeh'"):
            BokehPlot()

    def test_bokehplotter_missing_pandas_dependency(self, monkeypatch):
        monkeypatch.setattr(plot_adapter, "PANDAS_AVAILABLE", False)
        with pytest.raises(ImportError, match="pandas is required for backend='bokeh'"):
            BokehPlot()

    def test_cerebro_plot_bokeh_dispatch(self, tmp_path):
        cerebro = _run_cerebro_with_bokeh(
            start=datetime.datetime(2010, 1, 1),
            end=datetime.datetime(2010, 6, 30),
        )

        output = tmp_path / "cerebro_bokeh_chart.html"
        figs = cerebro.plot(backend="bokeh", style="candle", iplot=False, filename=str(output))

        # cerebro.plot() keeps contract returning list entries per strategy plot() call
        assert isinstance(figs, list)
        assert len(figs) == 1
        assert figs[0] == []
        assert output.exists()

    @pytest.mark.parametrize("style", ["candle", "bar", "line"])
    def test_bokehplotter_chart_styles(self, style, tmp_path):
        """candle / bar / line styles all render without error and save HTML."""
        results = _run_strategy(
            start=datetime.datetime(2010, 1, 1), end=datetime.datetime(2010, 6, 30)
        )
        strategy = results[0]

        plotter = BokehPlot(style=style)
        plotter.plot(strategy, iplot=False)
        figs = plotter.show()
        assert len(figs) == 1 and figs[0] is not None

        out = tmp_path / f"bokeh_{style}.html"
        plotter.savefig(figs[0], str(out))
        assert out.exists()

    def test_bokehplotter_multi_strategy(self):
        """Multiple strategies collapse into one Tabs with >=2 chart panels."""
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.adddata(
            _build_nasdaq_data(
                start=datetime.datetime(2010, 1, 1), end=datetime.datetime(2010, 6, 30)
            ),
            name="NVDA",
        )
        cerebro.addstrategy(BokehSmokeStrategy)
        cerebro.addstrategy(BokehSmokeStrategy)
        results = cerebro.run()
        # cerebro.run() may return [[s0, s1]] or [s0, s1]; normalize to a flat list.
        strategies = results[0] if isinstance(results[0], list) else results
        assert len(strategies) == 2

        plotter = BokehPlot(style="bar")
        for strat in strategies:
            plotter.plot(strat, iplot=False)
        figs = plotter.show()
        assert len(figs) == 1
        # one Charts panel per strategy -> at least 2 tabs in the single Tabs model
        assert len(figs[0].tabs) >= 2

    def test_bokehplotter_notebook_inline(self, monkeypatch):
        """In a notebook (ipykernel present) with iplot, output_notebook is used."""
        import sys
        import types

        monkeypatch.setitem(sys.modules, "ipykernel", types.ModuleType("ipykernel"))

        called = {"notebook": False, "show": False}
        monkeypatch.setattr(
            plot_adapter, "output_notebook", lambda: called.__setitem__("notebook", True)
        )
        monkeypatch.setattr(
            plot_adapter, "bokeh_show", lambda model: called.__setitem__("show", True)
        )

        results = _run_strategy(
            start=datetime.datetime(2010, 1, 1), end=datetime.datetime(2010, 6, 30)
        )
        strategy = results[0]

        plotter = BokehPlot(style="bar")
        plotter.plot(strategy, iplot=True)
        plotter.show()
        assert called["notebook"] is True
        assert called["show"] is True

    def test_cerebro_plot_default_bokeh_does_not_load_matplotlib(self, monkeypatch, tmp_path):
        """The default bokeh route must not trigger the matplotlib lazy-loader."""
        import backtrader.plot as plotmod

        load_count = {"n": 0}
        real_loader = plotmod._load_matplotlib_plotter

        def spy():
            load_count["n"] += 1
            return real_loader()

        monkeypatch.setattr(plotmod, "_load_matplotlib_plotter", spy)

        cerebro = _run_cerebro_with_bokeh(
            start=datetime.datetime(2010, 1, 1), end=datetime.datetime(2010, 6, 30)
        )
        cerebro.plot(style="bar", iplot=False, filename=str(tmp_path / "no_mpl.html"))
        # The default bokeh branch imports BokehPlot from backtrader.bokeh and
        # never touches backtrader.plot, so the matplotlib lazy-loader is not invoked.
        assert load_count["n"] == 0
