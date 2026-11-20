"""Report-chart resampling compatibility and periodicity tests (R71-022/052/170)."""

import pytest

pd = pytest.importorskip("pandas")

from backtrader.reports.charts import MATPLOTLIB_AVAILABLE, ReportChart


def _classification(dates):
    return ReportChart()._get_periodicity(dates)


def test_auto_periodicity_uses_hourly_cadence_for_short_hourly_series():
    """A four-hour, hourly-indexed span must not be expanded into minute bins."""
    dates = pd.date_range("2026-01-05 09:00", periods=5, freq="h")
    name, offset = _classification(dates)

    assert name == "Hourly"
    assert isinstance(offset, pd.offsets.Hour)


def test_auto_periodicity_uses_minute_cadence_for_short_minute_series():
    """Sub-hour input cadence remains minute-level over a short total span."""
    dates = pd.date_range("2026-01-05 09:00", periods=5, freq="min")
    name, offset = _classification(dates)

    assert name == "Per Minute"
    assert isinstance(offset, pd.offsets.Minute)


@pytest.mark.parametrize(
    "start, elapsed_hours",
    (("2026-03-08", 23), ("2026-11-01", 25)),
)
def test_auto_periodicity_keeps_new_york_local_daily_bars_across_dst(
    start, elapsed_hours
):
    """Local midnight-to-midnight daily bars remain daily across DST changes."""
    dates = pd.date_range(
        start, periods=2, freq="D", tz="America/New_York"
    )
    name, offset = _classification(dates)

    assert dates[0].date() != dates[1].date()
    assert dates[1] - dates[0] == pd.Timedelta(hours=elapsed_hours)
    assert name == "Daily"
    assert isinstance(offset, pd.offsets.Day)


@pytest.mark.parametrize(
    "start, periods, elapsed_hours",
    (("2026-03-08", 23, 22), ("2026-11-01", 25, 24)),
)
def test_auto_periodicity_keeps_same_local_dst_day_hourly(
    start, periods, elapsed_hours
):
    """Hourly cadence stays hourly across spring and fall local-day lengths."""
    dates = pd.date_range(
        start, periods=periods, freq="h", tz="America/New_York"
    )
    name, offset = _classification(dates)

    assert len(set(dates.date)) == 1
    assert dates[-1] - dates[0] == pd.Timedelta(hours=elapsed_hours)
    assert name == "Hourly"
    assert isinstance(offset, pd.offsets.Hour)


@pytest.mark.parametrize(
    "dates, expected_title, expected_bars",
    [
        (
            pd.date_range("2026-03-08", periods=2, freq="D", tz="America/New_York"),
            "Daily Returns",
            1,
        ),
        (
            pd.date_range("2026-11-01", periods=2, freq="D", tz="America/New_York"),
            "Daily Returns",
            1,
        ),
        (
            pd.date_range("2026-03-08", periods=23, freq="h", tz="America/New_York"),
            "Hourly Returns",
            22,
        ),
        (
            pd.date_range("2026-11-01", periods=25, freq="h", tz="America/New_York"),
            "Hourly Returns",
            24,
        ),
    ],
)
@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not available")
def test_dst_local_dates_resample_to_the_inferred_period(dates, expected_title, expected_bars):
    """Timezone-aware local series keep daily/hourly return counts across DST."""
    chart = ReportChart()
    values = [100.0 + index for index in range(len(dates))]

    fig = chart.plot_return_bars(dates, values)

    assert fig is not None
    assert fig.axes[0].get_title() == expected_title
    assert len(fig.axes[0].patches) == expected_bars
    chart.close_all()


def test_auto_periodicity_uses_fractional_days_for_multi_day_spans():
    """A three-day series is daily, not hourly because of integer-day truncation."""
    dates = pd.date_range("2026-01-05", periods=4, freq="D")
    name, offset = _classification(dates)

    assert name == "Daily"
    assert isinstance(offset, pd.offsets.Day)


def test_auto_periodicity_sorts_and_deduplicates_before_cadence_detection():
    """Duplicate and unordered timestamps do not distort the inferred interval."""
    dates = pd.DatetimeIndex(
        [
            "2026-01-05 11:00",
            "2026-01-05 09:00",
            "2026-01-05 09:00",
            "2026-01-05 10:00",
        ]
    )
    name, offset = _classification(dates)

    assert name == "Hourly"
    assert isinstance(offset, pd.offsets.Hour)


def test_auto_periodicity_uses_calendar_span_across_trading_gaps():
    """Weekend gaps in a short market sample use calendar span for daily bins."""
    dates = pd.DatetimeIndex(
        ["2026-01-09 15:00", "2026-01-12 09:00", "2026-01-12 10:00"]
    )
    name, offset = _classification(dates)

    assert name == "Daily"
    assert isinstance(offset, pd.offsets.Day)


def test_auto_weekly_offset_keeps_the_existing_sunday_boundary():
    """The offset form preserves the former ``W`` alias boundary."""
    dates = pd.date_range("2026-01-01", periods=60, freq="D")
    name, offset = _classification(dates)

    assert name == "Weekly"
    assert isinstance(offset, pd.offsets.Week)
    assert offset.weekday == 6


def test_empty_datetime_index_is_supported_and_has_a_daily_fallback():
    chart = ReportChart()
    name, offset = chart._get_periodicity(pd.DatetimeIndex([]))

    assert name == "Daily"
    assert isinstance(offset, pd.offsets.Day)
    if MATPLOTLIB_AVAILABLE:
        assert chart.plot_return_bars(pd.DatetimeIndex([]), []) is None


@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not available")
def test_auto_return_bars_use_the_inferred_hour_and_day_offsets():
    """Real pandas resampling produces one return per input interval/day."""
    chart = ReportChart()
    hourly_dates = pd.date_range("2026-01-05 09:00", periods=5, freq="h")
    daily_dates = pd.date_range("2026-01-05", periods=4, freq="D")

    hourly_fig = chart.plot_return_bars(hourly_dates, [100, 101, 102, 103, 104])
    daily_fig = chart.plot_return_bars(daily_dates, [100, 101, 102, 103])

    assert hourly_fig is not None
    assert hourly_fig.axes[0].get_title() == "Hourly Returns"
    assert len(hourly_fig.axes[0].patches) == 4
    assert daily_fig is not None
    assert daily_fig.axes[0].get_title() == "Daily Returns"
    assert len(daily_fig.axes[0].patches) == 3
    chart.close_all()


@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not available")
def test_auto_daily_returns_skip_empty_weekend_bins():
    """A Friday-to-Monday market gap contributes one observed return bar."""
    chart = ReportChart()
    dates = pd.DatetimeIndex(
        ["2026-01-09 15:00", "2026-01-12 09:00", "2026-01-12 10:00"]
    )

    fig = chart.plot_return_bars(dates, [100.0, 101.0, 102.0])

    assert fig is not None
    assert fig.axes[0].get_title() == "Daily Returns"
    assert len(fig.axes[0].patches) == 1
    assert fig.axes[0].patches[0].get_height() == pytest.approx(2.0)
    chart.close_all()


@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not available")
def test_auto_return_bars_accept_unsorted_duplicate_timestamps():
    """Real resampling tolerates duplicate observations in unsorted input."""
    chart = ReportChart()
    dates = pd.DatetimeIndex(
        [
            "2026-01-05 11:00",
            "2026-01-05 09:00",
            "2026-01-05 09:00",
            "2026-01-05 10:00",
        ]
    )

    fig = chart.plot_return_bars(dates, [103.0, 100.0, 102.0, 101.0])

    assert fig is not None
    assert fig.axes[0].get_title() == "Hourly Returns"
    assert len(fig.axes[0].patches) == 2
    chart.close_all()


@pytest.mark.parametrize(
    "period, dates, expected_title",
    [
        ("daily", pd.date_range("2026-01-01", periods=4, freq="D"), "Daily Returns"),
        (
            "weekly",
            pd.date_range("2026-01-05", periods=4, freq="W-MON"),
            "Weekly Returns",
        ),
        ("monthly", pd.date_range("2026-01-01", periods=4, freq="MS"), "Monthly Returns"),
        (
            "yearly",
            pd.DatetimeIndex([f"{year}-12-31" for year in range(2022, 2026)]),
            "Yearly Returns",
        ),
    ],
)
@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not available")
def test_explicit_period_names_and_plot_api_remain_compatible(period, dates, expected_title):
    """Existing explicit period names still select usable calendar offsets."""
    chart = ReportChart()
    values = [100.0 + index for index in range(len(dates))]

    fig = chart.plot_return_bars(dates, values, period=period)

    assert fig is not None
    assert fig.axes[0].get_title() == expected_title
    assert len(fig.axes[0].patches) > 0
    if period == "weekly":
        assert [tick.get_text() for tick in fig.axes[0].get_xticklabels()] == [
            "2026-01-18",
            "2026-01-25",
            "2026-02-01",
        ]
    chart.close_all()
