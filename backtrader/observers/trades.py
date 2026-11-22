#!/usr/bin/env python
"""Trades Observer Module - Trade tracking and PnL visualization.

This module provides the Trades observer for tracking completed trades
and plotting their profit/loss.

Classes:
    Trades: Observer that tracks trades and plots PnL.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addobserver(bt.observers.Trades)
"""

from ..lineseries import Lines
from ..observer import Observer

_DATA_TRADES_LINES_CACHE: dict = {}


def _get_data_trades_lines_class(count):
    """Return a cached Lines class declaring ``data0``..``data{count-1}``."""
    lines_cls = _DATA_TRADES_LINES_CACHE.get(count)
    if lines_cls is None:
        line_names = tuple(f"data{i}" for i in range(count))
        lines_cls = Lines._derive("lines", line_names, 0, (), linesoverride=True)
        _DATA_TRADES_LINES_CACHE[count] = lines_cls
    return lines_cls


# This class saves all trades and plots PnL when trade is closed
class Trades(Observer):
    """This observer keeps track of full trades and plots the PnL level achieved
    when a trade is closed.

    A trade is open when a position goes from 0 (or crossing over 0) to X and
    is then closed when it goes back to 0 (or crosses over 0 in the opposite
    direction)

    Params:
      - ``pnlcomm`` (def: ``True``)

        Show net/profit and loss, i.e.: after commission.If set to `False`,
        it will show the result of trades before commission
    """

    # Attributes
    _stclock = True
    # Two lines
    lines = ("pnlplus", "pnlminus")
    # Parameters
    params = {"pnlcomm": True}
    # Plot info when plotting
    plotinfo = {
        "plot": True,
        "subplot": True,
        "plotname": "Trades - Net Profit/Loss",
        "plotymargin": 0.10,
        "plothlines": [0.0],
    }
    # Line settings when plotting
    plotlines = {
        "pnlplus": {
            "_name": "Positive",
            "ls": "",
            "marker": "o",
            "color": "blue",
            "markersize": 8.0,
            "fillstyle": "full",
        },
        "pnlminus": {
            "_name": "Negative",
            "ls": "",
            "marker": "o",
            "color": "red",
            "markersize": 8.0,
            "fillstyle": "full",
        },
    }

    def __init__(self):
        """Initialize the Trades observer.

        Sets up tracking variables for trade statistics.
        """
        self.trades = 0

        self.trades_long = 0
        self.trades_short = 0

        self.trades_plus = 0
        self.trades_minus = 0

        self.trades_plus_gross = 0
        self.trades_minus_gross = 0

        self.trades_win = 0
        self.trades_win_max = 0
        self.trades_win_min = 0

        self.trades_loss = 0
        self.trades_loss_max = 0
        self.trades_loss_min = 0

        self.trades_length = 0
        self.trades_length_max = 0
        self.trades_length_min = 0

    def next(self):
        """Update trade statistics based on closed trades.

        Processes pending trades and updates PnL lines.
        """
        self.lines.pnlplus[0] = float("nan")
        self.lines.pnlminus[0] = float("nan")

        # For existing trades
        for trade in self._owner._tradespending:
            # If trade's data has no data, skip
            if trade.data not in self.ddatas:
                continue
            # If trade is not closed, skip
            if not trade.isclosed:
                continue
            # If closed, if trade's net profit exists, pnl equals net profit, otherwise pnl equals profit
            pnl = trade.pnlcomm if self.p.pnlcomm else trade.pnl
            # If pnl > 0, plot on pnlplus line, if < 0, plot on pnlminus line
            if pnl >= 0.0:
                self.lines.pnlplus[0] = pnl
            else:
                self.lines.pnlminus[0] = pnl


# DataTrades class - refactored to not use metaclass and dynamic class creation
class DataTrades(Observer):
    """
    Track closed-trade PnL in a dedicated line for each data feed.

    Declares ten default lines (``data0``..``data9``) on the class and
    dynamically expands the instance's ``Lines`` container when attached to a
    strategy with more than ten feeds, without using metaclasses. A custom
    subclass that overrides ``lines`` with a fixed smaller capacity still
    fails closed during construction instead of silently dropping feeds.
    """

    _stclock = True

    params = (("usenames", True),)

    plotinfo = {"plot": True, "subplot": True, "plothlines": [0.0], "plotymargin": 0.10}

    plotlines: dict = {}

    # Define a reasonable number of lines for common use cases
    # This replaces the dynamic line creation from the metaclass
    lines = (
        "data0",
        "data1",
        "data2",
        "data3",
        "data4",
        "data5",
        "data6",
        "data7",
        "data8",
        "data9",
    )

    def __init__(self, *args, **kwargs):
        """
        Initialize with standard line system
        """
        # Initialize parent first - this will set up the line system
        super().__init__(*args, **kwargs)

        # DataTrades observes all strategy feeds. Generic Observer setup may
        # use the strategy itself as a clock/data placeholder; it is not a
        # tradable feed and must not be used for trade/data matching.
        owner_datas = getattr(self._owner, "datas", None)
        if owner_datas is not None:
            self.datas = list(owner_datas)
            self.ddatas = dict.fromkeys(self.datas)

        feed_count = len(getattr(self, "datas", ()))
        max_datas = len(self.lines)
        if feed_count > max_datas:
            if getattr(type(self), "lines", None) is DataTrades.lines:
                self._expand_lines_for_feeds(feed_count)
                max_datas = len(self.lines)
            else:
                raise ValueError(
                    "DataTrades supports at most {} data feeds; got {}".format(
                        max_datas, feed_count
                    )
                )

        # Feed ids are assigned by each Cerebro instance and are not the
        # observer's line contract. Bind each exact feed object to its local
        # strategy-data slot instead of assuming ``data._id - 1``.
        self._data_line_indices = {
            id(data): index for index, data in enumerate(getattr(self, "datas", ()))
        }

        # Setup plotlines configuration after parent initialization
        self._setup_plotlines_simple()

    def _expand_lines_for_feeds(self, count):
        """Allocate a Lines instance sized for ``count`` feeds without metaclasses."""
        lines_cls = _get_data_trades_lines_class(count)
        new_lines = lines_cls()
        object.__setattr__(new_lines, "_owner_ref", self)
        strict_context = getattr(self, "_factor_strict_context", None)
        if strict_context is not None:
            object.__setattr__(new_lines, "_factor_strict_context", strict_context)
        ltype = getattr(type(self), "_ltype", None)
        minperiod = getattr(self, "_minperiod", 1)
        for line in new_lines:
            if hasattr(line, "_refresh_cached_line_flags"):
                line._refresh_cached_line_flags(owner=new_lines, ltype=ltype)
            if strict_context is not None:
                line._factor_strict_context = strict_context
            if minperiod > 1 and hasattr(line, "updateminperiod"):
                line.updateminperiod(minperiod)
        self.lines = new_lines

    def _setup_plotlines_simple(self):
        """Setup plotlines configuration using simple dictionary approach"""
        # Only set up plotlines if we have access to datas
        if not hasattr(self, "datas") or not self.datas:
            return

        if isinstance(self.plotlines, dict):
            self.plotlines = dict(self.plotlines)
        else:
            # ParamsMixin may convert the class dictionary to an object whose
            # mapping helper functions are instance attributes, not bound
            # methods. Copy its non-callable settings without invoking keys().
            self.plotlines = {
                name: value
                for name, value in vars(self.plotlines).items()
                if not name.startswith("_") and not callable(value)
            }

        # CRITICAL FIX: Access parameter properly through self.params or self.p
        try:
            use_names = getattr(self.params, "usenames", True)
        except AttributeError:
            try:
                use_names = getattr(self.p, "usenames", True)
            except AttributeError:
                use_names = True  # Default fallback

        # Create line names based on data
        if use_names:
            lnames = [getattr(x, "_name", f"data{i}") for i, x in enumerate(self.datas)]
        else:
            lnames = [f"data{x}" for x in range(len(self.datas))]

        markers = [
            "o",
            "v",
            "^",
            "<",
            ">",
            "1",
            "2",
            "3",
            "4",
            "8",
            "s",
            "p",
            "*",
            "h",
            "H",
            "+",
            "x",
            "D",
            "d",
        ]

        colors = [
            "b",
            "g",
            "r",
            "c",
            "m",
            "y",
            "k",
            "b",
            "g",
            "r",
            "c",
            "m",
            "y",
            "k",
            "b",
            "g",
            "r",
            "c",
            "m",
        ]

        # Base style for all markers
        basedict = {"ls": "", "markersize": 8.0, "fillstyle": "full"}

        # Create plotlines configuration using simple dict update
        for i in range(min(len(lnames), len(self.lines))):
            marker = markers[i % len(markers)]
            color = colors[i % len(colors)]
            plot_config = basedict.copy()
            plot_config.update(marker=marker, color=color)
            # Set plotline configuration by line alias
            line_name = getattr(self.lines, "_getlinealias", lambda x: f"data{x}")(i)
            self.plotlines[line_name] = plot_config

    def next(self):
        """Update data-specific trade PnL values.

        Records closed trade PnL for each data feed.
        """
        for i in range(len(self.lines)):
            self.lines[i][0] = float("nan")

        for trade in self._owner._tradespending:
            if trade.data not in self.ddatas:
                continue

            if not trade.isclosed:
                continue

            # Set pnl by this observer's local feed-to-line binding. The
            # strategy feed id is only an implementation detail of Cerebro.
            data_line_indices = self.__dict__.get("_data_line_indices")
            if data_line_indices is None:
                # Keep direct, manually constructed observer instances usable
                # by deriving the same identity map from their configured data.
                datas = self.__dict__.get("datas", self.__dict__.get("ddatas", ()))
                data_line_indices = {id(data): index for index, data in enumerate(datas)}
                self._data_line_indices = data_line_indices

            data_id = data_line_indices.get(id(trade.data))
            if data_id is not None:
                self.lines[data_id][0] = trade.pnl
