"""Native Alpha101 factor implementation for Alpha032."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalScale,
    Delay,
    Divide,
    Multiply,
    RollingCorrelation,
    RollingSum,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha032Native(FactorIndicator):
    """AF46-032: two scaled price terms, including a five-delayed 230-grid correlation."""

    lines = ("factor",)
    alpha_id = 32
    case_id = "AF46-032"
    formula = (
        "(scale(((sum(close, 7) / 7) - close)) + "
        "(20 * scale(correlation(vwap, delay(close, 5), 230))))"
    )
    lookback_h = 234
    formula_fields = ("close", "vwap")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close = self.field_lines("close")
        close_sum_7 = per_asset(self, "sum_close_7", RollingSum, close, period=7)
        close_mean_7 = per_asset(self, "mean_close_7", Divide, close_sum_7, (7.0,) * count)
        close_mean_difference = per_asset(
            self, "close_mean_difference", Subtract, close_mean_7, close
        )
        scaled_mean_difference = panel(
            self, "scale_close_mean_difference", CrossSectionalScale, close_mean_difference
        )
        close_delay_5 = per_asset(self, "delay_close_5", Delay, close, period=5)
        correlation = per_asset(
            self,
            "vwap_close_correlation_230",
            RollingCorrelation,
            self.field_lines("vwap"),
            close_delay_5,
            period=230,
        )
        scaled_correlation = panel(
            self, "scale_vwap_close_correlation", CrossSectionalScale, correlation
        )
        weighted_correlation = per_asset(
            self, "weighted_correlation", Multiply, (20.0,) * count, scaled_correlation
        )
        self._result_lines = per_asset(
            self, "factor", Add, scaled_mean_difference, weighted_correlation
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha032Build(FactorIndicator):
    """AF48-032: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha032Native.alpha_id
    case_id = Alpha032Native.case_id
    lookback_h = Alpha032Native.lookback_h
    formula_fields = Alpha032Native.formula_fields
    required_fields = Alpha032Native.required_fields
    formula = Alpha032Native.formula
    operator_profile = Alpha032Native.operator_profile
    input_policy = Alpha032Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        close = ctx.field("close")
        close_sum_7 = ctx.sum(close, 7)
        close_mean_7 = close_sum_7 / 7.0
        close_mean_difference = close_mean_7 - close
        scaled_mean_difference = ctx.scale(close_mean_difference)
        close_delay_5 = ctx.delay(close, 5)
        correlation = ctx.correlation(ctx.field("vwap"), close_delay_5, 230)
        scaled_correlation = ctx.scale(correlation)
        weighted_correlation = 20.0 * scaled_correlation
        factor = scaled_mean_difference + weighted_correlation
        return factor
