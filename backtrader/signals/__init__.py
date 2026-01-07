#!/usr/bin/env python
"""Signal Strategy Module - Trading signal based strategies.

This module provides signal-based strategy implementations where trading
decisions are driven by external signal sources rather than internal
logic. Signals can be generated from indicators, machine learning models,
or external data sources.

Key Classes:
    SignalStrategy: Base class for signal-based strategies.

Example:
    Creating a signal-based strategy:
    >>> class MySignalStrategy(bt.SignalStrategy):
    ...     def __init__(self):
    ...         self.signal_add(bt.SIGNAL_LONG, self.data.close)
"""
