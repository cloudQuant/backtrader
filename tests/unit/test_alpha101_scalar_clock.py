"""Target-clock provenance for scalar-only branches in native factor trees."""

import math
from types import SimpleNamespace

import pytest

import backtrader.research.operators as alpha_operators
from backtrader.research._helpers import panel, per_asset
from backtrader.errors import FactorComputationError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.operators import (
    Add,
    CrossSectionalRank,
    IndNeutralize,
    Multiply,
    Subtract,
)
from tests.unit.test_factor_research_representatives import _frames, _run_subset

_WEIGHT = 0.728317


class _ScalarTreeProbe(FactorIndicator):
    lines = ("factor",)
    alpha_id = 41
    case_id = "AF46-041-scalar-clock-probe"
    lookback_h = 0
    formula = "rank(close + ((1 - 0.728317) * 2))"
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        constant_leaf = per_asset(
            self, "constant_leaf", Subtract, (1.0,) * count, (_WEIGHT,) * count
        )
        nested_constant = per_asset(
            self, "nested_constant", Multiply, constant_leaf, (2.0,) * count
        )
        values = per_asset(
            self, "add_constant_branch", Add, self.field_lines("close"), nested_constant
        )
        self._result_lines = panel(self, "rank", CrossSectionalRank, values)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


class _WeightedVwapNeutralizer(FactorIndicator):
    """Minimal weighted-VWAP tree with a neutralizing panel consumer."""

    lines = ("factor",)
    alpha_id = 59
    case_id = "AF46-059-clock-probe"
    lookback_h = 0
    formula = "IndNeutralize(vwap*0.728317 + vwap*(1-0.728317), industry)"
    formula_fields = ("vwap",)
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        vwap = self.field_lines("vwap")
        complement = per_asset(
            self, "weight_complement", Subtract, (1.0,) * count, (_WEIGHT,) * count
        )
        weighted = per_asset(
            self,
            "weighted_vwap",
            Add,
            per_asset(self, "weighted_vwap_fixed", Multiply, vwap, (_WEIGHT,) * count),
            per_asset(self, "weighted_vwap_complement", Multiply, vwap, complement),
        )
        self._result_lines = panel(
            self,
            "industry_neutral",
            IndNeutralize,
            weighted,
            level="industry",
            groups=self.classification_lines("industry"),
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


class _ForeignAssetProbe(FactorIndicator):
    lines = ("factor",)
    alpha_id = 42
    case_id = "AF46-042-foreign-asset-probe"
    lookback_h = 0
    formula = "rank(close) with inputs bound to different target assets"
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close = self.field_lines("close")
        self._result_lines = panel(
            self, "rank_foreign", CrossSectionalRank, (close[1], close[0], close[2])
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]




@pytest.mark.parametrize("runonce", [False, True])
def test_factor_panel_accepts_nested_scalar_only_operator_branch(runonce):
    all_frames = _frames(periods=2)
    frames = {asset: frame.copy(deep=True) for asset, frame in list(all_frames.items())[:3]}
    strategy = _run_subset(frames, {"scalar_probe": _ScalarTreeProbe}, runonce=runonce)
    result = strategy.get_panel().factors["scalar_probe"]
    assert all(math.isfinite(float(value)) for value in result)


@pytest.mark.parametrize("runonce", [False, True])
def test_factor_panel_rejects_a_real_line_from_another_target(runonce):
    all_frames = _frames(periods=2)
    frames = {asset: frame.copy(deep=True) for asset, frame in list(all_frames.items())[:3]}

    with pytest.raises(FactorComputationError) as caught:
        _run_subset(frames, {"scalar_probe": _ForeignAssetProbe}, runonce=runonce)

    assert isinstance(caught.value.__cause__, alpha_operators.OperatorInputError)


def test_unknown_operator_with_scalar_shaped_metadata_is_not_neutral():
    class UnknownOperator:
        _operand_args = (1.0, 2.0)
        datas = ()

    source = SimpleNamespace(
        _owner=SimpleNamespace(_owner_ref=UnknownOperator()),
        _clock=None,
    )
    target = SimpleNamespace()

    assert alpha_operators._line_target_relation(source, target) is None
