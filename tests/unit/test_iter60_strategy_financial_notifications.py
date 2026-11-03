"""Unsupported financial notifications have explicit unavailable values."""

import math

from backtrader.service.strategy_financial_notifications import strategy_financial_notification


def test_unavailable_values_are_not_zero_or_account_values():
    cash, value, fundvalue, shares, reasons = strategy_financial_notification()
    assert all(math.isnan(item) for item in (cash, value, fundvalue, shares))
    assert reasons == {
        "cash": "STRATEGY_CASH_CURRENCY_REQUIRED",
        "value": "STRATEGY_VALUE_UNAVAILABLE",
        "fundvalue": "STRATEGY_FUND_VALUE_UNAVAILABLE",
        "fundshares": "STRATEGY_FUND_SHARES_UNAVAILABLE",
    }
    reasons.clear()
    assert len(strategy_financial_notification()[-1]) == 4
