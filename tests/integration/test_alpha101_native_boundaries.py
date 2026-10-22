"""Shared native Alpha101 input-binding boundary contracts."""

from __future__ import annotations

import pytest

from backtrader.errors import DatasetError
from backtrader.research.alpha101 import get_alpha, list_alphas
from backtrader.research.specs import FactorSpec


def _complete_bindings(indicator):
    """Return explicit ordinary-feed bindings for every declared input."""
    bindings = {}
    for alias in indicator.formula_fields:
        if alias.startswith("adv") and alias[3:].isdigit():
            bindings[alias] = {
                "derive": "adv",
                "source": "dollar_volume",
                "window": int(alias[3:]),
            }
        else:
            bindings[alias] = "feed:target:%s" % alias
    return bindings


@pytest.mark.parametrize("alpha_id", list_alphas(), ids=lambda value: "alpha%d" % value)
def test_each_alpha_rejects_an_absent_required_raw_field_before_calculation(alpha_id):
    indicator = get_alpha(alpha_id)
    bindings = _complete_bindings(indicator)
    raw_aliases = tuple(
        alias
        for alias in indicator.formula_fields
        if not alias.startswith("adv") and alias != "dollar_volume"
    )
    assert raw_aliases, "Alpha%d must declare at least one directly bound input" % alpha_id
    missing_alias = raw_aliases[0]
    del bindings[missing_alias]

    with pytest.raises(DatasetError) as caught:
        FactorSpec(
            name="alpha%d" % alpha_id,
            indicator=indicator,
            panel_line="factor",
            field_bindings=bindings,
        )

    assert caught.value.code == "MISSING_INPUT"
    assert caught.value.report["missing_fields"] == (missing_alias,)
