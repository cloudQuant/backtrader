"""Futures contract lookup for Backtrader strategies.

Lookup delegates to the configured broker. Both ranks can be obtained from a
single explicit query; selection does not roll, trade or establish authority.
For example, inside a strategy method::

    result = self.get_futures_contracts(
        "CTP___FUTURE", "SHFE", "rb", environment="simnow",
        allow_reference=True,
    )
    main, secondary = result.main, result.secondary

The first argument is an SDK route; venue and product identifiers must match
the provider. The default fails closed when real-time freshness is unavailable.
The explicit reference mode does not prove real-time freshness. Each separate
main/secondary call refreshes independently and may use a different snapshot;
use the combined method when the ranks must share one snapshot.
"""

from ..strategy import Strategy


class CtpFutureStrategy(Strategy):
    """Delegate futures lookups to the broker configured on this strategy."""

    def _futures_broker_method(self, name):
        method = getattr(self.broker, name, None)
        if not callable(method):
            raise NotImplementedError("futures contract lookup is unsupported by this broker")
        return method

    def get_futures_contracts(self, *args, **kwargs):
        """Return both ranks and source status from one broker lookup."""
        return self._futures_broker_method("get_futures_contracts")(*args, **kwargs)

    def get_main_contract(self, *args, **kwargs):
        """Request the first rank; each call performs a separate lookup."""
        return self._futures_broker_method("get_main_contract")(*args, **kwargs)

    def get_secondary_contract(self, *args, **kwargs):
        """Request the second rank, if present; each call performs a lookup."""
        return self._futures_broker_method("get_secondary_contract")(*args, **kwargs)
