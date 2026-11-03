"""Strategy-scoped financial notifications without account fallback.

No SDK is imported by this module.  A future implementation may publish
amounts only from a single validated strategy snapshot with an explicit
currency and valuation policy; the current account-book API has neither a
currency for these callbacks nor a trusted strategy equity/fund valuation.
"""


def strategy_financial_notification():
    """Return unavailable financial values and finite diagnostic reasons.

    Unknown is represented by NaN, not zero or a broker account amount.
    Each invocation returns its own reason mapping for the caller to retain.
    """
    return (
        float("nan"),
        float("nan"),
        float("nan"),
        float("nan"),
        {
            "cash": "STRATEGY_CASH_CURRENCY_REQUIRED",
            "value": "STRATEGY_VALUE_UNAVAILABLE",
            "fundvalue": "STRATEGY_FUND_VALUE_UNAVAILABLE",
            "fundshares": "STRATEGY_FUND_SHARES_UNAVAILABLE",
        },
    )
