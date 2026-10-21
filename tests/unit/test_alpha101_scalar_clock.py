"""Target-clock provenance for scalar-only branches in native factor trees."""

import math
from types import SimpleNamespace

import pytest

import backtrader.research.operators as alpha_operators
from backtrader.research.errors import FactorComputationError
from backtrader.research.operators import (
    Add,
    CrossSectionalRank,
    IndNeutralize,
    Multiply,
    Subtract,
)
from backtrader.research.representative import _RepresentativeFactor
from tests.unit.test_factor_research_representatives import _frames, _run_subset


_WEIGHT = 0.728317


class _ScalarTreeProbe(_RepresentativeFactor):
    lines = ("factor",)
    alpha_id = 41
    case_id = "AF46-041"
    lookback_h = 0
    formula = "rank(close + ((1 - 0.728317) * 2))"
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        constant_leaf = self._per_asset(
            "constant_leaf",
            Subtract,
            (1.0,) * count,
            (_WEIGHT,) * count,
        )
        nested_constant = self._per_asset(
            "nested_constant",
            Multiply,
            constant_leaf,
            (2.0,) * count,
        )
        values = self._per_asset("add_constant_branch", Add, self._field("close"), nested_constant)
        return self._panel("rank", CrossSectionalRank, values)


class _WeightedVwapNeutralizer(_RepresentativeFactor):
    """Minimal weighted-VWAP tree with a neutralizing panel consumer."""

    lines = ("factor",)
    alpha_id = 59
    case_id = "AF46-059-clock"
    lookback_h = 0
    formula = "IndNeutralize(vwap*0.728317 + vwap*(1-0.728317), industry)"
    formula_fields = ("vwap",)
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        vwap = self._field("vwap")
        complement = self._per_asset(
            "weight_complement", Subtract, (1.0,) * count, (_WEIGHT,) * count
        )
        weighted = self._per_asset(
            "weighted_vwap",
            Add,
            self._per_asset("weighted_vwap_fixed", Multiply, vwap, (_WEIGHT,) * count),
            self._per_asset("weighted_vwap_complement", Multiply, vwap, complement),
        )
        return self._panel("industry_neutral", IndNeutralize, weighted, level="industry")


class _ForeignAssetProbe(_ScalarTreeProbe):
    lines = ("factor",)

    def _make_formula(self):
        close = self._field("close")
        return self._panel("rank_foreign", CrossSectionalRank, (close[1], close[0], close[2]))


@pytest.mark.parametrize("runonce", [False, True])
def test_weighted_vwap_scalar_complement_reaches_industry_neutralize(runonce):
    all_frames = _frames(periods=30)
    frames = {asset: frame.copy(deep=True) for asset, frame in list(all_frames.items())[:3]}
    names = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    strategy = _run_subset(
        frames,
        {"weighted_neutral": _WeightedVwapNeutralizer},
        runonce=runonce,
    )

    raw = strategy.get_dataset().raw_factors["weighted_neutral"].unstack("asset")
    for row, point in enumerate(grid):
        weighted = [
            float(frames[asset]["vwap"].iloc[row]) * _WEIGHT
            + float(frames[asset]["vwap"].iloc[row]) * (1.0 - _WEIGHT)
            for asset in names
        ]
        group_mean = math.fsum(weighted) / len(weighted)
        for asset, expected in zip(names, (value - group_mean for value in weighted)):
            assert float(raw.at[(point, asset)]) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("runonce", [False, True])
def test_factor_panel_accepts_nested_scalar_only_operator_branch(runonce):
    all_frames = _frames(periods=2)
    frames = {asset: frame.copy(deep=True) for asset, frame in list(all_frames.items())[:3]}
    strategy = _run_subset(frames, {"scalar_probe": _ScalarTreeProbe}, runonce=runonce)
    result = strategy.get_dataset().raw_factors["scalar_probe"]
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
