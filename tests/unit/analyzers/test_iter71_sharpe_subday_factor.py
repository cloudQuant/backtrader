"""Regression coverage for sub-day Sharpe factor requirements (R71-172)."""

import math

import backtrader as bt
import pandas as pd
import pytest


# Explicit test convention only; production does not infer a market calendar.
_SUBDAY_FACTOR = 252 * 390


def _price_frame(timeframe, length=80):
    """Build a deterministic price path for the requested feed timeframe."""
    prices = [
        100.0 + 0.07 * index + 1.4 * math.sin(index * 0.47)
        + 0.35 * math.cos(index * 0.13)
        for index in range(length)
    ]
    frequency = "min" if timeframe == bt.TimeFrame.Minutes else "D"
    start = "2024-01-02 09:30" if frequency == "min" else "2024-01-01"
    return pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1.0 for price in prices],
            "low": [price - 1.0 for price in prices],
            "close": prices,
            "volume": [1000.0] * length,
            "openinterest": [0.0] * length,
        },
        index=pd.date_range(start, periods=length, freq=frequency),
    )


def _run_sharpe_cases(timeframe, compression, cases):
    """Run real Cerebro Sharpe analyzers alongside their TimeReturn series."""
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(
        bt.feeds.PandasData(
            dataname=_price_frame(timeframe),
            timeframe=timeframe,
            compression=1,
        )
    )

    class BuyOnce(bt.Strategy):
        def __init__(self):
            self.entered = False

        def next(self):
            if not self.entered:
                self.buy(size=10)
                self.entered = True

    cerebro.addstrategy(BuyOnce)
    cerebro.addanalyzer(
        bt.analyzers.TimeReturn,
        _name="returns",
        timeframe=timeframe,
        compression=compression,
    )
    for name, options in cases.items():
        analyzer_options = dict(options)
        analyzer_options.setdefault("timeframe", timeframe)
        analyzer_options.setdefault("compression", compression)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name=name, **analyzer_options)

    strategy = cerebro.run(runonce=True, preload=True)[0]
    returns = list(strategy.analyzers.returns.get_analysis().values())
    ratios = {
        name: strategy.analyzers.getbyname(name).get_analysis()["sharperatio"]
        for name in cases
    }
    return returns, ratios


def _reference_sharpe(returns, riskfreerate, factor, convertrate, annualize):
    """Calculate the documented factor/rate transformation independently."""
    values = list(returns)
    rate = riskfreerate
    if factor is not None:
        if convertrate:
            rate = (1.0 + rate) ** (1.0 / factor) - 1.0
        else:
            values = [(1.0 + value) ** factor - 1.0 for value in values]

    excess = [value - rate for value in values]
    mean = sum(excess) / len(excess)
    deviation = math.sqrt(
        sum((value - mean) ** 2 for value in excess) / len(excess)
    )
    ratio = mean / deviation
    if factor is not None and convertrate and annualize:
        ratio *= math.sqrt(factor)
    return ratio


def test_subday_without_factor_rejects_unavailable_annual_conversions():
    cases = {
        "annual_rate_to_period": {
            "riskfreerate": 0.01,
            "convertrate": True,
            "annualize": False,
        },
        "annual_rate_without_conversion": {
            "riskfreerate": 0.01,
            "convertrate": False,
            "annualize": False,
        },
        "annualize_zero_rate": {
            "riskfreerate": 0.0,
            "convertrate": True,
            "annualize": True,
        },
        "annualize_inferred_feed_timeframe": {
            "timeframe": None,
            "riskfreerate": 0.0,
            "convertrate": True,
            "annualize": True,
        },
        "annualize_returns_without_conversion_factor": {
            "riskfreerate": 0.0,
            "convertrate": False,
            "annualize": False,
        },
        "raw_period_zero_rate": {
            "riskfreerate": 0.0,
            "convertrate": True,
            "annualize": False,
        },
    }
    returns, ratios = _run_sharpe_cases(bt.TimeFrame.Minutes, 1, cases)

    assert len(returns) > 2
    assert all(math.isfinite(value) for value in returns)
    for name in cases:
        if name == "raw_period_zero_rate":
            expected = _reference_sharpe(
                returns,
                riskfreerate=0.0,
                factor=None,
                convertrate=True,
                annualize=False,
            )
            assert ratios[name] == pytest.approx(expected, rel=1e-12, abs=1e-12)
        else:
            assert ratios[name] is None


def test_subday_explicit_factor_keeps_rate_and_annualization_contract():
    cases = {
        "period_ratio": {
            "factor": _SUBDAY_FACTOR,
            "riskfreerate": 0.01,
            "convertrate": True,
            "annualize": False,
        },
        "annualized_ratio": {
            "factor": _SUBDAY_FACTOR,
            "riskfreerate": 0.01,
            "convertrate": True,
            "annualize": True,
        },
        "annualized_returns": {
            "factor": _SUBDAY_FACTOR,
            "riskfreerate": 0.01,
            "convertrate": False,
            "annualize": False,
        },
    }
    returns, ratios = _run_sharpe_cases(bt.TimeFrame.Minutes, 1, cases)

    for name, options in cases.items():
        expected = _reference_sharpe(
            returns,
            riskfreerate=options["riskfreerate"],
            factor=options["factor"],
            convertrate=options["convertrate"],
            annualize=options["annualize"],
        )
        assert ratios[name] == pytest.approx(expected, rel=1e-12, abs=1e-12)


def test_daily_default_custom_and_legacy_factor_precedence_are_unchanged():
    cases = {
        "daily_table_factor": {
            "riskfreerate": 0.01,
            "convertrate": True,
            "annualize": True,
        },
        "daily_custom_factor": {
            "factor": 360,
            "riskfreerate": 0.01,
            "convertrate": True,
            "annualize": True,
        },
        "daily_daysfactor_precedence": {
            "factor": 360,
            "daysfactor": 365,
            "riskfreerate": 0.01,
            "convertrate": True,
            "annualize": True,
        },
    }
    returns, ratios = _run_sharpe_cases(bt.TimeFrame.Days, 1, cases)
    factors = {
        "daily_table_factor": 252,
        "daily_custom_factor": 360,
        "daily_daysfactor_precedence": 365,
    }

    for name, factor in factors.items():
        expected = _reference_sharpe(
            returns,
            riskfreerate=0.01,
            factor=factor,
            convertrate=True,
            annualize=True,
        )
        assert ratios[name] == pytest.approx(expected, rel=1e-12, abs=1e-12)
