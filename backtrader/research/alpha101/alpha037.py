"""Native Alpha101 factor implementation for Alpha037."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delay,
    RollingCorrelation,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha037Native(FactorIndicator):
    """AF46-037: rank of delayed intraday-move correlation plus its direct rank."""

    lines = ("factor",)
    alpha_id = 37
    case_id = "AF46-037"
    formula = "(rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close)))"
    lookback_h = 200
    formula_fields = ("open", "close")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        open_close = per_asset(
            self, "open_minus_close", Subtract, self.field_lines("open"), self.field_lines("close")
        )
        delayed_open_close = per_asset(
            self, "delay_open_minus_close_1", Delay, open_close, period=1
        )
        correlation = per_asset(
            self,
            "delayed_open_close_correlation_200",
            RollingCorrelation,
            delayed_open_close,
            self.field_lines("close"),
            period=200,
        )
        ranked_correlation = panel(
            self, "rank_delayed_open_close_correlation", CrossSectionalRank, correlation
        )
        ranked_open_close = panel(self, "rank_open_minus_close", CrossSectionalRank, open_close)
        self._result_lines = per_asset(self, "factor", Add, ranked_correlation, ranked_open_close)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha037Build(FactorIndicator):
    """AF48-037: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha037Native.alpha_id
    case_id = Alpha037Native.case_id
    lookback_h = Alpha037Native.lookback_h
    formula_fields = Alpha037Native.formula_fields
    required_fields = Alpha037Native.required_fields
    formula = Alpha037Native.formula
    operator_profile = Alpha037Native.operator_profile
    input_policy = Alpha037Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        open_close = ctx.field("open") - ctx.field("close")
        delayed_open_close = ctx.delay(open_close, 1)
        correlation = ctx.correlation(delayed_open_close, ctx.field("close"), 200)
        ranked_correlation = ctx.rank(correlation)
        ranked_open_close = ctx.rank(open_close)
        factor = ranked_correlation + ranked_open_close
        return factor
