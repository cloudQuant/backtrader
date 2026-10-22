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
