"""Default HTML report image attributes escape ordinary template values."""

import base64
from datetime import datetime, timedelta
from html.parser import HTMLParser

import pytest

pytest.importorskip("jinja2")

import backtrader as bt
from backtrader.reports.charts import MATPLOTLIB_AVAILABLE, PANDAS_AVAILABLE
from backtrader.reports.reporter import ReportGenerator


class _Feed(bt.feeds.DataBase):
    """Small local price series for a real Cerebro report."""

    def __init__(self):
        super().__init__()
        self._index = 0

    def _load(self):
        prices = (100.0, 101.0, 102.0, 101.0, 103.0, 104.0)
        if self._index == len(prices):
            return False
        value = prices[self._index]
        self.lines.datetime[0] = bt.date2num(datetime(2024, 1, 1) + timedelta(days=self._index))
        for line in (self.lines.open, self.lines.high, self.lines.low, self.lines.close):
            line[0] = value
        self.lines.volume[0] = 1
        self.lines.openinterest[0] = 0
        self._index += 1
        return True


class _Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.items.append(dict(attrs))


def _images(path):
    parser = _Images()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.items


@pytest.fixture(scope="module")
def strategy():
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(_Feed())
    cerebro.addstrategy(bt.Strategy)
    return cerebro.run()[0]


@pytest.mark.parametrize(
    ("field", "alt"),
    [
        ("equity_curve_img", "Equity Curve"),
        ("return_bars_img", "Return Bars"),
        ("drawdown_img", "Drawdown"),
    ],
)
def test_default_report_escapes_image_source_attribute(strategy, tmp_path, field, alt):
    payload = 'x" data-probe="injected&value'
    output = tmp_path / "report.html"
    ReportGenerator(strategy).generate_html(output, **{field: payload})
    image = next(image for image in _images(output) if image.get("alt") == alt)
    assert image == {"src": payload, "alt": alt}


@pytest.mark.skipif(
    not (MATPLOTLIB_AVAILABLE and PANDAS_AVAILABLE), reason="chart dependencies unavailable"
)
def test_default_report_keeps_generated_png_data_uris(strategy, tmp_path):
    output = tmp_path / "report.html"
    ReportGenerator(strategy).generate_html(output)
    images = _images(output)
    assert {image.get("alt") for image in images} == {
        "Equity Curve", "Return Bars", "Drawdown"
    }
    for image in images:
        prefix, encoded = image["src"].split(",", 1)
        assert prefix == "data:image/png;base64"
        assert base64.b64decode(encoded, validate=True).startswith(b"\x89PNG\r\n\x1a\n")
