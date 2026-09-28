"""Post-close data cleaning for the CTP tick pipeline.

The :mod:`bt_api_ctp.collector` package writes one tick tree per shard host
(``<data_root>/<trading_day>/<exchange>/<instrument>.parquet``).  This package
is the other half of that pipeline:

* ``pull``    -- copy every shard's tree onto the local machine;
* ``verify``  -- prove the copy matches the remote before anything is removed;
* ``merge``   -- deduplicate the copies into one authoritative local tree;
* ``delete``  -- reclaim remote disk, but only for directories already merged;
* ``kline``   -- synthesise 1/5/15 minute bars from the merged ticks.

Nothing here imports venue-specific code; CTP naming rules live in
:mod:`bt_api_ctp.cleaner_ctp`.
"""

from __future__ import annotations

__all__ = ["BACKENDS", "SUPPORTED_PERIODS", "CleanerConfig", "ConfigError", "HostConfig"]

from bt_api_ctp.cleaner.config import (
    BACKENDS,
    SUPPORTED_PERIODS,
    CleanerConfig,
    ConfigError,
    HostConfig,
)
