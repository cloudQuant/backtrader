"""Native Alpha101 factor implementation for Alpha056."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Divide,
    Multiply,
    RollingSum,
    Subtract,
)
from .._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha056Native(FactorIndicator):
    """AF46-056: nested return sums times a point-in-time cap rank."""

    lines = ("factor",)
    alpha_id = 56
    case_id = "AF46-056"
    lookback_h = 10
    formula_fields = ("close", "cap")
    required_fields = formula_fields
    formula = (
        "(0 - (1 * (rank((sum(returns, 10) / sum(sum(returns, 2), 3))) * rank((returns * cap)))))"
    )

    def __init__(self):
        super().__init__()
        self._nodes = {}
        returns = simple_returns(self, "returns")
        long_sum = per_asset(self, "sum_returns10", RollingSum, returns, period=10)
        inner_sum = per_asset(self, "sum_returns2", RollingSum, returns, period=2)
        nested_sum = per_asset(self, "sum_of_sum3", RollingSum, inner_sum, period=3)
        ratio = per_asset(self, "sum_ratio", Divide, long_sum, nested_sum)
        ranked_ratio = panel(self, "rank_sum_ratio", CrossSectionalRank, ratio)
        return_cap = per_asset(self, "return_times_cap", Multiply, returns, self.field_lines("cap"))
        ranked_return_cap = panel(self, "rank_return_cap", CrossSectionalRank, return_cap)
        product = per_asset(self, "rank_product", Multiply, ranked_ratio, ranked_return_cap)
        times_one = per_asset(self, "times_one", Multiply, product, (1.0,) * len(self.datas))
        self._result_lines = per_asset(
            self, "zero_minus", Subtract, (0.0,) * len(self.datas), times_one
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        returns = ctx.returns()
        long_sum = ctx.sum(returns, 10)
        inner_sum = ctx.sum(returns, 2)
        nested_sum = ctx.sum(inner_sum, 3)
        ratio = long_sum / nested_sum
        ranked_ratio = ctx.rank(ratio)
        return_cap = returns * ctx.field("cap")
        ranked_return_cap = ctx.rank(return_cap)
        product = ranked_ratio * ranked_return_cap
        times_one = product * 1.0
        factor = 0.0 - times_one
        return factor
