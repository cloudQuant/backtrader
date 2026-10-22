"""Contracts for promotion of the twenty accepted Alpha101 recipes."""

import math

import pytest

from backtrader.research.alpha101 import (
    ALPHA_REGISTRY,
    Alpha001Native,
    Alpha002Native,
    Alpha003Native,
    Alpha004Native,
    Alpha007Native,
    Alpha009Native,
    Alpha013Native,
    Alpha029Native,
    Alpha048Native,
    Alpha056Native,
    Alpha058Native,
    Alpha062Native,
    Alpha063Native,
    Alpha067Native,
    Alpha081Native,
    Alpha084Native,
    Alpha092Native,
    Alpha096Native,
    Alpha100Native,
    Alpha101Native,
    DEFAULT_FORMULA_UNIVERSE_POLICY,
    DEFAULT_PIT_POLICY,
    get_alpha,
    list_alphas,
    native_alpha,
)
from backtrader.research.factor_indicator import FactorIndicator
from tests.test_utils.alpha101_full_reference import formula_metadata, formula_source
from tests.unit.test_factor_research_representatives import (
    _FORMULA_FIELDS,
    _HISTORY,
    _formula_reference,
    _frames,
    _run_subset,
)

_PROMOTED = {
    1: Alpha001Native,
    2: Alpha002Native,
    3: Alpha003Native,
    4: Alpha004Native,
    7: Alpha007Native,
    9: Alpha009Native,
    13: Alpha013Native,
    29: Alpha029Native,
    48: Alpha048Native,
    56: Alpha056Native,
    58: Alpha058Native,
    62: Alpha062Native,
    63: Alpha063Native,
    67: Alpha067Native,
    81: Alpha081Native,
    84: Alpha084Native,
    92: Alpha092Native,
    96: Alpha096Native,
    100: Alpha100Native,
    101: Alpha101Native,
}


def test_metadata_decorator_canonicalizes_class_attrs_without_registry_side_effect():
    before = list_alphas()
    before_registry = tuple(ALPHA_REGISTRY.items())

    class UnregisteredAlpha077(FactorIndicator):
        lines = ("factor",)
        alpha_id = 77
        formula = "rank(close)"
        lookback_h = 0
        formula_fields = ("close",)
        classification_fields = ()
        classification_levels = ()

        def next(self):
            pass

    decorated = native_alpha(UnregisteredAlpha077)
    assert list_alphas() == before
    assert tuple(ALPHA_REGISTRY.items()) == before_registry
    assert decorated is UnregisteredAlpha077
    assert UnregisteredAlpha077.alpha_id == 77
    assert UnregisteredAlpha077.formula == "rank(close)"
    assert UnregisteredAlpha077.lookback_h == 0
    assert UnregisteredAlpha077.operator_profile == "alpha101-v1"
    assert UnregisteredAlpha077.formula_fields == ("close",)
    assert UnregisteredAlpha077.classification_fields == ()
    assert UnregisteredAlpha077.classification_levels == ()
    assert UnregisteredAlpha077.formula_universe_policy == DEFAULT_FORMULA_UNIVERSE_POLICY
    assert UnregisteredAlpha077.pit_policy == DEFAULT_PIT_POLICY


def test_promotion_registry_and_declarations_match_the_twenty_reviewed_recipes():
    assert set(_PROMOTED).issubset(list_alphas())
    assert set(_PROMOTED).issubset(ALPHA_REGISTRY)

    for alpha_id, native_class in _PROMOTED.items():
        source_metadata = formula_metadata(alpha_id)
        expected_formula = formula_source(alpha_id)
        expected_classification_levels = tuple(
            call["level"] for call in source_metadata["classification_requirements"]["calls"]
        )
        expected_classification_fields = tuple(dict.fromkeys(expected_classification_levels))

        assert get_alpha(alpha_id) is native_class
        assert issubclass(native_class, FactorIndicator)
        assert native_class.__bases__ == (FactorIndicator,)
        assert native_class.__dict__["alpha_id"] == alpha_id
        assert native_class.__dict__["case_id"] == "AF46-%03d" % alpha_id
        assert "__init__" in native_class.__dict__
        assert "next" in native_class.__dict__
        assert native_class.__dict__["formula"] == expected_formula
        assert native_class.__dict__["lookback_h"] == _HISTORY[alpha_id]
        assert native_class.__dict__["formula_fields"] == _FORMULA_FIELDS[alpha_id]
        assert "classification_fields" in native_class.__dict__
        assert "classification_levels" in native_class.__dict__
        assert native_class.formula == expected_formula
        assert native_class.lookback_h == _HISTORY[alpha_id]
        assert native_class.operator_profile == "alpha101-v1"
        assert native_class.formula_fields == _FORMULA_FIELDS[alpha_id]
        assert native_class.required_fields == _FORMULA_FIELDS[alpha_id]
        assert native_class.classification_fields == expected_classification_fields
        assert native_class.classification_levels == expected_classification_levels
        assert native_class.pit_policy == DEFAULT_PIT_POLICY

    assert (
        Alpha009Native.formula_universe_policy
        == "per-target close history; output eligibility from ResearchSpec.formula_universe"
    )
    assert (
        Alpha101Native.formula_universe_policy
        == "per-target pointwise evaluation; output eligibility from ResearchSpec.formula_universe"
    )


@pytest.mark.parametrize("runonce", (False, True))
def test_all_twenty_production_classes_match_the_independent_formula_oracle(runonce):
    frames = _frames(periods=320)
    factor_names = {"alpha%d" % alpha_id: cls for alpha_id, cls in _PROMOTED.items()}
    strategy = _run_subset(frames, factor_names, runonce=runonce)
    raw = strategy.get_dataset().raw_factors
    grid = tuple(next(iter(frames.values())).index.to_pydatetime())
    assets = tuple(frames)

    for alpha_id, native_class in _PROMOTED.items():
        name = "alpha%d" % alpha_id
        expected, _ = _formula_reference(alpha_id, frames)
        spec = strategy._factor_specs_by_name[name]
        factor = strategy.factor_instances[name]
        assert spec.indicator is native_class
        assert spec.lookback_h == native_class.lookback_h
        assert factor.lookback_h == native_class.lookback_h

        finite_witnesses = 0
        for row, point in enumerate(grid):
            for column, asset in enumerate(assets):
                # The independent matrix oracle computes formula nodes before
                # the declared indicator warmup is applied. Mask against its
                # independent H table, never the production class/spec.
                wanted = expected[row][column] if row >= _HISTORY[alpha_id] else math.nan
                got = float(raw.at[(point, asset), name])
                if math.isnan(wanted):
                    assert math.isnan(got), "%s row %d asset %s should remain ineligible/warmup" % (
                        name,
                        row,
                        asset,
                    )
                else:
                    assert math.isfinite(got), "%s row %d asset %s is not finite" % (
                        name,
                        row,
                        asset,
                    )
                    assert abs(got - wanted) <= 1e-12 + 1e-10 * abs(wanted), (
                        "%s row %d asset %s differs from the independent oracle: "
                        "got %.17g, wanted %.17g" % (name, row, asset, got, wanted)
                    )
                    finite_witnesses += 1
        assert finite_witnesses, "%s produced no finite reference-backed witness" % name
