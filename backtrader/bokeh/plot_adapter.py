#!/usr/bin/env python
"""Bokeh plotter adapter for Cerebro plotter contract."""

from __future__ import annotations

import bisect
import datetime
import sys

from .. import date2num
from ..utils.log_message import get_logger
from .app import BOKEH_AVAILABLE, PANDAS_AVAILABLE
from .app import BacktraderBokeh

try:
    from bokeh.io import output_notebook, output_file, save, show as bokeh_show
except ImportError:  # pragma: no cover - covered by feature flag above
    output_notebook = None  # type: ignore[assignment]
    output_file = None  # type: ignore[assignment]
    save = None  # type: ignore[assignment]
    bokeh_show = None  # type: ignore[assignment]

logger = get_logger(__name__)

_KNOWN_PLOTTER_KWARGS = {"style", "scheme", "use_default_tabs", "filter", "filename"}


class BokehPlot:
    """Adapter class exposing cerebro-compatible plotter contract.

    It keeps `BacktraderBokeh` API unchanged and maps the existing `cerebro.plot()`
    contract to a Plot/Plotly-compatible adapter interface:
    ``plot -> show -> savefig``.
    """

    def __init__(self, **kwargs):
        if not BOKEH_AVAILABLE:
            raise ImportError("bokeh is required for backend='bokeh'; pip install bokeh")
        if not PANDAS_AVAILABLE:
            raise ImportError("pandas is required for backend='bokeh'; pip install pandas")

        self._notebook_notified = False
        self._iplot = True
        self._filename = None
        self._models = []
        self._app_kwargs = {}

        unknown_kwargs = [k for k in kwargs if k not in _KNOWN_PLOTTER_KWARGS]
        if unknown_kwargs:
            logger.warning(
                "Ignoring unsupported BacktraderBokeh kwargs for adapter: %s",
                ", ".join(sorted(unknown_kwargs)),
            )

        for key, value in kwargs.items():
            if key == "filename":
                self._filename = value
            elif key in _KNOWN_PLOTTER_KWARGS:
                self._app_kwargs[key] = value

        self._app = BacktraderBokeh(**self._app_kwargs)

    def plot(
        self,
        strategy,
        figid=0,
        numfigs=1,
        iplot=True,
        start=None,
        end=None,
        use=None,
        **kwargs,
    ):
        """Collect a strategy figure for deferred rendering.

        Args:
            strategy: Strategy instance
            figid: Unused in adapter, kept for compatibility.
            numfigs: Reserved for compatibility.
            iplot: Notebook display preference.
            start: Start index or datetime for slicing.
            end: End index or datetime for slicing.
            use: Unused, matplotlib-only option kept for compatibility.

        Returns:
            Empty list, reserved for plotter contract consistency.
        """
        self._iplot = iplot

        if use is not None:
            logger.warning("bokeh backend ignores use parameter from cerebro.plot()")
        if numfigs is not None and numfigs != 1:
            logger.warning(
                "bokeh backend uses one tab chart stack; numfigs=%s will be ignored",
                numfigs,
            )

        if kwargs:
            logger.warning("Unsupported plot() kwargs ignored: %s", ", ".join(sorted(kwargs)))

        _ = iplot  # keep signature compatibility; actual display is deferred to show()

        if strategy is None:
            return []

        start_i, end_i = self._resolve_range(strategy, start, end)
        self._app.create_figurepage(strategy, filldata=True, start=start_i, end=end_i)
        return []

    def show(self):
        """Build deferred models and render them.

        Returns:
            List of bokeh models.
        """
        # build_full_model (not build_model) so the extra tabs
        # (Performance/Analyzer/Metadata/Config/Log/Source) are included,
        # matching BacktraderBokeh.plot() - this is bokeh's value-add over a
        # bare charts panel.
        model = self._app.build_full_model()
        if model is None:
            return []

        if self._iplot and self._should_use_notebook_output():
            output_notebook()  # type: ignore[call-arg]

        if bokeh_show is not None and self._iplot:
            bokeh_show(model)

        if self._filename is not None:
            self.savefig(model, self._filename)

        self._models.append(model)
        return [model]

    def savefig(self, fig, filename, **kwargs):
        """Save a bokeh model to disk.

        Args:
            fig: Bokeh model
            filename: HTML file path
            **kwargs: Unused compatibility args
        """
        if output_file is None or save is None:
            raise ImportError("bokeh is required for backend='bokeh'; pip install bokeh")

        output_file(filename)
        save(fig)

    def _should_use_notebook_output(self):
        if self._notebook_notified:
            return False

        if "ipykernel" not in sys.modules:
            return False

        self._notebook_notified = True
        return output_notebook is not None

    def _resolve_range(self, strategy, start, end):
        if strategy is None:
            return 0, None

        dtime = strategy.lines.datetime.plot()
        total = len(dtime)
        if total == 0:
            return 0, 0

        start_i = self._resolve_index(dtime, start, 0)
        end_i = self._resolve_index(dtime, end, total, is_end=True)
        return start_i, end_i

    def _resolve_index(self, dtline, value, default, is_end=False):
        if value is None:
            return default

        if isinstance(value, (datetime.date, datetime.datetime)):
            return (
                bisect.bisect_right(dtline, date2num(value))
                if is_end
                else bisect.bisect_left(dtline, date2num(value))
            )

        if isinstance(value, (int, float)):
            value = int(value)
            if value < 0:
                value = len(dtline) + value
            if is_end and value < 0:
                value = len(dtline) + 1 + value
            return max(0, value)

        try:
            return bisect.bisect_left(dtline, value)
        except TypeError:
            if is_end:
                try:
                    return bisect.bisect_right(dtline, value)
                except TypeError:
                    return default
            return bisect.bisect_left(dtline, value)
