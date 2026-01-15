"""Digital Currency Commission Module - Crypto commission scheme.

This module provides the ComminfoDC class for calculating commissions
for digital currency (cryptocurrency) trading.

Classes:
    ComminfoDC: Commission info for digital currency trading.

Example:
    >>> comminfo = bt.commissions.ComminfoDC(
    ...     commission=0.001,
    ...     margin=0.5
    ... )
    >>> cerebro.broker.setcommission(comminfo)
"""

from ..comminfo import CommInfoBase


class ComminfoDC(CommInfoBase):
    """Implement a digital currency commission class"""

    params = (
        ("stocklike", False),
        ("commtype", CommInfoBase.COMM_PERC),
        ("percabs", True),
        ("interest", 3),
    )

    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * price * self.p.mult * self.p.commission

    def get_margin(self, price):
        """Calculate margin required for a position at given price.

        Args:
            price: Price per unit of the asset.

        Returns:
            float: Margin amount required.
        """
        return price * self.p.mult * self.p.margin

    # Calculate interest fee, involves some simplifications
    def get_credit_interest(self, data, pos, dt):
        """For example, I hold 100U, want to buy 300U of BTC, leverage is 3x, at this time I only need to borrow 2*100U,
        so interest should be 200U * interest, similarly, for nx long, need to pay (n-1)*base interest
         If I want to open short, I only have 100U, I must borrow BTC to sell first, even 1x short, need to borrow 100U worth of BTC,
         so for nx short, need to pay n*base interest"""
        # Position and price
        size, price = pos.size, pos.price
        # Holding time
        dt0 = dt
        dt1 = pos.datetime
        gap_seconds = (dt0 - dt1).seconds
        days = gap_seconds / (24 * 60 * 60)
        # Calculate current position value
        position_value = size * price * self.p.mult
        # If current position is long, and position value greater than 1x leverage, portion exceeding 1x leverage will be charged interest
        total_value = self.getvalue()
        if size > 0 and position_value > total_value:
            return days * self.self._creditrate * (position_value - total_value)
        # If position is long, but within 1x leverage
        if size > 0 and position_value <= total_value:
            return 0
        # If current is short position, calculate interest
        if size < 0:
            return days * self.self._creditrate * position_value
