"""Native Alpha101 factor implementation for Alpha028."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalScale,
    Divide,
    RollingCorrelation,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha028Native(FactorIndicator):
    """AF46-028: scaled sum of ADV/low correlation and the high-low midpoint."""

    lines = ("factor",)
    alpha_id = 28
    case_id = "AF46-028"
    formula = "scale(((correlation(adv20, low, 5) + ((high + low) / 2)) - close))"
    lookback_h = 23
    formula_fields = ("low", "high", "close", "dollar_volume", "adv20")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        correlation = per_asset(
            self,
            "adv20_low_correlation_5",
            RollingCorrelation,
            self.field_lines("adv20"),
            self.field_lines("low"),
            period=5,
        )
        high_plus_low = per_asset(
            self, "high_plus_low", Add, self.field_lines("high"), self.field_lines("low")
        )
        midpoint = per_asset(self, "high_low_midpoint", Divide, high_plus_low, (2.0,) * count)
        correlation_plus_midpoint = per_asset(
            self, "correlation_plus_midpoint", Add, correlation, midpoint
        )
        unscaled = per_asset(
            self, "scale_input", Subtract, correlation_plus_midpoint, self.field_lines("close")
        )
        self._result_lines = panel(self, "factor", CrossSectionalScale, unscaled)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        correlation = ctx.correlation(ctx.field("adv20"), ctx.field("low"), 5)
        high_plus_low = ctx.field("high") + ctx.field("low")
        midpoint = high_plus_low / 2.0
        correlation_plus_midpoint = correlation + midpoint
        unscaled = correlation_plus_midpoint - ctx.field("close")
        factor = ctx.scale(unscaled)
        return factor
