"""Market impact models for order book depth matching.

Provides pluggable market impact models used by OrderBookBroker to
estimate price impact of large orders consuming depth levels.

Models:
    - MarketImpactModel: Abstract base class
    - LinearImpactModel: Linear price impact proportional to order size
    - SquareRootImpactModel: Square-root impact model (more realistic)

Example::

    from backtrader.brokers.impact_models import SquareRootImpactModel
    model = SquareRootImpactModel(coefficient=0.1)
    impact = model.calculate_impact(price=50000, size=10.0)
"""

import math
from abc import ABC, abstractmethod

__all__ = ["MarketImpactModel", "LinearImpactModel", "SquareRootImpactModel"]


class MarketImpactModel(ABC):
    """Abstract base class for market impact models.

    Market impact models estimate how a trade of a given size at a given
    price level will move the market price, accounting for liquidity
    consumption effects.
    """

    @abstractmethod
    def calculate_impact(self, price, size) -> float:
        """Calculate the absolute price impact.

        Args:
            price: Current price level.
            size: Order size being filled.

        Returns:
            Absolute price impact (always >= 0).
        """
        pass


class LinearImpactModel(MarketImpactModel):
    """Linear market impact: impact = coefficient * size * price.

    Simple model where price impact scales linearly with order size.
    Suitable for small orders relative to market depth.

    Args:
        coefficient: Impact coefficient (default: 0.001).
            Higher values mean more price impact per unit size.
    """

    def __init__(self, coefficient=0.001):
        """Initialize the linear impact model.

        Args:
            coefficient: Impact coefficient (default: 0.001).
                Higher values mean more price impact per unit size.
        """
        self.coefficient = coefficient

    def calculate_impact(self, price, size) -> float:
        """Calculate linear price impact.

        Returns:
            coefficient * size * price
        """
        return self.coefficient * abs(size) * price


class SquareRootImpactModel(MarketImpactModel):
    """Square-root market impact: impact = coefficient * sqrt(size) * price.

    More realistic model based on empirical research showing that price
    impact scales with the square root of order size. Better suited for
    large orders.

    Args:
        coefficient: Impact coefficient (default: 0.01).
        daily_volume: Average daily volume for normalization (default: 0.0).
            If > 0, size is normalized by daily volume before sqrt.
    """

    def __init__(self, coefficient=0.01, daily_volume=0.0):
        """Initialize the square-root impact model.

        Args:
            coefficient: Impact coefficient (default: 0.01).
            daily_volume: Average daily volume for normalization (default: 0.0).
                If > 0, size is normalized by daily volume before sqrt.
        """
        self.coefficient = coefficient
        self.daily_volume = daily_volume

    def calculate_impact(self, price, size) -> float:
        """Calculate square-root price impact.

        If daily_volume > 0:
            impact = coefficient * sqrt(size / daily_volume) * price
        Else:
            impact = coefficient * sqrt(size) * price

        Returns:
            Absolute price impact.
        """
        abs_size = abs(size)
        if abs_size <= 0:
            return 0.0

        if self.daily_volume > 0:
            normalized = abs_size / self.daily_volume
        else:
            normalized = abs_size

        return self.coefficient * math.sqrt(normalized) * price
