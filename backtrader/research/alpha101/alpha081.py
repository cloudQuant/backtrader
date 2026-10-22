"""Native Alpha101 factor implementation for Alpha081."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    LessThan,
    Log,
    Multiply,
    Power,
    RollingCorrelation,
    RollingProduct,
    RollingSum,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha081Native(FactorIndicator):
    """AF46-081: powered ranked correlation, rolling product/log and comparison."""

    lines = ("factor",)
    alpha_id = 81
    case_id = "AF46-081"
    lookback_h = 77
    formula_fields = ("vwap", "volume", "dollar_volume", "adv10")
    required_fields = formula_fields
    formula = "((rank(Log(product(rank((rank(correlation(vwap, sum(adv10, 49.6054), 8.47743))^4)), 14.9655))) < rank(correlation(rank(vwap), rank(volume), 5.07914))) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        adv10 = self.field_lines("adv10")
        adv_sum = per_asset(self, "adv10_sum49", RollingSum, adv10, period=49.6054)
        first_correlation = per_asset(
            self,
            "correlation8",
            RollingCorrelation,
            self.field_lines("vwap"),
            adv_sum,
            period=8.47743,
        )
        first_rank = panel(self, "first_rank", CrossSectionalRank, first_correlation)
        powered = per_asset(self, "rank_power4", Power, first_rank, (4.0,) * len(self.datas))
        powered_rank = panel(self, "powered_rank", CrossSectionalRank, powered)
        product = per_asset(self, "product14", RollingProduct, powered_rank, period=14.9655)
        logged = per_asset(self, "log_product", Log, product)
        ranked_log = panel(self, "rank_log_product", CrossSectionalRank, logged)
        vwap_rank = panel(self, "rank_vwap", CrossSectionalRank, self.field_lines("vwap"))
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        second_correlation = per_asset(
            self, "second_correlation5", RollingCorrelation, vwap_rank, volume_rank, period=5.07914
        )
        second_rank = panel(self, "second_rank", CrossSectionalRank, second_correlation)
        comparison = per_asset(self, "comparison", LessThan, ranked_log, second_rank)
        self._result_lines = per_asset(
            self, "negative_comparison", Multiply, comparison, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha081Build(FactorIndicator):
    """AF48-081: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha081Native.alpha_id
    case_id = Alpha081Native.case_id
    lookback_h = Alpha081Native.lookback_h
    formula_fields = Alpha081Native.formula_fields
    required_fields = Alpha081Native.required_fields
    formula = Alpha081Native.formula
    operator_profile = Alpha081Native.operator_profile
    input_policy = Alpha081Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        adv10 = ctx.field("adv10")
        adv_sum = ctx.sum(adv10, 49.6054)
        first_correlation = ctx.correlation(ctx.field("vwap"), adv_sum, 8.47743)
        first_rank = ctx.rank(first_correlation)
        powered = first_rank ** (4.0)
        powered_rank = ctx.rank(powered)
        product = ctx.product(powered_rank, 14.9655)
        logged = ctx.log(product)
        ranked_log = ctx.rank(logged)
        vwap_rank = ctx.rank(ctx.field("vwap"))
        volume_rank = ctx.rank(ctx.field("volume"))
        second_correlation = ctx.correlation(vwap_rank, volume_rank, 5.07914)
        second_rank = ctx.rank(second_correlation)
        comparison = ctx.less_than(ranked_log, second_rank)
        factor = comparison * (-1.0)
        return factor
