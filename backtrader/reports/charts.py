#!/usr/bin/env python
"""
Report-specific chart generator.

Generates static charts for reports, distinct from interactive plotting.
"""

import base64
import io
import math

from ..utils.log_message import get_logger

logger = get_logger(__name__)

try:
    import matplotlib.dates as mdates
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


class ReportChart:
    """Report-specific chart generator.

    Generates static charts for reports, including:
    - Equity curve chart (with buy-and-hold comparison line)
    - Return bars chart (automatic period detection)
    - Drawdown area chart

    Attributes:
        figsize: Default chart size
        dpi: Chart resolution
    """

    def __init__(self, figsize=(10, 3), dpi=100):
        """Initialize the chart generator.

        Args:
            figsize: Chart size (width, height)
            dpi: Chart resolution
        """
        self.figsize = figsize
        self.dpi = dpi
        self._figures = []

    def _new_figure(self):
        """Create a static figure without depending on a GUI pyplot backend."""
        fig = Figure(figsize=self.figsize, dpi=self.dpi)
        FigureCanvasAgg(fig)
        return fig, fig.add_subplot(1, 1, 1)

    def plot_equity_curve(
        self, dates, values, benchmark_dates=None, benchmark_values=None, title="Equity Curve"
    ):
        """Plot equity curve chart.

        Args:
            dates: List of dates
            values: List of equity values
            benchmark_dates: List of benchmark dates (optional)
            benchmark_values: List of benchmark values (optional, e.g., buy-and-hold)
            title: Chart title

        Returns:
            matplotlib.figure.Figure or None
        """
        if not MATPLOTLIB_AVAILABLE or not dates or not values:
            return None

        fig, ax = self._new_figure()

        # Normalize to 100
        start_value = 1.0
        for value in values:
            if isinstance(value, (int, float)) and math.isfinite(value) and value != 0:
                start_value = value
                break

        normalized_values = []
        for value in values:
            if isinstance(value, (int, float)) and math.isfinite(value):
                normalized_values.append(100 * value / start_value)
            else:
                normalized_values.append(normalized_values[-1] if normalized_values else 100)

        # Plot equity curve
        ax.plot(dates, normalized_values, label="Strategy", linewidth=1.5, color="#3498DB")

        # Plot buy-and-hold comparison line
        if benchmark_dates and benchmark_values:
            sanitized_benchmark_values = []
            for value in benchmark_values:
                if isinstance(value, (int, float)) and math.isfinite(value):
                    sanitized_benchmark_values.append(value)
                else:
                    sanitized_benchmark_values.append(
                        sanitized_benchmark_values[-1] if sanitized_benchmark_values else 100
                    )
            ax.plot(
                benchmark_dates,
                sanitized_benchmark_values,
                label="Buy & Hold",
                linewidth=1,
                color="gray",
                linestyle="--",
            )

        # Plot baseline (100)
        ax.axhline(y=100, color="gray", linestyle=":", linewidth=0.8, alpha=0.7)

        ax.set_ylabel("Net Asset Value (start=100)")
        ax.set_title(title)
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)

        # Format x-axis dates
        if len(dates) > 0:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            fig.autofmt_xdate(rotation=45)

        fig.tight_layout()
        self._figures.append(fig)

        return fig

    def plot_return_bars(self, dates, values, period="auto", title=None):
        """Plot return bars chart.

        Args:
            dates: List of dates
            values: List of equity values
            period: Period ('auto', 'daily', 'weekly', 'monthly', 'yearly')
            title: Chart title

        Returns:
            matplotlib.figure.Figure or None
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return None

        if dates is None or values is None:
            return None

        try:
            dates = list(dates)
            values = list(values)
        except TypeError:
            return None

        if not dates or not values:
            return None

        # Create Series
        series = pd.Series(data=values, index=pd.to_datetime(dates))

        # Auto-detect period
        if period == "auto":
            period_name, period_code = self._get_periodicity(dates)
        else:
            period_map = {
                "daily": ("Daily", pd.offsets.Day()),
                "weekly": ("Weekly", pd.offsets.Week(weekday=6)),
                "monthly": ("Monthly", pd.offsets.MonthEnd()),
                "yearly": ("Yearly", pd.offsets.YearEnd()),
            }
            period_selection = period_map.get(
                period, ("Daily", pd.offsets.Day())
            )
            period_name = period_selection[0]
            period_code = period_selection[1]

        # Resample and calculate returns
        try:
            # Empty calendar bins (notably weekends and exchange holidays) are
            # not observations; dropping them avoids synthetic zero-return bars.
            resampled = series.resample(period_code).last().dropna()
            returns = 100 * resampled.pct_change(fill_method=None).dropna()
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            logger.warning("Failed to resample returns with period %s: %s", period_code, e)
            return None

        prev_values = resampled.shift(1).reindex(returns.index)
        curr_values = resampled.reindex(returns.index)
        invalid_mask = (
            ~curr_values.map(lambda value: isinstance(value, (int, float)) and math.isfinite(value))
            | ~prev_values.map(
                lambda value: isinstance(value, (int, float)) and math.isfinite(value)
            )
            | prev_values.eq(0)
            | ~returns.map(lambda value: math.isfinite(value))
        )
        if invalid_mask.any():
            logger.debug(
                "Replacing %d non-finite return bar values with 0.0",
                int(invalid_mask.sum()),
            )
            returns = returns.mask(invalid_mask, 0.0)

        if len(returns) == 0:
            return None

        fig, ax = self._new_figure()

        # Set colors based on positive/negative values
        colors = ["green" if r > 0 else "red" for r in returns.values]

        # Plot bar chart
        x_labels = [
            d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in returns.index
        ]
        ax.bar(range(len(returns)), returns.values, color=colors, alpha=0.7)

        # Set x-axis labels
        if len(x_labels) <= 20:
            ax.set_xticks(range(len(returns)))
            ax.set_xticklabels(x_labels, rotation=45, ha="right")
        else:
            # Show only partial labels when too many
            step = len(x_labels) // 10
            ax.set_xticks(range(0, len(returns), step))
            ax.set_xticklabels(x_labels[::step], rotation=45, ha="right")

        ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
        ax.set_ylabel("Return (%)")
        ax.set_title(title or f"{period_name} Returns")
        ax.grid(True, alpha=0.3, axis="y")

        fig.tight_layout()
        self._figures.append(fig)

        return fig

    def plot_drawdown(self, dates, values, title="Drawdown"):
        """Plot drawdown area chart.

        Args:
            dates: List of dates
            values: List of equity values
            title: Chart title

        Returns:
            matplotlib.figure.Figure or None
        """
        if not MATPLOTLIB_AVAILABLE or not dates or not values:
            return None

        # Calculate drawdown
        running_max = 0.0
        for value in values:
            if isinstance(value, (int, float)) and math.isfinite(value):
                running_max = value
                break

        drawdowns: list = []

        for v in values:
            if isinstance(v, (int, float)) and math.isfinite(v):
                if v > running_max:
                    running_max = v
                dd = (v - running_max) / running_max * 100 if running_max != 0 else 0
            else:
                dd = drawdowns[-1] if drawdowns else 0
            drawdowns.append(dd)

        fig, ax = self._new_figure()

        # Plot drawdown area
        ax.fill_between(dates, drawdowns, 0, alpha=0.3, color="red", label="Drawdown")
        ax.plot(dates, drawdowns, color="red", linewidth=1)

        ax.set_ylabel("Drawdown (%)")
        ax.set_title(title)
        ax.grid(True, alpha=0.3)

        # Show maximum drawdown
        max_dd = min(drawdowns)
        max_dd_idx = drawdowns.index(max_dd)
        ax.annotate(
            f"Max: {max_dd:.2f}%",
            xy=(dates[max_dd_idx], max_dd),
            xytext=(10, 10),
            textcoords="offset points",
            fontsize=9,
            color="red",
        )

        # Format x-axis dates
        if len(dates) > 0:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            fig.autofmt_xdate(rotation=45)

        fig.tight_layout()
        self._figures.append(fig)

        return fig

    def _get_periodicity(self, dates):
        """Choose display bins from calendar span and observed cadence.

        Calendar spans choose yearly, monthly, or weekly bins; spans over five
        days use daily bins. For shorter spans, advancing local dates at a
        consistent local time or a near-daily median interval identifies daily
        data across DST changes. Otherwise, the median positive interval
        chooses hourly bins at one-hour cadence or coarser, with minute bins
        for faster data. Sorting and deduplicating makes the cadence estimate
        insensitive to input order and duplicate timestamps.

        Args:
            dates: List of dates

        Returns:
            tuple: (period name, period code)
        """
        if not PANDAS_AVAILABLE:
            return ("Daily", "D")

        try:
            dates = pd.DatetimeIndex(pd.to_datetime(dates))
            dates = dates[~dates.isna()].drop_duplicates().sort_values()
            if len(dates) < 2:
                return ("Daily", pd.offsets.Day())

            time_interval_days = (dates[-1] - dates[0]).total_seconds() / 86400.0

            if time_interval_days > 5 * 365.25:
                return ("Yearly", pd.offsets.YearEnd())
            if time_interval_days > 365.25:
                return ("Monthly", pd.offsets.MonthEnd())
            if time_interval_days > 50:
                return ("Weekly", pd.offsets.Week(weekday=6))
            if time_interval_days > 5.0:
                return ("Daily", pd.offsets.Day())

            intervals = dates.to_series().diff().dropna()
            intervals = intervals[intervals > pd.Timedelta(0)]
            median_interval = intervals.median() if not intervals.empty else pd.Timedelta(0)
            local_dates = dates.date
            local_dates_advance = any(
                current > previous for previous, current in zip(local_dates, local_dates[1:])
            )
            local_times = dates.strftime("%H:%M:%S.%f")
            same_local_time = len(set(local_times)) == 1
            if local_dates_advance and (
                same_local_time or median_interval >= pd.Timedelta(hours=20)
            ):
                return ("Daily", pd.offsets.Day())
            if median_interval >= pd.Timedelta(hours=1):
                return ("Hourly", pd.offsets.Hour())
            return ("Per Minute", pd.offsets.Minute())
        except (AttributeError, IndexError, TypeError, ValueError) as e:
            logger.warning("Failed to determine periodicity: %s", e)
            return ("Daily", pd.offsets.Day())

    def save_to_file(self, fig, filename, format="png"):
        """Save chart to file.

        Args:
            fig: matplotlib figure object
            filename: Output filename
            format: Image format ('png', 'jpg', 'svg', 'pdf')
        """
        if fig is None:
            return

        fig.savefig(filename, format=format, dpi=self.dpi, bbox_inches="tight")

    def to_base64(self, fig, format="png"):
        """Convert chart to base64 encoding.

        Args:
            fig: matplotlib figure object
            format: Image format

        Returns:
            str: base64 encoded image data
        """
        if fig is None:
            return ""

        buf = io.BytesIO()
        fig.savefig(buf, format=format, dpi=self.dpi, bbox_inches="tight")
        buf.seek(0)

        img_base64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()

        return f"data:image/{format};base64,{img_base64}"

    def close_all(self):
        """Close all charts and release memory."""
        if MATPLOTLIB_AVAILABLE:
            for fig in self._figures:
                fig.clear()
        self._figures = []
