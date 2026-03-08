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

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

from .vchartfile import VChartFile as VChartFile
from .btapistore import BtApiStore as BtApiStore
from .btapistore import BtApiMissingDependencyError as BtApiMissingDependencyError
from .btapistore import BtApiProviderNotImplementedError as BtApiProviderNotImplementedError
