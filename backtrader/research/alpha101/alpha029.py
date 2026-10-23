"""Native Alpha101 factor implementation for Alpha029."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    CrossSectionalScale,
    Delay,
    Delta,
    Log,
    Multiply,
    RollingProduct,
    RollingSum,
    Subtract,
    TsMin,
    TsRank,
)
from .._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha029Native(FactorIndicator):
    """AF46-029: nested rank/scale/log/product path and delayed-return rank."""

    lines = ("factor",)
    alpha_id = 29
    case_id = "AF46-029"
    lookback_h = 11
    formula_fields = ("close",)
    required_fields = formula_fields
    formula = "(min(product(rank(rank(scale(log(sum(ts_min(rank(rank((-1 * rank(delta((close - 1), 5))))), 2), 1))))), 1), 5) + ts_rank(delay((-1 * returns), 6), 5))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close_minus_one = per_asset(
            self, "close_minus_one", Subtract, self.field_lines("close"), (1.0,) * len(self.datas)
        )
        change = per_asset(self, "delta5", Delta, close_minus_one, period=5)
        rank_once = panel(self, "rank_delta", CrossSectionalRank, change)
        negate = per_asset(self, "negative_rank", Multiply, rank_once, (-1.0,) * len(self.datas))
        rank_twice = panel(self, "rank_negative_rank", CrossSectionalRank, negate)
        rank_thrice = panel(self, "rank_rank_negative", CrossSectionalRank, rank_twice)
        local_min = per_asset(self, "ts_min2", TsMin, rank_thrice, period=2)
        local_sum = per_asset(self, "sum1", RollingSum, local_min, period=1)
        logged = per_asset(self, "log_sum", Log, local_sum)
        scaled = panel(self, "scale_log", CrossSectionalScale, logged)
        ranked_scaled = panel(self, "rank_scaled", CrossSectionalRank, scaled)
        ranked_again = panel(self, "rank_rank_scaled", CrossSectionalRank, ranked_scaled)
        product = per_asset(self, "product1", RollingProduct, ranked_again, period=1)
        rolling_min = per_asset(self, "ts_min5", TsMin, product, period=5)
        returns = simple_returns(self, "returns")
        negative_returns = per_asset(
            self, "negative_returns", Multiply, returns, (-1.0,) * len(self.datas)
        )
        delayed = per_asset(self, "delay6", Delay, negative_returns, period=6)
        delayed_rank = per_asset(self, "ts_rank5", TsRank, delayed, period=5)
        self._result_lines = per_asset(self, "add_branches", Add, rolling_min, delayed_rank)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        close_minus_one = ctx.close - 1.0
        delta = ctx.delta(close_minus_one, 5)
        rank_once = ctx.rank(delta)
        negative_rank = rank_once * -1.0
        rank_twice = ctx.rank(negative_rank)
        rank_thrice = ctx.rank(rank_twice)
        local_min = ctx.ts_min(rank_thrice, 2)
        local_sum = ctx.sum(local_min, 1)
        logged = ctx.log(local_sum)
        scaled = ctx.scale(logged)
        ranked_scaled = ctx.rank(scaled)
        ranked_again = ctx.rank(ranked_scaled)
        product = ctx.product(ranked_again, 1)
        rolling_min = ctx.ts_min(product, 5)

        returns = ctx.returns()
        negative_returns = returns * -1.0
        delayed = ctx.delay(negative_returns, 6)
        delayed_rank = ctx.ts_rank(delayed, 5)
        return rolling_min + delayed_rank
