"""Public registry and metadata contracts for native Alpha101 factors."""

import pytest

import backtrader.research.alpha101 as alpha101
from backtrader.research.alpha101 import (
    ALPHA_REGISTRY,
    Alpha003Build,
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
    DEFAULT_INPUT_POLICY,
    get_alpha,
    list_alphas,
)
from backtrader.research.factor_indicator import FactorIndicator
from tests.test_utils.alpha101_full_reference import formula_metadata, history_h

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
_ALPHA_IDS = tuple(range(1, 102))
_PUBLIC_HELPERS = {
    "ALPHA_REGISTRY",
    "DEFAULT_INPUT_POLICY",
    "get_alpha",
    "list_alphas",
    "native_alpha",
}


def test_public_registry_aliases_and_direct_factor_subclasses_cover_all_formulas():
    assert list_alphas() == _ALPHA_IDS
    assert tuple(ALPHA_REGISTRY) == _ALPHA_IDS
    assert alpha101.ALPHA_REGISTRY is ALPHA_REGISTRY

    expected_exports = _PUBLIC_HELPERS | {"Alpha%03dNative" % alpha_id for alpha_id in _ALPHA_IDS}
    expected_exports.add(Alpha003Build.__name__)
    assert set(alpha101.__all__) == expected_exports
    for alpha_id in _ALPHA_IDS:
        factor_class = get_alpha(alpha_id)
        assert ALPHA_REGISTRY[alpha_id] is factor_class
        assert getattr(alpha101, "Alpha%03dNative" % alpha_id) is factor_class
        assert factor_class.__bases__ == (FactorIndicator,)
        assert issubclass(factor_class, FactorIndicator)
        if alpha_id in _PROMOTED:
            assert factor_class is _PROMOTED[alpha_id]


def test_native_class_metadata_matches_the_static_formula_catalog():
    for alpha_id in _ALPHA_IDS:
        factor_class = get_alpha(alpha_id)
        source_metadata = formula_metadata(alpha_id)

        assert factor_class.alpha_id == alpha_id
        assert factor_class.case_id == "AF46-%03d" % alpha_id
        assert factor_class.formula == source_metadata["source_formula"]
        assert factor_class.lookback_h == history_h(alpha_id)
        assert factor_class.operator_profile == "alpha101-v2"
        assert factor_class.input_policy == DEFAULT_INPUT_POLICY
        assert isinstance(factor_class.formula_fields, tuple)
        assert factor_class.formula_fields
        assert all(isinstance(field, str) and field for field in factor_class.formula_fields)
        assert len(factor_class.formula_fields) == len(set(factor_class.formula_fields))
        assert factor_class.required_fields == factor_class.formula_fields


def test_registry_is_immutable_and_rejects_invalid_ids():
    with pytest.raises(TypeError):
        ALPHA_REGISTRY[102] = Alpha101Native

    with pytest.raises(TypeError, match="integer"):
        get_alpha(True)
    for alpha_id in (0, 102):
        with pytest.raises(KeyError):
            get_alpha(alpha_id)


def test_alpha101_public_surface_is_native_classes_without_formula_dsl():
    assert not hasattr(alpha101, "compile_formula")
    assert not hasattr(alpha101, "build_formula")
    assert not hasattr(alpha101, "FormulaDSL")
    assert all(
        isinstance(get_alpha(alpha_id).formula, str)
        and not hasattr(get_alpha(alpha_id), "build_formula")
        for alpha_id in _ALPHA_IDS
    )
