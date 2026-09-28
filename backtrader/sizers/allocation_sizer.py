"""Advisory sizing against an explicit managed notional allocation."""

import math
from decimal import Decimal

from ..parameters import ParameterDescriptor
from ..sizer import Sizer

__all__ = ["NotionalAllocationSizer"]


class NotionalAllocationSizer(Sizer):
    """Use the managed local risk reader and its reviewed instrument registry.

    Configure ``strategy_id``, ``instrument`` (the exact data feed name), a
    reviewed ``registry``, ``limit_price(data, isbuy)`` returning Decimal, and
    ``clock_ns()`` using the metadata's clock. This sizer requires the optional
    SDK allocation-sizing API. It never reads account cash or creates permits.

    Only the fixed notional reservation policy is supported; margin and
    remaining-position budgets need their own reviewed valuation contract.
    A stale suggestion can still be rejected by the writer's atomic gate.
    """

    strategy_id = ParameterDescriptor(default=None, doc="Exact managed strategy identity")
    instrument = ParameterDescriptor(default=None, doc="Exact instrument and data feed name")
    registry = ParameterDescriptor(default=None, doc="Reviewed SDK instrument risk registry")
    limit_price = ParameterDescriptor(default=None, doc="Bounded Decimal limit-price callback")
    clock_ns = ParameterDescriptor(default=None, doc="Clock matching the reviewed metadata")

    def getsizing(self, data, isbuy):
        """Return a native quantity suggestion without querying account balances."""

        strategy_id = self.get_param("strategy_id")
        instrument = self.get_param("instrument")
        if type(strategy_id) is not str or not strategy_id:
            raise ValueError("a managed strategy identity is required")
        if (
            type(instrument) is not str
            or not instrument
            or getattr(data, "_name", None) != instrument
        ):
            raise ValueError("data feed does not match the sizing instrument")
        price = self.get_param("limit_price")
        clock = self.get_param("clock_ns")
        if not callable(price) or not callable(clock):
            raise ValueError("reviewed limit price and metadata clock callbacks are required")
        reader = getattr(self.broker, "get_strategy_allocation", None)
        if not callable(reader):
            raise ValueError("managed strategy allocation reader is unavailable")
        # Import only on explicit use; ordinary backtests have no SDK dependency.
        from bt_api_risk.allocation_sizing import size_for_strategy_allocation

        snapshot = reader(strategy_id)
        if getattr(snapshot, "strategy_id", None) != strategy_id:
            raise ValueError("allocation snapshot belongs to a different strategy")
        quantity = size_for_strategy_allocation(
            snapshot,
            self.get_param("registry"),
            instrument=instrument,
            limit_price=price(data, isbuy),
            now_ns=clock(),
        )
        if quantity == quantity.to_integral_value():
            return int(quantity)
        value = float(quantity)
        if not math.isfinite(value) or Decimal(str(value)) != quantity:
            raise ValueError("suggested native quantity cannot be represented by this broker")
        return value
