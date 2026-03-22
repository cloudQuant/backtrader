class StateTracker:
    def __init__(self):
        self._states = {}

    def reset(self):
        self._states = {}

    def get_state(self, symbol):
        if symbol not in self._states:
            self._states[symbol] = {
                "fee": 0.0,
                "num_trades": 0,
                "trading_volume": 0.0,
                "trading_value": 0.0,
            }
        return self._states[symbol]

    def on_fill(self, symbol, price, size, commission, role=None):
        _ = role
        state = self.get_state(symbol)
        state["num_trades"] += 1
        state["trading_volume"] += abs(size)
        state["trading_value"] += abs(size) * price
        state["fee"] += commission
        return state

    def snapshot(self, symbol, position, balance, mid_price=None):
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
