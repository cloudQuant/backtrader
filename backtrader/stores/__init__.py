#!/usr/bin/env python
"""Data Stores Module - External data source integrations.

This module provides store classes for connecting to external data sources
and brokers. Stores handle data retrieval and order execution for live trading.

Available Stores:
    - BtApiStore: Unified bt_api_py live store.
    - VChartFile: VChart file data source.

Example:
    Using a store with cerebro:
    >>> store = bt.stores.BtApiStore(provider='okx', api=my_bt_api_client)
    >>> data = store.getdata(dataname='BTC/USDT')
"""

import os as _os

from ._btapi_errors import LiveCompositionError as LiveCompositionError
from .base_btapi_store import BaseBtApiStore as BaseBtApiStore
from .btapi_composition import (
    GatewayReadinessProof as GatewayReadinessProof,
    LiveRunBinding as LiveRunBinding,
    ProcessModeFence as ProcessModeFence,
    create_direct_store as create_direct_store,
    create_gateway_store as create_gateway_store,
    create_live_store as create_live_store,
    validate_live_config as validate_live_config,
)
from .btapistore import BtApiMissingDependencyError as BtApiMissingDependencyError
from .btapistore import BtApiProviderNotImplementedError as BtApiProviderNotImplementedError
from .btapistore import BtApiStore as BtApiStore
from .direct_btapi_store import DirectBtApiStore as DirectBtApiStore
from .gateway_btapi_store import GatewayBtApiStore as GatewayBtApiStore

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables


if _os.environ.get("BACKTRADER_LIGHT_IMPORT", "").strip().lower() not in {
    "1",
    "true",
    "yes",
    "on",
}:
    from .vchartfile import VChartFile as VChartFile
