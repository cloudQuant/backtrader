"""HFT (high-frequency trading) broker components.

This package bundles the building blocks for the tick-level
backtesting engine:

* ``exchange``: maker/taker fill rules, queue models and
  :class:`OrderResult` containers.
* ``latency``: feed/order-entry/order-response latency models and
  the priority-queue-driven :class:`LatencyEngine`.
* ``matching_core``: order matching, fill reporting and cancel
  results.
* ``queue``: queue-position models used by
  :class:`backtrader.brokers.hft.exchange.QueueExchangeModel`.
* ``state`` / ``recorder``: per-symbol state tracking and bounded
  event recording.
* ``binance_bbo``: Binance BBO zip-pair conversion and latency
  generation helpers.
* ``examples``: strategy specs and quote builders used by the HFT
  example suite.

The ``__all__`` list below is the public surface of the package.
"""
from .binance_bbo import (
    BinanceBBOConversionResult,
    BinanceBBOLatencyResult,
    convert_binance_bbo_zip_pair,
    generate_latency_from_hft_events,
)
from .examples import (
    APTQuoteBuilder,
    BasisAlphaQuoteBuilder,
    GLFTQuoteBuilder,
    HFTExampleSpec,
    InputRequirement,
    OBIAlphaQuoteBuilder,
    PlainGridQuoteBuilder,
    QueueMarketMakingQuoteBuilder,
    StrategyConfig,
    build_input_manifest,
    build_quote_builder,
    get_hftbacktest_demo_example_specs,
    get_hftbacktest_example_spec,
    get_hftbacktest_example_specs,
)
from .exchange import ExchangeModel, FillRole, OrderResult, QueueExchangeModel, SimpleExchangeModel
from .latency import ConstantLatencyModel, IntpLatencyModel, LatencyEngine, LatencyModel
from .matching_core import CancelResult, FillReport, MatchingCore, MatchResult
from .queue import NoQueueModel, ProbQueueModel
from .recorder import Recorder
from .state import StateTracker

__all__ = [
    "LatencyModel",
    "ConstantLatencyModel",
    "IntpLatencyModel",
    "LatencyEngine",
    "FillRole",
    "OrderResult",
    "ExchangeModel",
    "SimpleExchangeModel",
    "QueueExchangeModel",
    "NoQueueModel",
    "ProbQueueModel",
    "Recorder",
    "FillReport",
    "MatchResult",
    "CancelResult",
    "MatchingCore",
    "BinanceBBOConversionResult",
    "BinanceBBOLatencyResult",
    "convert_binance_bbo_zip_pair",
    "generate_latency_from_hft_events",
    "StateTracker",
    "InputRequirement",
    "StrategyConfig",
    "HFTExampleSpec",
    "BasisAlphaQuoteBuilder",
    "APTQuoteBuilder",
    "GLFTQuoteBuilder",
    "PlainGridQuoteBuilder",
    "QueueMarketMakingQuoteBuilder",
    "OBIAlphaQuoteBuilder",
    "get_hftbacktest_demo_example_specs",
    "get_hftbacktest_example_specs",
    "get_hftbacktest_example_spec",
    "build_input_manifest",
    "build_quote_builder",
]
