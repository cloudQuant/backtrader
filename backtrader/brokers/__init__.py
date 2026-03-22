#!/usr/bin/env python
"""Brokers Module - Order execution and portfolio management.

This module provides broker implementations for order execution and
portfolio management. Brokers handle order routing, position tracking,
cash management, and trade history.

Available Brokers:
    - BackBroker: Built-in backtesting broker.
    - TickBroker: Tick and order book matching backtesting broker.
    - BtApiBroker: Unified bt_api_py live trading broker.

Example:
    Setting the broker in cerebro:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.setbroker(bt.brokers.BackBroker())
"""

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

from backtrader.brokers.bbroker import BackBroker as BackBroker
from backtrader.brokers.bbroker import BrokerBack as BrokerBack
from backtrader.brokers.mixbroker import MixBroker as MixBroker
from backtrader.brokers.tickbroker import TickBroker as TickBroker

from backtrader.brokers.btapibroker import BtApiBroker as BtApiBroker
