"""Lazy Backtrader facade for the SDK-owned neutral market cohort API.

The implementation lives in :mod:`bt_api_py.market_cohort`. These direct
aliases preserve type identity for existing imports while keeping the SDK an
optional dependency until this module is requested.
"""

from bt_api_py.market_cohort import (
    MarketCohortLeg,
    MarketCohortNow,
    MarketCohortPolicy,
    MarketCohortReason,
    MarketCohortResult,
    MarketQuoteCohort,
    MarketQuoteCohortValidator,
    MarketQuoteEvidence,
    MarketQuoteValidation,
    validate_market_quote,
)

__all__ = [
    "MarketCohortLeg",
    "MarketCohortNow",
    "MarketCohortPolicy",
    "MarketCohortReason",
    "MarketCohortResult",
    "MarketQuoteCohort",
    "MarketQuoteCohortValidator",
    "MarketQuoteEvidence",
    "MarketQuoteValidation",
    "validate_market_quote",
]
