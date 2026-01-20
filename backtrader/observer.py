#!/usr/bin/env python
"""Observer Module - Strategy monitoring and data collection.

This module provides the Observer base class for monitoring strategy
execution and collecting data during backtesting. Observers track metrics
like cash, value, drawdown, and trade statistics.

Observers are similar to indicators but are used primarily for monitoring
and recording strategy state rather than generating trading signals.

Key Classes:
    Observer: Base class for all observers.

Observers receive the same notifications as strategies:
    - prenext/nextstart/next: Called during each bar
    - start/stop: Called at the beginning and end of backtesting

Example:
    Creating a custom observer:
    >>> class MyObserver(Observer):
    ...     lines = ('custom_metric',)
    ...
    ...     def next(self):
    ...         self.lines.custom_metric[0] = self.data.close[0] * 2
"""

from .lineiterator import LineIterator, ObserverBase, StrategyBase


# Observer class - refactored to not use metaclass
class Observer(ObserverBase):
    """Base class for monitoring strategy execution.

    Observers track and record strategy state during backtesting.
    They can track metrics like cash, value, drawdown, positions, etc.

    Attributes:
        csv: Whether to save observer data to CSV (default: True).
        plotinfo: Plotting configuration dictionary.

    Example:
        >>> observer = MyObserver()
        >>> cerebro.addobserver(observer)
    """

    # Set _stclock to False
    _stclock = False
    # Owned instance
    _OwnerCls = StrategyBase
    # Line type
    _ltype = LineIterator.ObsType
    # Whether to save to csv and other files
    csv = True
    # Plot settings options
    plotinfo = dict(plot=False, subplot=True)

    def __init__(self, *args, **kwargs):
        """
        Initialize Observer with functionality previously in MetaObserver.dopreinit.

        Note: __new__ removed - _analyzers initialization moved here.
        """
        # Initialize _analyzers list (moved from __new__)
        self._analyzers = list()  # keep children analyzers

        # Initialize parent first
        super().__init__(*args, **kwargs)

        # Handle _stclock functionality (previously in MetaObserver.dopreinit)
        if self._stclock:  # Change the clock if strategy wide observer
            self._clock = self._owner

    # An Observer is ideally always observing and that' why prenext calls next.
    # The behavior can be overriden by subclasses
    def prenext(self):
        """Process bars before minimum period is reached.

        By default, observers always process every bar by calling next()
        even during the prenext phase. Subclasses can override this behavior.

        Note:
            This default implementation calls next() to ensure observers
            track all bars from the beginning.
        """
        self.next()

    # Register analyzer
    def _register_analyzer(self, analyzer):
        self._analyzers.append(analyzer)

    def _start(self):
        # PERFORMANCE FIX: Ensure _owner is set before calling start()
        # This is a fallback for cases where findowner didn't find the strategy during __init__
        if not hasattr(self, "_owner") or self._owner is None:
            # Try to get owner from _parent (set by strategy when adding observer)
            if hasattr(self, "_parent") and self._parent is not None:
                self._owner = self._parent

        self.start()

    def start(self):
        """Called at the start of the backtesting run.

        This method can be overridden by subclasses to perform
        initialization at the start of strategy execution.
        """
