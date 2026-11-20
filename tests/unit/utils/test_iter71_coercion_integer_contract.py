"""Compatibility contract for integer coercion across input representations."""

import math
from decimal import Decimal

import pytest

from backtrader.utils.coercion import coerce_int


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12.9, 12),
        (-12.9, -12),
        (Decimal("12.9"), 12),
        (Decimal("-12.9"), -12),
        (12.0, 12),
        (True, 1),
    ],
)
def test_non_string_numbers_follow_python_int_truncation(value, expected):
    assert coerce_int(value, default=73) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12.0", 12),
        ("1,200", 1200),
        ("12.9", 73),
        ("-12.9", 73),
        ("NaN", 73),
        ("Infinity", 73),
    ],
)
def test_text_numbers_require_a_finite_integral_decimal(value, expected):
    assert coerce_int(value, default=73) == expected


@pytest.mark.parametrize(
    "value",
    [None, math.nan, math.inf, -math.inf, Decimal("NaN"), Decimal("Infinity"), object()],
)
def test_none_non_finite_and_caught_conversion_errors_use_default(value):
    assert coerce_int(value, default=73) == 73


def test_unlisted_custom_conversion_errors_are_not_swallowed():
    class RaisesRuntimeError:
        def __int__(self):
            raise RuntimeError("custom conversion failure")

    with pytest.raises(RuntimeError, match="custom conversion failure"):
        coerce_int(RaisesRuntimeError(), default=73)
