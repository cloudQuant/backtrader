#!/usr/bin/env python
"""
Bokeh Application Core Classes

Provides integration between Backtrader and Bokeh
"""

import logging
from collections import OrderedDict

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

BOKEH_AVAILABLE = False
Panel = None

try:
    from bokeh.layouts import gridplot
    from bokeh.models import ColumnDataSource, CrosshairTool, HoverTool
    from bokeh.plotting import figure

    BOKEH_AVAILABLE = True

    # Handle different Bokeh versions for Panel
    try:
        from bokeh.models import TabPanel as Panel
    except ImportError:
        try:
            from bokeh.models.widgets import Panel
        except ImportError:
            from bokeh.models import Panel
except ImportError:
    pass

from . import tabs as default_tabs  # noqa: E402
from .schemes import Tradimo  # noqa: E402

_logger = logging.getLogger(__name__)


class FigurePage:
    """Figure Page

    Manages a group of related charts and data sources.
    """

    def __init__(self, strategy=None):
        """Initialize a FigurePage.

        Args:
            strategy: Strategy instance associated with this figure page.
        """
        self.strategy = strategy
        self.figures = []
        self.cds = None  # ColumnDataSource
        self._data = None

    def set_cds_columns_from_df(self, df):
        """Set CDS columns from DataFrame.

        Args:
            df: pandas DataFrame
        """
        if not BOKEH_AVAILABLE or df is None:
            return

        if self.cds is None:
            self.cds = ColumnDataSource(df)
        else:
            self.cds.data = df.to_dict("list")

    def get_cds_streamdata_from_df(self, df):
        """Get stream data from DataFrame.

        Args:
            df: pandas DataFrame

        Returns:
            dict: Stream data dictionary
        """
        if df is None or df.empty:
            return {}
        return df.to_dict("list")

    def get_cds_patchdata_from_series(self, series):
        """Get patch data from Series.

        Args:
            series: pandas Series

        Returns:
            tuple: (patch_data, stream_data)
        """
        return {}, {}


class Figure:
    """Single Figure

    Wraps a Bokeh figure.
    """

    def __init__(self, scheme=None):
        """Initialize a Figure.

        Args:
            scheme: Theme/scheme instance for styling the figure.
        """
        self.scheme = scheme
        self.figure = None
        self.cds = None

    def get_cds_streamdata_from_df(self, df):
        """Get stream data from DataFrame."""
        if df is None or df.empty:
            return {}
        return df.to_dict("list")

    def get_cds_patchdata_from_series(self, series, fill_nan=None):
        """Get patch data from Series."""
        return {}, {}

    def fill_nan(self):
        """Return columns that need NaN filling."""
        return []


class BacktraderBokeh:
    """Backtrader Bokeh Application

    Provides the following features:
    - Create and manage figure pages
    - Generate Bokeh models
    - Data processing and formatting

    Args:
        style: Chart style, 'bar' or 'candle'
        scheme: Theme instance
        use_default_tabs: Whether to use default tabs
        filter: Data filter configuration

    Example:
        app = BacktraderBokeh(style='candle', scheme=Blackly())
        figid, figurepage = app.create_figurepage(strategy)
        panels = app.generate_model_panels()
    """

    params = (
        ("style", "bar"),
        ("scheme", None),
        ("use_default_tabs", True),
        ("filter", None),
    )

    def __init__(self, **kwargs):
        """Initialize BacktraderBokeh application.

        Args:
            **kwargs: Keyword arguments for configuration:
                - style: Chart style ('bar' or 'candle')
                - scheme: Theme instance for styling
                - use_default_tabs: Whether to use default tabs
                - filter: Data filter configuration
        """
        # Process parameters
        self.p = type("Params", (), {})()
        for name, default in self.params:
            setattr(self.p, name, kwargs.get(name, default))

        # Set theme
        self.scheme = self.p.scheme
        if self.scheme is None:
            self.scheme = Tradimo()

        # Figure page storage
        self._figurepages = OrderedDict()
        self._figid_counter = 0

        # Current filter settings
        self._filter = self.p.filter or {}

        # Tab list
        self.tabs = []
        if self.p.use_default_tabs:
            self.tabs = [
                default_tabs.PerformanceTab,
                default_tabs.AnalyzerTab,
                default_tabs.MetadataTab,
                default_tabs.ConfigTab,
                default_tabs.LogTab,
                default_tabs.SourceTab,
            ]

    def create_figurepage(self, strategy, filldata=True):
        """Create a figure page.

        Args:
            strategy: Strategy instance
            filldata: Whether to fill data

        Returns:
            tuple: (figid, figurepage)
        """
        figid = self._figid_counter
        self._figid_counter += 1

        figurepage = FigurePage(strategy)
        self._figurepages[figid] = figurepage

        if filldata:
            self._fill_figurepage(figurepage, strategy)

        return figid, figurepage

    def _fill_figurepage(self, figurepage, strategy):
        """Fill figure page with data.

        Args:
            figurepage: Figure page instance
            strategy: Strategy instance
        """
        if not BOKEH_AVAILABLE or not PANDAS_AVAILABLE:
            return

        if strategy is None or not hasattr(strategy, "datas") or not strategy.datas:
            return

        # Get the first data source
        data = strategy.datas[0]

        # Create DataFrame
        df_data = self._create_dataframe(data, strategy)

        if df_data is not None:
            # Add trade signal data
            df_data = self._add_trade_signals(df_data, strategy)

            figurepage._data = df_data
            figurepage.cds = ColumnDataSource(df_data)

            # Create main figure (price + trade signals)
            main_figure = self._create_main_figure(df_data, strategy)
            if main_figure is not None:
                figurepage.figures.append(main_figure)

            # Create equity curve figure
            equity_figure = self._create_equity_figure(df_data, strategy)
            if equity_figure is not None:
                figurepage.figures.append(equity_figure)

            # Create drawdown figure
            drawdown_figure = self._create_drawdown_figure(df_data, strategy)
            if drawdown_figure is not None:
                figurepage.figures.append(drawdown_figure)

    def _create_dataframe(self, data, strategy):
        """Create DataFrame from data source.

        Args:
            data: Data source
            strategy: Strategy instance

        Returns:
            pandas.DataFrame
        """
        if not PANDAS_AVAILABLE:
            return None

        length = len(data)
        if length == 0:
            return None

        df_dict = {
            "index": list(range(length)),
        }

        # Add datetime
        try:
            df_dict["datetime"] = [data.datetime.datetime(-length + i + 1) for i in range(length)]
        except Exception:
            df_dict["datetime"] = list(range(length))

        # Add OHLCV data
        for name in ["open", "high", "low", "close", "volume"]:
            if hasattr(data, name):
                line = getattr(data, name)
                try:
                    df_dict[name] = [line[-length + i + 1] for i in range(length)]
                except Exception:
                    df_dict[name] = [0] * length

        return pd.DataFrame(df_dict)

    def _add_trade_signals(self, df, strategy):
        """Add trade signal data to DataFrame.

        Args:
            df: DataFrame
            strategy: Strategy instance

        Returns:
            DataFrame: DataFrame with trade signals added
        """
        # Initialize trade signal columns
        df = df.copy()
        df["buy_signal"] = None
        df["sell_signal"] = None
        df["buy_price"] = None
        df["sell_price"] = None

        # Extract trade records from strategy
        if not hasattr(strategy, "_trades") and not hasattr(strategy, "trades"):
            # Try to get trade info from analyzer
            trade_analyzer = None
            for analyzer in getattr(strategy, "analyzers", []):
                if analyzer.__class__.__name__ == "TradeAnalyzer":
                    trade_analyzer = analyzer
                    break

            if trade_analyzer is None:
                return df

        # Extract trade signals from order history
        try:
            orders = getattr(strategy, "_orders", []) or getattr(strategy, "orders", [])
            for order in orders:
                if order.status == order.Completed:
                    exec_dt = order.executed.dt
                    exec_price = order.executed.price

                    # Convert backtrader date to datetime
                    from ..utils.date import num2date

                    try:
                        dt = num2date(exec_dt)
                    except Exception:
                        continue

                    # Find the corresponding DataFrame row
                    mask = df["datetime"] == dt
                    if mask.any():
                        idx = df[mask].index[0]
                        if order.isbuy():
                            df.loc[idx, "buy_signal"] = True
                            df.loc[idx, "buy_price"] = exec_price
                        else:
                            df.loc[idx, "sell_signal"] = True
                            df.loc[idx, "sell_price"] = exec_price
        except Exception:
            pass

        # Add equity curve data
        df = self._add_equity_data(df, strategy)

        return df

    def _add_equity_data(self, df, strategy):
        """Add equity curve data.

        Args:
            df: DataFrame
            strategy: Strategy instance

        Returns:
            DataFrame
        """
        length = len(df)

        # Get equity data from Broker observer
        equity_values = [None] * length

        if hasattr(strategy, "observers"):
            for obs in strategy.observers:
                if obs.__class__.__name__ == "Broker":
                    if hasattr(obs.lines, "value"):
                        value_line = obs.lines.value
                        obs_len = len(value_line)
                        for i in range(min(length, obs_len)):
                            idx = 1 - obs_len + i
                            try:
                                equity_values[i] = value_line[idx]
                            except Exception:
                                pass
                    break

        # If no Broker observer, try to calculate from TimeReturn analyzer
        if all(v is None for v in equity_values):
            time_return = None
            for analyzer in getattr(strategy, "analyzers", []):
                if analyzer.__class__.__name__ == "TimeReturn":
                    try:
                        time_return = analyzer.get_analysis()
                    except Exception:
                        pass
                    break

            if time_return:
                start_cash = 100000  # Default starting capital
                if hasattr(strategy, "broker"):
                    try:
                        start_cash = strategy.broker.startingcash
                    except Exception:
                        pass

                cumulative = start_cash
                sorted_returns = sorted(time_return.items())
                ret_idx = 0

                for i, row in df.iterrows():
                    if ret_idx < len(sorted_returns):
                        dt, ret = sorted_returns[ret_idx]
                        if row["datetime"].date() >= dt.date() if hasattr(dt, "date") else True:
                            cumulative = cumulative * (1 + ret)
                            ret_idx += 1
                    equity_values[i] = cumulative

        df["equity"] = equity_values

        # Calculate drawdown
        df["drawdown"] = None
        df["drawdown_pct"] = None

        max_equity = None
        for i, eq in enumerate(equity_values):
            if eq is not None:
                if max_equity is None or eq > max_equity:
                    max_equity = eq
                if max_equity > 0:
                    dd = max_equity - eq
                    dd_pct = (dd / max_equity) * 100
                    df.loc[i, "drawdown"] = dd
                    df.loc[i, "drawdown_pct"] = dd_pct

        return df

    def _create_main_figure(self, df, strategy=None):
        """Create main figure (price + trade signals).

        Args:
            df: DataFrame
            strategy: Strategy instance

        Returns:
            Figure instance
        """
        if not BOKEH_AVAILABLE:
            return None

        fig = Figure(self.scheme)

        # Create Bokeh figure
        fig.figure = figure(
            title="Price & Trade Signals",
            x_axis_type="datetime" if "datetime" in df.columns else "linear",
            height=self.scheme.plot_height,
            sizing_mode=self.scheme.plot_sizing_mode,
            tools="pan,wheel_zoom,box_zoom,reset,save",
            toolbar_location=self.scheme.toolbar_location,
        )

        # Apply theme style
        self._apply_scheme_to_figure(fig.figure)

        # Plot price data
        if self.p.style == "candle" and all(
            col in df.columns for col in ["open", "high", "low", "close"]
        ):
            self._plot_candlestick(fig, df)
        else:
            self._plot_line(fig, df)

        # Plot trade signals
        self._plot_trade_signals(fig, df)

        # Add crosshair
        crosshair = CrosshairTool(line_color=self.scheme.crosshair_line_color)
        fig.figure.add_tools(crosshair)

        # Add HoverTool
        hover = HoverTool(
            tooltips=[
                ("Date", "@datetime{%F}"),
                ("Open", "@open{0.2f}"),
                ("High", "@high{0.2f}"),
                ("Low", "@low{0.2f}"),
                ("Close", "@close{0.2f}"),
            ],
            formatters={"@datetime": "datetime"},
            mode="vline",
        )
        fig.figure.add_tools(hover)

        # Create data source
        fig.cds = ColumnDataSource(df)

        return fig

    def _plot_trade_signals(self, fig, df):
        """Plot trade signal markers.

        Args:
            fig: Figure instance
            df: DataFrame
        """
        x_col = "datetime" if "datetime" in df.columns else "index"

        # Plot buy signals (green up triangle)
        buy_df = df[df["buy_signal"]]
        if len(buy_df) > 0:
            fig.figure.triangle(
                buy_df[x_col],
                buy_df["buy_price"] if "buy_price" in buy_df.columns else buy_df["low"] * 0.98,
                size=12,
                color="#00ff00",
                alpha=0.8,
                legend_label="Buy",
            )

        # Plot sell signals (red down triangle)
        sell_df = df[df["sell_signal"]]
        if len(sell_df) > 0:
            fig.figure.inverted_triangle(
                sell_df[x_col],
                (
                    sell_df["sell_price"]
                    if "sell_price" in sell_df.columns
                    else sell_df["high"] * 1.02
                ),
                size=12,
                color="#ff0000",
                alpha=0.8,
                legend_label="Sell",
            )

        # Configure legend
        if len(buy_df) > 0 or len(sell_df) > 0:
            fig.figure.legend.location = "top_left"
            fig.figure.legend.click_policy = "hide"

    def _create_equity_figure(self, df, strategy):
        """Create equity curve figure.

        Args:
            df: DataFrame
            strategy: Strategy instance

        Returns:
            Figure instance
        """
        if not BOKEH_AVAILABLE:
            return None

        if "equity" not in df.columns or df["equity"].isna().all():
            return None

        fig = Figure(self.scheme)

        # Create Bokeh figure
        fig.figure = figure(
            title="Equity Curve",
            x_axis_type="datetime" if "datetime" in df.columns else "linear",
            height=int(self.scheme.plot_height * 0.6),
            sizing_mode=self.scheme.plot_sizing_mode,
            tools="pan,wheel_zoom,box_zoom,reset,save",
            toolbar_location=self.scheme.toolbar_location,
        )

        # Apply theme style
        self._apply_scheme_to_figure(fig.figure)

        x_col = "datetime" if "datetime" in df.columns else "index"

        # Plot equity curve
        equity_df = df[df["equity"].notna()]
        if len(equity_df) > 0:
            fig.figure.line(
                equity_df[x_col],
                equity_df["equity"],
                line_width=2,
                color="#2196F3",
                legend_label="Equity",
            )

            # Fill area

            ColumnDataSource(
                data={
                    "x": equity_df[x_col].tolist(),
                    "y": equity_df["equity"].tolist(),
                    "lower": [equity_df["equity"].min()] * len(equity_df),
                }
            )

        # Add crosshair
        crosshair = CrosshairTool(line_color=self.scheme.crosshair_line_color)
        fig.figure.add_tools(crosshair)

        fig.figure.legend.location = "top_left"

        return fig

    def _create_drawdown_figure(self, df, strategy):
        """Create drawdown figure.

        Args:
            df: DataFrame
            strategy: Strategy instance

        Returns:
            Figure instance
        """
        if not BOKEH_AVAILABLE:
            return None

        if "drawdown_pct" not in df.columns or df["drawdown_pct"].isna().all():
            return None

        fig = Figure(self.scheme)

        # Create Bokeh figure
        fig.figure = figure(
            title="Drawdown (%)",
            x_axis_type="datetime" if "datetime" in df.columns else "linear",
            height=int(self.scheme.plot_height * 0.5),
            sizing_mode=self.scheme.plot_sizing_mode,
            tools="pan,wheel_zoom,box_zoom,reset,save",
            toolbar_location=self.scheme.toolbar_location,
        )

        # Apply theme style
        self._apply_scheme_to_figure(fig.figure)

        x_col = "datetime" if "datetime" in df.columns else "index"

        # Plot drawdown curve
        dd_df = df[df["drawdown_pct"].notna()]
        if len(dd_df) > 0:
            # Use negative values to display as decline on chart
            fig.figure.varea(
                x=dd_df[x_col],
                y1=0,
                y2=-dd_df["drawdown_pct"],
                fill_color="#f44336",
                fill_alpha=0.5,
                legend_label="Drawdown",
            )

            fig.figure.line(dd_df[x_col], -dd_df["drawdown_pct"], line_width=1, color="#d32f2f")

        # Add crosshair
        crosshair = CrosshairTool(line_color=self.scheme.crosshair_line_color)
        fig.figure.add_tools(crosshair)

        fig.figure.legend.location = "bottom_left"
        fig.figure.y_range.flipped = False

        return fig

    def _apply_scheme_to_figure(self, fig):
        """Apply theme style to figure.

        Args:
            fig: Bokeh figure
        """
        fig.background_fill_color = self.scheme.background_fill
        fig.border_fill_color = self.scheme.border_fill

        fig.xgrid.grid_line_color = self.scheme.grid_line_color
        fig.ygrid.grid_line_color = self.scheme.grid_line_color

        fig.xaxis.axis_line_color = self.scheme.axis_line_color
        fig.yaxis.axis_line_color = self.scheme.axis_line_color

        fig.xaxis.major_tick_line_color = self.scheme.tick_line_color
        fig.yaxis.major_tick_line_color = self.scheme.tick_line_color

        fig.xaxis.axis_label_text_color = self.scheme.axis_label_text_color
        fig.yaxis.axis_label_text_color = self.scheme.axis_label_text_color

        fig.title.text_color = self.scheme.plot_title_text_color

    def _plot_candlestick(self, fig, df):
        """Plot candlestick chart.

        Args:
            fig: Figure instance
            df: DataFrame
        """
        if "datetime" not in df.columns:
            return

        # Calculate up/down
        df = df.copy()
        df["is_up"] = df["close"] >= df["open"]

        # Separate up and down data
        up = df[df["is_up"]]
        down = df[~df["is_up"]]

        # Calculate candle width
        width = 0.5 * 24 * 60 * 60 * 1000  # Half day in milliseconds

        # Plot up candles
        if len(up) > 0:
            fig.figure.segment(
                up["datetime"], up["high"], up["datetime"], up["low"], color=self.scheme.barup_wick
            )
            fig.figure.vbar(
                up["datetime"],
                width,
                up["open"],
                up["close"],
                fill_color=self.scheme.barup,
                line_color=self.scheme.barup_outline,
            )

        # Plot down candles
        if len(down) > 0:
            fig.figure.segment(
                down["datetime"],
                down["high"],
                down["datetime"],
                down["low"],
                color=self.scheme.bardown_wick,
            )
            fig.figure.vbar(
                down["datetime"],
                width,
                down["open"],
                down["close"],
                fill_color=self.scheme.bardown,
                line_color=self.scheme.bardown_outline,
            )

    def _plot_line(self, fig, df):
        """Plot line chart.

        Args:
            fig: Figure instance
            df: DataFrame
        """
        x_col = "datetime" if "datetime" in df.columns else "index"

        if "close" in df.columns:
            fig.figure.line(
                df[x_col], df["close"], line_width=self.scheme.line_width, color=self.scheme.barup
            )

    def get_figurepage(self, figid):
        """Get figure page.

        Args:
            figid: Figure page ID

        Returns:
            FigurePage instance or None
        """
        return self._figurepages.get(figid)

    def get_last_idx(self, figid):
        """Get last data index of figure page.

        Args:
            figid: Figure page ID

        Returns:
            int: Last index
        """
        figurepage = self.get_figurepage(figid)
        if figurepage is None or figurepage._data is None:
            return -1

        if "index" in figurepage._data.columns:
            return figurepage._data["index"].iloc[-1]
        return len(figurepage._data) - 1

    def generate_data(
        self, figid=None, start=None, end=None, back=None, preserveidx=False, fill_gaps=False
    ):
        """Generate chart data.

        Args:
            figid: Figure page ID
            start: Start index
            end: End index
            back: Number of bars to look back
            preserveidx: Whether to preserve original index
            fill_gaps: Whether to fill gaps

        Returns:
            pandas.DataFrame
        """
        if not PANDAS_AVAILABLE:
            return None

        figurepage = self.get_figurepage(figid) if figid is not None else None

        if figurepage is None or figurepage._data is None:
            return pd.DataFrame()

        df = figurepage._data.copy()

        # Apply range limits
        if back is not None:
            if end is not None:
                start_idx = max(0, end - back + 1)
                df = df.iloc[start_idx : end + 1]
            else:
                df = df.tail(back)
        elif start is not None:
            if "index" in df.columns:
                df = df[df["index"] > start]
            else:
                df = df.iloc[start:]

        if not preserveidx:
            df = df.reset_index(drop=True)

        return df

    def update_figurepage(self, filter=None):
        """Update figure page.

        Args:
            filter: Filter configuration
        """
        if filter is not None:
            self._filter = filter

    def generate_model_panels(self):
        """Generate model panels.

        Returns:
            list: Panel list
        """
        if not BOKEH_AVAILABLE:
            return []

        panels = []

        for figid, figurepage in self._figurepages.items():
            # Create chart panel
            if figurepage.figures:
                figures = [fig.figure for fig in figurepage.figures if fig.figure is not None]
                if figures:
                    grid = gridplot(
                        [[fig] for fig in figures], sizing_mode=self.scheme.plot_sizing_mode
                    )
                    panel = Panel(child=grid, title="Charts")
                    panels.append(panel)

        return panels

    def plot(self, strategy=None, show=True, filename=None):
        """Bindto strategy and generate static chart.

        Args:
            strategy: Strategy instance
            show: Whether to show chart
            filename: Save filename

        Returns:
            Bokeh model or None
        """
        if not BOKEH_AVAILABLE:
            _logger.error("Bokeh is not available")
            return None

        if strategy is None:
            _logger.warning("No strategy provided")
            return None

        # Create figure page
        figid, figurepage = self.create_figurepage(strategy, filldata=True)

        # Generate panels
        panels = self.generate_model_panels()

        # Add tabs
        for tab_class in self.tabs:
            tab = tab_class(self, figurepage, None)
            if tab.is_useable():
                panels.append(tab.get_panel())

        if not panels:
            _logger.warning("No panels generated")
            return None

        from bokeh.models import Tabs

        model = Tabs(tabs=[p for p in panels if p is not None])

        if show:
            from bokeh.io import show as bokeh_show

            bokeh_show(model)

        if filename:
            from bokeh.io import output_file, save

            output_file(filename)
            save(model)

        return model
