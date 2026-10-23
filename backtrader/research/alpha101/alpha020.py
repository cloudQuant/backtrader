"""Native Alpha101 factor implementation for Alpha020."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delay,
    Multiply,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha020Native(FactorIndicator):
    """Alpha #20: product of three cross-sectional open-minus-prior ranks."""

    lines = ("factor",)
    alpha_id = 20
    case_id = "AF46-020"
    lookback_h = 1
    formula = "(((-1 * rank((open - delay(high, 1)))) * rank((open - delay(close, 1)))) * rank((open - delay(low, 1))))"
    formula_fields = ("open", "high", "close", "low")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        open_ = self.field_lines("open")
        high_delay = per_asset(self, "high_delay1", Delay, self.field_lines("high"), period=1)
        close_delay = per_asset(self, "close_delay1", Delay, self.field_lines("close"), period=1)
        low_delay = per_asset(self, "low_delay1", Delay, self.field_lines("low"), period=1)
        open_minus_high = per_asset(self, "open_minus_high_delay", Subtract, open_, high_delay)
        open_minus_close = per_asset(self, "open_minus_close_delay", Subtract, open_, close_delay)
        open_minus_low = per_asset(self, "open_minus_low_delay", Subtract, open_, low_delay)
        rank_high = panel(self, "rank_open_minus_high_delay", CrossSectionalRank, open_minus_high)
        negative_rank_high = per_asset(
            self, "negative_rank_open_minus_high_delay", Multiply, rank_high, (-1.0,) * count
        )
        rank_close = panel(
            self, "rank_open_minus_close_delay", CrossSectionalRank, open_minus_close
        )
        first_product = per_asset(
            self, "first_rank_product", Multiply, negative_rank_high, rank_close
        )
        rank_low = panel(self, "rank_open_minus_low_delay", CrossSectionalRank, open_minus_low)
        self._result_lines = per_asset(self, "factor", Multiply, first_product, rank_low)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        open_ = ctx.field("open")
        high_delay = ctx.delay(ctx.field("high"), 1)
        close_delay = ctx.delay(ctx.field("close"), 1)
        low_delay = ctx.delay(ctx.field("low"), 1)
        open_minus_high = open_ - high_delay
        open_minus_close = open_ - close_delay
        open_minus_low = open_ - low_delay
        rank_high = ctx.rank(open_minus_high)
        negative_rank_high = rank_high * -1.0
        rank_close = ctx.rank(open_minus_close)
        first_product = negative_rank_high * rank_close
        rank_low = ctx.rank(open_minus_low)
        factor = first_product * rank_low
        return factor
