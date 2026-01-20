#!/usr/bin/env python
"""Brokers Module - Order execution and portfolio management.

This module provides broker implementations for order execution and
portfolio management. Brokers handle order routing, position tracking,
cash management, and trade history.

Available Brokers:
    - BackBroker: Built-in backtesting broker.
    - IBBroker: Interactive Brokers integration (optional).
    - OandaBroker: OANDA broker integration (optional).
    - VCBroker: VisualChart broker integration (optional).

Example:
    Setting the broker in cerebro:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.setbroker(bt.brokers.BackBroker())
"""

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

from backtrader.brokers.bbroker import BackBroker as BackBroker
from backtrader.brokers.bbroker import BrokerBack as BrokerBack

try:
    from backtrader.brokers.ibbroker import IBBroker as IBBroker
except ImportError:
    pass  # The user may not have ibpy installed

try:
    from backtrader.brokers.vcbroker import VCBroker as VCBroker
except ImportError:
    pass  # The user may not have something installed

try:
    from backtrader.brokers.oandabroker import OandaBroker as OandaBroker
except ImportError:
    pass  # The user may not have something installed
