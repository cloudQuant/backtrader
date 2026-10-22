"""Native Alpha101 factor implementation for Alpha034."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delta,
    Divide,
    RollingStd,
    Subtract,
)
from .._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha034Native(FactorIndicator):
    """AF46-034: ranked combination of relative volatility and close change ranks."""

    lines = ("factor",)
    alpha_id = 34
    case_id = "AF46-034"
    formula = (
        "rank(((1 - rank((stddev(returns, 2) / stddev(returns, 5)))) + "
        "(1 - rank(delta(close, 1)))))"
    )
    lookback_h = 5
    formula_fields = ("close",)
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        returns = simple_returns(self, "returns")
        std_returns_2 = per_asset(self, "returns_std_2", RollingStd, returns, period=2)
        std_returns_5 = per_asset(self, "returns_std_5", RollingStd, returns, period=5)
        relative_volatility = per_asset(
            self, "relative_volatility", Divide, std_returns_2, std_returns_5
        )
        ranked_volatility = panel(
            self, "rank_relative_volatility", CrossSectionalRank, relative_volatility
        )
        one_minus_volatility_rank = per_asset(
            self, "one_minus_volatility_rank", Subtract, (1.0,) * count, ranked_volatility
        )
        close_change = per_asset(self, "close_delta_1", Delta, self.field_lines("close"), period=1)
        ranked_close_change = panel(self, "rank_close_delta_1", CrossSectionalRank, close_change)
        one_minus_change_rank = per_asset(
            self, "one_minus_change_rank", Subtract, (1.0,) * count, ranked_close_change
        )
        combined = per_asset(
            self, "combined_rank_terms", Add, one_minus_volatility_rank, one_minus_change_rank
        )
        self._result_lines = panel(self, "factor", CrossSectionalRank, combined)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha034Build(FactorIndicator):
    """AF48-034: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha034Native.alpha_id
    case_id = Alpha034Native.case_id
    lookback_h = Alpha034Native.lookback_h
    formula_fields = Alpha034Native.formula_fields
    required_fields = Alpha034Native.required_fields
    formula = Alpha034Native.formula
    operator_profile = Alpha034Native.operator_profile
    input_policy = Alpha034Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        returns = ctx.returns()
        std_returns_2 = ctx.stddev(returns, 2)
        std_returns_5 = ctx.stddev(returns, 5)
        relative_volatility = std_returns_2 / std_returns_5
        ranked_volatility = ctx.rank(relative_volatility)
        one_minus_volatility_rank = 1.0 - ranked_volatility
        close_change = ctx.delta(ctx.field("close"), 1)
        ranked_close_change = ctx.rank(close_change)
        one_minus_change_rank = 1.0 - ranked_close_change
        combined = one_minus_volatility_rank + one_minus_change_rank
        factor = ctx.rank(combined)
        return factor
