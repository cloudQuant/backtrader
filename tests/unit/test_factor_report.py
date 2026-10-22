"""Tests for the Backtrader adapter to fincore's bilingual factor report."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _require_fincore_report():
    module = pytest.importorskip("fincore.report.factor")
    if not hasattr(module, "write_factor_report"):
        pytest.skip("the installed fincore does not provide the factor HTML report")
    return module


def _dataset():
    _require_fincore_report()
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2024-01-01", periods=60, tz="UTC")
    assets = ["S%02d" % index for index in range(20)]
    prices = pd.DataFrame(
        100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, (len(dates), len(assets))), axis=0),
        index=dates,
        columns=assets,
    )
    index = pd.MultiIndex.from_product([dates, assets], names=("time", "asset"))
    factors = pd.DataFrame({"factor": rng.normal(size=len(index))}, index=index)
    grid = pd.DataFrame(
        {"open_time": dates - pd.Timedelta(hours=6)},
        index=pd.DatetimeIndex(dates, name="close_time"),
    )
    from backtrader.research import FactorPanel

    return FactorPanel(
        factors=factors,
        grid=grid,
        prices_open=prices,
        prices_close=prices,
        start=dates[0],
        end=dates[-1],
        target_order=tuple(assets),
        factor_order=("factor",),
        directions={"factor": 1},
    )


@pytest.mark.parametrize("language", ("zh", "en"))
def test_write_factor_report_uses_the_bilingual_fincore_report(tmp_path, language):
    from backtrader.research.factor_report import write_factor_report

    path = write_factor_report(
        _dataset(),
        "factor",
        tmp_path / ("report-%s.html" % language),
        periods=(1, 5),
        quantiles=3,
        language=language,
    )
    html = path.read_text(encoding="utf-8")
    assert '<html lang="%s">' % language in html
    assert "lang-switch" in html
    assert 'data-lang="zh"' in html and 'data-lang="en"' in html
    assert "信息系数（IC）时间序列" in html
    assert "Information Coefficient (IC) Time Series" in html
    assert "IC 统计" in html and "IC statistics" in html
    assert "echarts" in html.casefold()
    assert 'src="http' not in html and 'href="http' not in html
    assert "ic-chart" in html and "data-table" in html
    assert len(html) > 500_000


def test_write_factor_report_rejects_an_unknown_factor(tmp_path):
    from backtrader.research.factor_report import write_factor_report

    with pytest.raises(KeyError):
        write_factor_report(_dataset(), "missing", tmp_path / "report.html")


def test_write_factor_report_applies_each_direction_without_mutating_panel(monkeypatch, tmp_path):
    report_module = _require_fincore_report()
    from backtrader.research import FactorPanel
    from backtrader.research.factor_report import write_factor_report

    source = _dataset()
    factors = source.factors.copy(deep=True)
    factors["positive_factor"] = factors["factor"]
    panel = FactorPanel(
        factors=factors,
        grid=source.grid,
        prices_open=source.prices_open,
        prices_close=source.prices_close,
        start=source.start,
        end=source.end,
        target_order=source.target_order,
        factor_order=("factor", "positive_factor"),
        directions={"factor": -1, "positive_factor": 1},
    )
    original_factors = panel.factors.copy(deep=True)
    original_index = panel.factors.index
    original_attrs = panel.factors.attrs.copy()
    calls = []

    def capture_report(factor, prices, target, **kwargs):
        calls.append((factor.copy(deep=True), prices, kwargs))
        return target

    monkeypatch.setattr(report_module, "write_factor_report", capture_report)

    write_factor_report(panel, "factor", tmp_path / "negative.html")
    write_factor_report(panel, "positive_factor", tmp_path / "positive.html")

    expected_negative = source.factor_values("factor").mul(-1).rename("factor")
    expected_positive = source.factor_values("factor").rename("factor")
    assert calls[0][0].equals(expected_negative)
    assert calls[1][0].equals(expected_positive)
    assert calls[0][1] is panel.prices_open
    assert calls[1][1] is panel.prices_open
    assert calls[0][2]["next_open"] is True
    assert calls[1][2]["next_open"] is True
    assert panel.factors.equals(original_factors)
    assert panel.factors.index is original_index
    assert panel.factors.attrs == original_attrs


def test_write_factor_report_close_to_close_matches_raw_close_baseline(monkeypatch, tmp_path):
    report_module = _require_fincore_report()
    from backtrader.research.factor_report import write_factor_report

    panel = _dataset()
    panel.directions["factor"] = -1
    calls = []

    def capture_report(factor, prices, target, **kwargs):
        calls.append((factor.copy(deep=True), prices, kwargs))
        return target

    monkeypatch.setattr(report_module, "write_factor_report", capture_report)
    write_factor_report(
        panel,
        "factor",
        tmp_path / "close-report.html",
        label="close_to_close",
    )

    explicit_factor = panel.factor_values("factor").mul(-1).rename("factor")
    assert len(calls) == 1
    assert calls[0][0].equals(explicit_factor)
    assert calls[0][1] is panel.prices_close
    assert calls[0][2]["next_open"] is False


def test_write_factor_report_rejects_labels_without_panel_price_support():
    from backtrader.errors import ResearchConfigError
    from backtrader.research.factor_report import write_factor_report

    class MinimalPanel:
        factor_order = ("factor",)

    with pytest.raises(ResearchConfigError) as caught:
        write_factor_report(MinimalPanel(), "factor", "report.html", label="precomputed")

    assert caught.value.code == "INVALID_CONFIG"
    assert caught.value.report["field"] == "label"
