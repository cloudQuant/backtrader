"""Native Alpha101 factor implementation for Alpha003."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    _MultiplyPanel,
    _RollingCorrelationPanel,
)
from .._helpers import pair_panel, panel
from ._metadata import native_alpha


@native_alpha
class Alpha003Native(FactorIndicator):
    """AF46-003: negative ten-grid correlation of daily open and volume ranks."""

    lines = ("factor",)
    alpha_id = 3
    case_id = "AF46-003"
    lookback_h = 9
    formula_fields = ("open", "volume")
    required_fields = formula_fields
    formula = "(-1 * correlation(rank(open), rank(volume), 10))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        open_rank = panel(self, "rank_open", CrossSectionalRank, self.field_lines("open"))
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        self._physical_nodes = []
        correlation = pair_panel(
            self,
            "correlation10",
            _RollingCorrelationPanel,
            open_rank,
            volume_rank,
            period=10,
        )
        self._result_lines = pair_panel(
            self,
            "negate",
            _MultiplyPanel,
            correlation,
            (-1.0,) * len(self.datas),
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        return ctx.correlation(ctx.rank(ctx.open), ctx.rank(ctx.volume), 10) * -1.0
