#!/usr/bin/env python
"""TradeLogger Observer Module - Comprehensive trade and data logging.

This module provides the TradeLogger observer for recording order, trade,
position, and bar data (OHLCV + open interest + custom fields) during
backtesting. All logs are stored in accessible lists and populated in
real-time as each bar is processed.

Classes:
    TradeLogger: Observer that logs orders, trades, positions, and bar data.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addobserver(bt.observers.TradeLogger)
    >>> results = cerebro.run()
    >>> strat = results[0]
    >>> tl = strat.stats.tradelogger
    >>> print(tl.order_log)
    >>> print(tl.trade_log)
    >>> print(tl.position_log)
    >>> print(tl.data_log)
"""

from ..observer import Observer
from ..trade import Trade
from ..utils.date import num2date


class TradeLogger(Observer):
    """Observer that logs orders, trades, positions, and bar data.

    Records comprehensive information during backtesting in real-time:
    - **order_log**: Order events (ref, type, status, size, price, etc.)
    - **trade_log**: Trade events (ref, status, size, price, pnl, etc.)
    - **position_log**: Position snapshot per bar (size, price)
    - **data_log**: Bar data per bar (datetime, OHLCV, open interest,
      and any extra lines defined on the data feed)

    Logs are populated incrementally on each bar, so they are accessible
    during the run (e.g., from the strategy's next() method).

    Params:
      - ``log_orders`` (default: ``True``): Whether to log order events.
      - ``log_trades`` (default: ``True``): Whether to log trade events.
      - ``log_positions`` (default: ``True``): Whether to log position snapshots.
      - ``log_data`` (default: ``True``): Whether to log bar data.
      - ``extra_fields`` (default: ``None``): Additional field names to
        extract from the data feed lines beyond the standard OHLCV +
        open interest. If None, all extra lines on the data feed are
        automatically included.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addobserver(bt.observers.TradeLogger)
        >>> results = cerebro.run()
        >>> strat = results[0]
        >>> tl = strat.stats.tradelogger
        >>> all_logs = tl.get_all_logs()
    """

    _stclock = True

    lines = ("dummy",)

    params = (
        ("log_orders", True),
        ("log_trades", True),
        ("log_positions", True),
        ("log_data", True),
        ("extra_fields", None),
    )

    plotinfo = dict(plot=False, subplot=False)

    def __init__(self):
        """Initialize TradeLogger with empty log lists."""
        self.order_log = []
        self.trade_log = []
        self.position_log = []
        self.data_log = []

    @property
    def _owner_datas(self):
        """Get the strategy owner's data feeds.

        Observers have _mindatas=0 so self.datas/self.ddatas are empty.
        Strategy-wide observers must access data through the owner.
        """
        if hasattr(self, '_owner') and self._owner is not None:
            return getattr(self._owner, 'datas', [])
        return []

    def next(self):
        """Record order, trade, position, and bar data for the current bar.

        Called on every bar during the run, so logs are available in real-time.
        """
        if self.p.log_orders:
            self._log_orders()

        if self.p.log_trades:
            self._log_trades()

        if self.p.log_positions:
            self._log_positions()

        if self.p.log_data:
            self._log_data()

    def _log_orders(self):
        """Log pending order events for the current bar."""
        for order in self._owner._orderspending:
            entry = dict(
                ref=order.ref,
                ordtype=order.OrdTypes[order.ordtype] if order.ordtype is not None else "Unknown",
                status=order.Status[order.status],
                size=order.size,
                price=order.created.price if order.created else None,
                exectype=order.ExecTypes[order.exectype] if order.exectype is not None else None,
                executed_price=order.executed.price if order.executed and order.executed.size else None,
                executed_size=order.executed.size if order.executed else None,
                commission=order.executed.comm if order.executed else None,
                dt=num2date(order.data.datetime[0]) if len(order.data) else None,
                data_name=getattr(order.data, "_name", ""),
            )
            self.order_log.append(entry)

    def _log_trades(self):
        """Log pending trade events for the current bar."""
        for trade in self._owner._tradespending:
            entry = dict(
                ref=trade.ref,
                status=Trade.status_names[trade.status],
                size=trade.size,
                price=trade.price,
                value=trade.value,
                commission=trade.commission,
                pnl=trade.pnl,
                pnlcomm=trade.pnlcomm,
                isopen=trade.isopen,
                isclosed=trade.isclosed,
                justopened=trade.justopened,
                baropen=trade.baropen,
                barclose=trade.barclose,
                barlen=trade.barlen,
                dtopen=num2date(trade.dtopen) if trade.dtopen else None,
                dtclose=num2date(trade.dtclose) if trade.dtclose else None,
                data_name=getattr(trade.data, "_name", ""),
                tradeid=trade.tradeid,
                long=trade.long,
            )
            self.trade_log.append(entry)

    def _log_positions(self):
        """Log position snapshot for each data feed in the current bar."""
        for data in self._owner_datas:
            position = self._owner.getposition(data)
            entry = dict(
                dt=num2date(data.datetime[0]) if len(data) else None,
                data_name=getattr(data, "_name", ""),
                size=position.size,
                price=position.price,
            )
            self.position_log.append(entry)

    def _log_data(self):
        """Log bar data (OHLCV + open interest + extra fields) for each data feed."""
        for data in self._owner_datas:
            if not len(data):
                continue

            entry = dict(
                dt=num2date(data.datetime[0]),
                data_name=getattr(data, "_name", ""),
                open=data.open[0],
                high=data.high[0],
                low=data.low[0],
                close=data.close[0],
                volume=data.volume[0],
                openinterest=data.openinterest[0],
            )

            # Add extra lines beyond standard OHLCV + openinterest + datetime
            standard_lines = {
                "close", "low", "high", "open",
                "volume", "openinterest", "datetime",
            }

            extra_fields = self.p.extra_fields
            all_aliases = data.getlinealiases()

            if extra_fields is not None:
                # User-specified extra fields
                for field in extra_fields:
                    if hasattr(data.lines, field):
                        line = getattr(data.lines, field)
                        try:
                            entry[field] = line[0]
                        except (IndexError, Exception):
                            entry[field] = None
            else:
                # Auto-detect all extra lines
                for alias in all_aliases:
                    if alias not in standard_lines:
                        if hasattr(data.lines, alias):
                            line = getattr(data.lines, alias)
                            try:
                                entry[alias] = line[0]
                            except (IndexError, Exception):
                                entry[alias] = None

            self.data_log.append(entry)

    def get_order_log(self):
        """Return the collected order log.

        Returns:
            list: List of order event dictionaries.
        """
        return self.order_log

    def get_trade_log(self):
        """Return the collected trade log.

        Returns:
            list: List of trade event dictionaries.
        """
        return self.trade_log

    def get_position_log(self):
        """Return the collected position log.

        Returns:
            list: List of position snapshot dictionaries.
        """
        return self.position_log

    def get_data_log(self):
        """Return the collected data (bar) log.

        Returns:
            list: List of bar data dictionaries with OHLCV + extra fields.
        """
        return self.data_log

    def get_all_logs(self):
        """Return all logs as a dictionary.

        Returns:
            dict: Dictionary with keys 'orders', 'trades', 'positions', 'data'.
        """
        return dict(
            orders=self.order_log,
            trades=self.trade_log,
            positions=self.position_log,
            data=self.data_log,
        )
