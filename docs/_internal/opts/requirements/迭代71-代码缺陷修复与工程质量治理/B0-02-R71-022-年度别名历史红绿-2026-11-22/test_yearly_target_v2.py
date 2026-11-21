"""R71-022: list input reaches yearly resampling on real pandas 2.0."""
import datetime as dt

import pytest

pytest.importorskip("pandas")
pytest.importorskip("matplotlib")
import backtrader.reports.charts as charts


@pytest.mark.parametrize("period", ["yearly", "auto"])
def test_year_end_returns_are_drawn_on_supported_pandas(period, monkeypatch):
    dates = [dt.datetime(year, 12, 31) for year in range(2018, 2026)]
    values = [100.0 * (1.1 ** i) for i in range(len(dates))]
    messages = []

    def record_warning(message, *args, **kwargs):
        messages.append(message % args if args else message)

    monkeypatch.setattr(charts.logger, "warning", record_warning)
    chart = charts.ReportChart()
    figure = chart.plot_return_bars(dates, values, period=period)
    assert figure is not None, "chart was suppressed; warnings=%r" % messages
    assert figure.axes[0].get_title() == "Yearly Returns"
    assert len(figure.axes[0].patches) == 7
    assert [bar.get_height() for bar in figure.axes[0].patches] == pytest.approx([10.0] * 7)
    chart.close_all()
