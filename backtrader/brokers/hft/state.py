"""Per-symbol trading state tracking for HFT simulation.

Defines :class:`StateTracker`, which accumulates per-symbol statistics (fees,
trade count, traded volume/value) updated on each fill, used for reporting and
fee accounting in the tick broker.
"""


class StateTracker:
    """Per-symbol trading-state accumulator for the HFT tick broker.

    Maintains, for every symbol seen in a fill, a running count of
    trades, traded volume and traded notional value, and the
    cumulative fees paid. Snapshots are produced for either a single
    symbol or every known symbol and are intended for reporting and
    fee accounting.
    """

    def __init__(self):
        """Initialize the empty per-symbol state dict."""
        self._states = {}

    def reset(self):
        """Clear all per-symbol state. Useful between backtest runs."""
        self._states = {}

    def get_state(self, symbol):
        """Return (and lazily create) the state dict for ``symbol``.

        The state dict holds four counters: ``fee`` (cumulative
        commission), ``num_trades`` (number of fills), ``trading_volume``
        (absolute shares/contracts traded) and ``trading_value``
        (absolute notional traded, ``volume * price``).

        Args:
            symbol: Symbol whose state to fetch or create.

        Returns:
            dict: The mutable per-symbol state dict.
        """
        if symbol not in self._states:
            self._states[symbol] = {
                "fee": 0.0,
                "num_trades": 0,
                "trading_volume": 0.0,
                "trading_value": 0.0,
            }
        return self._states[symbol]

    def on_fill(self, symbol, price, size, commission, role=None):
        """Record a fill and return the updated per-symbol state.

        Args:
            symbol: Symbol the fill belongs to.
            price: Fill price (per unit). Used to update
                ``trading_value``.
            size: Signed fill size. Only its absolute value is added
                to ``trading_volume``.
            commission: Commission charged for the fill, added to
                ``fee``.
            role: Optional :class:`backtrader.brokers.hft.exchange.FillRole`
                tag. The tracker ignores it; it is accepted so the
                call site can pass the role verbatim.

        Returns:
            dict: The updated per-symbol state dict.
        """
        _ = role
        state = self.get_state(symbol)
        state["num_trades"] += 1
        state["trading_volume"] += abs(size)
        state["trading_value"] += abs(size) * price
        state["fee"] += commission
        return state

    def snapshot(self, symbol, position, balance, mid_price=None):
        """Build a per-symbol snapshot dict combining state and P&L.

        Args:
            symbol: Symbol to snapshot.
            position: Current net position (signed shares/contracts).
            balance: Cash balance attributable to ``symbol`` (or
                the full account, depending on accounting).
            mid_price: Optional mid price used to mark the position
                to market when computing ``equity``. When ``None``,
                ``equity`` equals ``balance``.

        Returns:
            dict: ``{"position", "balance", "fee", "num_trades",
            "trading_volume", "trading_value", "equity"}``.
        """
        state = self.get_state(symbol)
        equity = balance
        if mid_price is not None:
            equity += position * mid_price
        return {
            "position": position,
            "balance": balance,
            "fee": state["fee"],
            "num_trades": state["num_trades"],
            "trading_volume": state["trading_volume"],
            "trading_value": state["trading_value"],
            "equity": equity,
        }

    def snapshot_all(self, positions, balance_by_symbol=None, mid_prices=None):
        """Build per-symbol snapshots for every known symbol.

        The symbol set is the union of the keys already in the
        tracker and the keys in the ``positions`` mapping, so symbols
        that have only ever carried a position (but no fills) are
        still included. Missing positions/balances default to
        ``0.0``; missing mid prices leave ``equity`` equal to the
        balance.

        Args:
            positions: Mapping of symbol -> signed position.
            balance_by_symbol: Optional mapping of symbol -> cash
                balance. ``None`` or missing keys default to ``0.0``.
            mid_prices: Optional mapping of symbol -> mid price for
                mark-to-market. ``None`` or missing keys leave
                ``equity`` equal to the balance.

        Returns:
            dict: ``{symbol: snapshot_dict}`` for every known symbol.
        """
        balance_by_symbol = balance_by_symbol or {}
        mid_prices = mid_prices or {}
        symbols = set(self._states) | set(positions)
        result = {}
        for symbol in symbols:
            result[symbol] = self.snapshot(
                symbol,
                positions.get(symbol, 0.0),
                balance_by_symbol.get(symbol, 0.0),
                mid_prices.get(symbol),
            )
        return result
