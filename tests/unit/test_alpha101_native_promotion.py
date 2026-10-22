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
    DEFAULT_INPUT_POLICY,
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






