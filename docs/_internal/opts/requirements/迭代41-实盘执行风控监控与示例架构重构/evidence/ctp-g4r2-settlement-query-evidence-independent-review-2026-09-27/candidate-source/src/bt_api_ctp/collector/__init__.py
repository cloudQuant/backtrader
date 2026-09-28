"""Exchange-agnostic tick collection framework.

Public API:
    protocols   - InstrumentSpec / TickRecord / provider, subscriber,
                  handler and normalizer contracts
    engine      - CollectionConfig / TickCollectionEngine orchestrator
    buffer      - TickBuffer bounded per-instrument buffer
    sink        - ParquetSink / SinkReport / TICK_ARROW_SCHEMA
    shard       - ShardConfig / select_instruments / validate_shards
    schedule    - TradingCalendar / NIGHT_CLOSE_TIERS
    cli         - main() command-line entry point

No exchange-specific type is imported here; concrete implementations live in
the venue packages (for example ``bt_api_ctp.collector_ctp``).
"""

from __future__ import annotations

from bt_api_ctp.collector.buffer import TickBuffer
from bt_api_ctp.collector.engine import CollectionConfig, TickCollectionEngine
from bt_api_ctp.collector.protocols import (
    DEFAULT_ASSET_TYPES,
    EXCHANGES,
    InstrumentProvider,
    InstrumentSpec,
    MarketDataSubscriber,
    TickHandler,
    TickNormalizer,
    TickRecord,
)
from bt_api_ctp.collector.schedule import NIGHT_CLOSE_TIERS, TradingCalendar
from bt_api_ctp.collector.shard import ShardConfig, ShardValidationReport, validate_shards
from bt_api_ctp.collector.sink import (
    TICK_ARROW_SCHEMA,
    InstrumentReport,
    ParquetSink,
    SinkReport,
)

__all__ = [
    "DEFAULT_ASSET_TYPES",
    "EXCHANGES",
    "NIGHT_CLOSE_TIERS",
    "TICK_ARROW_SCHEMA",
    "CollectionConfig",
    "InstrumentProvider",
    "InstrumentReport",
    "InstrumentSpec",
    "MarketDataSubscriber",
    "ParquetSink",
    "ShardConfig",
    "ShardValidationReport",
    "SinkReport",
    "TickBuffer",
    "TickCollectionEngine",
    "TickHandler",
    "TickNormalizer",
    "TickRecord",
    "TradingCalendar",
    "validate_shards",
]
