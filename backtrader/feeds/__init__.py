#!/usr/bin/env python
"""Data Feeds Module - Data source implementations.

This module provides data feed implementations for various data sources
including CSV files, pandas DataFrames, Yahoo Finance, Quandl, InfluxDB,
and the unified bt_api_py live interface.

Data Feed Types:
    - CSV Feeds: GenericCSVData, BTCSV, MT4CSV, SierraChart, VChartCSV
    - Pandas: PandasData for pandas DataFrame integration
    - Online: Yahoo Finance, Quandl, BtApiFeed
    - Utilities: Chainer, RollOver for data manipulation

Example:
    Loading data from a CSV file:
    >>> data = bt.feeds.GenericCSVData(
    ...     dataname='data.csv',
    ...     datetime=0,
    ...     open=1,
    ...     high=2,
    ...     low=3,
    ...     close=4,
    ...     volume=5
    ... )
    >>> cerebro.adddata(data)
"""

import importlib as _importlib
import os as _os

from .barrier import BarBarrierPolicy as BarBarrierPolicy
from .barrier import BarBarrierReason as BarBarrierReason
from .barrier import BarBarrierResult as BarBarrierResult
from .barrier import BarEvidence as BarEvidence
from .barrier import BarLeg as BarLeg
from .barrier import ClockMapping as ClockMapping
from .barrier import MinuteDecisionInput as MinuteDecisionInput
from .barrier import MultiLegBarBarrier as MultiLegBarBarrier
from .barrier import QuoteCutoffResult as QuoteCutoffResult
from .barrier import validate_quote_against_bar as validate_quote_against_bar
if _os.environ.get("BACKTRADER_LIGHT_IMPORT", "").strip().lower() not in {
    "1",
    "true",
    "yes",
    "on",
}:
    from .btcsv import *
    from .chainer import Chainer as Chainer
    from .cryptohftdata import CryptoHFTData as CryptoHFTData
    from .csvgeneric import *
    from .influxfeed import *
    from .mixed_channel import MixedChannel as MixedChannel
    from .mixed_channel import build_mixed_channel as build_mixed_channel
    from .mt4csv import *
    from .pandafeed import *
    from .quandl import *
    from .rollover import RollOver as RollOver
    from .sierrachart import *
    from .vchart import *
    from .vchartcsv import *
    from .vchartfile import VChartFile as VChartFile
    from .yahoo import *


_MARKET_FACTOR_SOURCE_EXPORTS = frozenset(
    {
        "MarketFactorSourceBinding",
        "MarketFactorSourceCalendar",
        "MarketFactorSourceError",
        "MarketFactorTickProjection",
        "project_market_factor_tick",
    }
)

_MARKET_COHORT_EXPORTS = frozenset(
    {
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
    }
)

_OPTIONAL_FEED_EXPORTS = frozenset({"BtApiFeed"})


def __getattr__(name):
    """Load optional SDK-backed market projections only when requested."""

    if name in _OPTIONAL_FEED_EXPORTS:
        module = _importlib.import_module(".btapifeed", __name__)
    elif name in _MARKET_COHORT_EXPORTS:
        module = _importlib.import_module("bt_api_py.market_cohort")
    elif name in _MARKET_FACTOR_SOURCE_EXPORTS:
        module = _importlib.import_module(".market_factor_source", __name__)
    else:
        raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(
        set(globals())
        | _MARKET_FACTOR_SOURCE_EXPORTS
        | _MARKET_COHORT_EXPORTS
        | _OPTIONAL_FEED_EXPORTS
    )


# Keep star imports of the package's already-eager public names compatible.
# Cohort attributes are resolved only if a caller explicitly imports them.
__all__ = sorted(
    {name for name in globals() if not name.startswith("_")}
    | _MARKET_COHORT_EXPORTS
    | _OPTIONAL_FEED_EXPORTS
)
