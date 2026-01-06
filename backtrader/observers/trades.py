#!/usr/bin/env python

from ..observer import Observer


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
    params = dict(pnlcomm=True)
    # Plot info when plotting
    plotinfo = dict(
        plot=True,
        subplot=True,
        plotname="Trades - Net Profit/Loss",
        plotymargin=0.10,
        plothlines=[0.0],
    )
    # Line settings when plotting
    plotlines = dict(
        pnlplus=dict(
            _name="Positive", ls="", marker="o", color="blue", markersize=8.0, fillstyle="full"
        ),
        pnlminus=dict(
            _name="Negative", ls="", marker="o", color="red", markersize=8.0, fillstyle="full"
        ),
    )

    # Initialize trades-related values
    def __init__(self):
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
    DataTrades observer that has been refactored to remove metaclass usage
    and dynamic class creation. Uses fixed line definitions for common cases.
    """

    _stclock = True

    params = (("usenames", True),)

    plotinfo = dict(plot=True, subplot=True, plothlines=[0.0], plotymargin=0.10)

    plotlines = dict()

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

        # Setup plotlines configuration after parent initialization
        self._setup_plotlines_simple()

    def _setup_plotlines_simple(self):
        """Setup plotlines configuration using simple dictionary approach"""
        # Only set up plotlines if we have access to datas
        if not hasattr(self, "datas") or not self.datas:
            return

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
        basedict = dict(ls="", markersize=8.0, fillstyle="full")

        # Create plotlines configuration using simple dict update
        for i, (lname, marker, color) in enumerate(zip(lnames, markers, colors)):
            if i < len(self.lines):  # Only configure lines that exist
                plot_config = basedict.copy()
                plot_config.update(marker=marker, color=color)
                # Set plotline configuration as attribute
                line_name = getattr(self.lines, "_getlinealias", lambda x: f"data{x}")(i)
                setattr(self.plotlines, line_name, plot_config)

    def next(self):
        for trade in self._owner._tradespending:
            if trade.data not in self.ddatas:
                continue

            if not trade.isclosed:
                continue

            # Set pnl using standard line system
            data_id = trade.data._id - 1
            if data_id >= 0 and data_id < len(self.lines):
                self.lines[data_id][0] = trade.pnl
