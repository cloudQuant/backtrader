"""Native Alpha101 factor implementation for Alpha008."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delay,
    Multiply,
    RollingSum,
    Subtract,
)
from .._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha008Native(FactorIndicator):
    """Alpha #8: negative cross-rank of the delayed product difference."""

    lines = ("factor",)
    alpha_id = 8
    case_id = "AF46-008"
    lookback_h = 15
    formula = "(-1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(open, 5) * sum(returns, 5)), 10))))"
    formula_fields = ("open", "close")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        open_sum = per_asset(self, "open_sum5", RollingSum, self.field_lines("open"), period=5)
        returns = simple_returns(self, "returns")
        returns_sum = per_asset(self, "returns_sum5", RollingSum, returns, period=5)
        product = per_asset(self, "sum_product", Multiply, open_sum, returns_sum)
        prior_product = per_asset(self, "delayed_sum_product", Delay, product, period=10)
        difference = per_asset(self, "product_difference", Subtract, product, prior_product)
        ranked = panel(self, "rank_product_difference", CrossSectionalRank, difference)
        self._result_lines = per_asset(self, "negative_rank", Multiply, ranked, (-1.0,) * count)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
