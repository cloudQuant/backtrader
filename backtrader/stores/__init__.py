#!/usr/bin/env python
"""Data Stores Module - External data source integrations.

This module provides store classes for connecting to external data sources
and brokers. Stores handle data retrieval and order execution for live trading.

Available Stores:
    - IBStore: Interactive Brokers integration (optional).
    - OandaStore: OANDA broker integration (optional).
    - VCStore: VisualChart integration (optional).
    - VChartFile: VChart file data source.

Example:
    Using a store with cerebro:
    >>> store = bt.stores.IBStore(port=7497)
    >>> data = store.getdata(dataname='AAPL')
"""

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

try:
    from .ibstore import IBStore as IBStore
except ImportError:
    pass  # The user may not have ibpy installed

try:
    from .vcstore import VCStore as VCStore
except ImportError:
    pass  # The user may not have a module installed

try:
    from .oandastore import OandaStore as OandaStore
except ImportError:
    pass  # The user may not have a module installed


from .vchartfile import VChartFile as VChartFile

# CCXT Store for cryptocurrency exchanges
try:
    from .ccxtstore import CCXTStore as CCXTStore
except ImportError:
    pass  # ccxt not installed

# CTP Store for China futures
try:
    from .ctpstore import CTPStore as CTPStore
except ImportError:
    pass  # ctpbee not installed

# Futu Store for HK/US/A-Share stocks
try:
    from .futustore import FutuStore as FutuStore
except ImportError:
    pass  # futu-api not installed
