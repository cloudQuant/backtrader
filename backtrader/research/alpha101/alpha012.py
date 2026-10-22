"""Native Alpha101 factor implementation for Alpha012."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Delta,
    Multiply,
    Sign,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha012Native(FactorIndicator):
    """Alpha #12: sign of volume change times negative close change."""

    lines = ("factor",)
    alpha_id = 12
    case_id = "AF46-012"
    lookback_h = 1
    formula = "(sign(delta(volume, 1)) * (-1 * delta(close, 1)))"
    formula_fields = ("volume", "close")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        volume_delta = per_asset(self, "volume_delta1", Delta, self.field_lines("volume"), period=1)
        volume_sign = per_asset(self, "sign_volume_delta", Sign, volume_delta)
        close_delta = per_asset(self, "close_delta1", Delta, self.field_lines("close"), period=1)
        negative_close_delta = per_asset(
            self, "negative_close_delta", Multiply, close_delta, (-1.0,) * count
        )
        self._result_lines = per_asset(self, "factor", Multiply, volume_sign, negative_close_delta)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
