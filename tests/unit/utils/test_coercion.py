"""Stable coercion helpers used by live data adapters."""

import math

import pytest

from backtrader.utils.coercion import coerce_float, coerce_int, coerce_text, first_float


def test_coerce_float_accepts_common_vendor_shapes():
    assert coerce_float(None) == 0.0
    assert coerce_float("1,234.5") == 1234.5
    assert coerce_float({"amount": "2.5"}) == 2.5
    assert coerce_float({"value": "3"}) == 3.0
    assert coerce_float("bad", 7.0) == 7.0
    assert coerce_float(None, None) is None


def test_coerce_float_rejects_non_finite_values():
    assert coerce_float(math.inf) == 0.0
    assert coerce_float(math.nan, 9.0) == 9.0


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("12", 12),
        ("1,200", 1200),
        ("12.0", 12),
        (12.9, 12),
        ("12.5", 0),
        ("nan", 0),
        (None, 0),
        ("bad", 5),
    ),
)
def test_coerce_int_never_truncates_fractional_text(value, expected):
    default = expected if value == "bad" else 0
    assert coerce_int(value, default) == expected


def test_coerce_text_decodes_bytes_and_strips():
    assert coerce_text(b" hello ") == "hello"
    assert coerce_text("  value  ") == "value"
    assert coerce_text(None, "fallback") == "fallback"
    assert coerce_text(123) == "123"
    assert coerce_text(b"\xd6\xd0", "fallback") == "中"
    # latin1 is the last bounded decode, so arbitrary bytes stay lossless text.
    assert coerce_text(b"\xff\xfe", "fallback") == "ÿþ"


def test_first_float_returns_first_finite_value():
    assert first_float({"a": "bad", "b": "2.5"}, ("a", "b")) == 2.5
    assert first_float({"a": None}, ("a",)) is None
    assert first_float({}, ("a",)) is None
