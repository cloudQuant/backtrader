"""R71-053 chart-resource cleanup coverage for HTML and PDF reports."""

from pathlib import Path

import pytest

import backtrader.reports.reporter as reporter_module
from backtrader.reports.reporter import ReportGenerator


class _ControlledCharts:
    """Track a synthetic chart resource without depending on a plot backend."""

    def __init__(self, close_error=None):
        self.open_resources = [object()]
        self.close_calls = 0
        self.close_error = close_error

    def close_all(self):
        self.close_calls += 1
        self.open_resources.clear()
        if self.close_error is not None:
            raise self.close_error


class _ControlledPdfDocument:
    write_error = None

    def __init__(self, string):
        self.string = string

    def write_pdf(self, output_path):
        if type(self).write_error is not None:
            raise type(self).write_error
        Path(output_path).write_bytes(b"controlled pdf")


def _make_reporter(monkeypatch, charts=None):
    monkeypatch.setattr(reporter_module, "JINJA2_AVAILABLE", True)
    monkeypatch.setattr(reporter_module, "WEASYPRINT_AVAILABLE", True)
    monkeypatch.setattr(
        reporter_module, "WeasyHTML", _ControlledPdfDocument, raising=False
    )

    reporter = ReportGenerator(strategy=object())
    reporter.charts = charts if charts is not None else _ControlledCharts()
    reporter._build_context = lambda **kwargs: {"title": "controlled"}
    reporter._render_template = lambda context: "<html>controlled</html>"
    return reporter


@pytest.mark.parametrize(
    ("method", "filename"),
    (("generate_html", "report.html"), ("generate_pdf", "report.pdf")),
)
def test_report_generation_closes_chart_resources_on_success(
    monkeypatch, tmp_path, method, filename
):
    charts = _ControlledCharts()
    reporter = _make_reporter(monkeypatch, charts)
    output_path = tmp_path / filename

    result = getattr(reporter, method)(output_path)

    assert result == output_path
    assert output_path.is_file()
    assert charts.close_calls == 1
    assert charts.open_resources == []


def test_generate_html_closes_chart_resources_after_template_failure(monkeypatch, tmp_path):
    charts = _ControlledCharts()
    reporter = _make_reporter(monkeypatch, charts)
    template_error = ValueError("template rendering failed")

    def fail_render(context):
        raise template_error

    reporter._render_template = fail_render

    with pytest.raises(ValueError, match="template rendering failed") as caught:
        reporter.generate_html(tmp_path / "report.html")

    assert caught.value is template_error
    assert charts.close_calls == 1
    assert charts.open_resources == []


def test_generate_html_closes_chart_resources_after_file_open_failure(
    monkeypatch, tmp_path
):
    charts = _ControlledCharts()
    reporter = _make_reporter(monkeypatch, charts)
    disk_error = PermissionError("report output is not writable")

    def fail_open(*args, **kwargs):
        raise disk_error

    monkeypatch.setattr(reporter_module, "open", fail_open, raising=False)

    with pytest.raises(PermissionError, match="not writable") as caught:
        reporter.generate_html(tmp_path / "report.html")

    assert caught.value is disk_error
    assert charts.close_calls == 1
    assert charts.open_resources == []


def test_generate_pdf_closes_chart_resources_after_pdf_failure(monkeypatch, tmp_path):
    charts = _ControlledCharts()
    reporter = _make_reporter(monkeypatch, charts)
    pdf_error = OSError("font resource unavailable")
    monkeypatch.setattr(_ControlledPdfDocument, "write_error", pdf_error)

    with pytest.raises(OSError, match="font resource unavailable") as caught:
        reporter.generate_pdf(tmp_path / "report.pdf")

    assert caught.value is pdf_error
    assert charts.close_calls == 1
    assert charts.open_resources == []


@pytest.mark.parametrize(
    ("method", "filename"),
    (("generate_html", "report.html"), ("generate_pdf", "report.pdf")),
)
def test_cleanup_failure_does_not_replace_report_generation_error(
    monkeypatch, tmp_path, method, filename
):
    primary_error = RuntimeError("original report failure")
    cleanup_error = RuntimeError("chart cleanup failure")
    charts = _ControlledCharts(close_error=cleanup_error)
    reporter = _make_reporter(monkeypatch, charts)
    if method == "generate_html":
        reporter._render_template = lambda context: (_ for _ in ()).throw(primary_error)
    else:
        monkeypatch.setattr(_ControlledPdfDocument, "write_error", primary_error)

    with pytest.raises(RuntimeError, match="original report failure") as caught:
        getattr(reporter, method)(tmp_path / filename)

    assert caught.value is primary_error
    assert charts.close_calls == 1
    assert charts.open_resources == []


@pytest.mark.parametrize(
    ("method", "filename"),
    (("generate_html", "report.html"), ("generate_pdf", "report.pdf")),
)
def test_cleanup_failure_surfaces_when_report_generation_succeeds(
    monkeypatch, tmp_path, method, filename
):
    cleanup_error = RuntimeError("chart cleanup failure")
    charts = _ControlledCharts(close_error=cleanup_error)
    reporter = _make_reporter(monkeypatch, charts)

    with pytest.raises(RuntimeError, match="chart cleanup failure") as caught:
        getattr(reporter, method)(tmp_path / filename)

    assert caught.value is cleanup_error
    assert charts.close_calls == 1
    assert charts.open_resources == []
