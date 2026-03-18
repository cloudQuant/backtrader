import pytest

from backtrader.channels.funding import _parse_optional_float as parse_funding_optional_float
from backtrader.channels.orderbook import _parse_levels, _parse_required_float
from backtrader.channels.tick import _parse_optional_float as parse_tick_optional_float


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", None),
        ("inf", None),
        ("-inf", None),
        ("nan", None),
        ("123.45", 123.45),
    ],
)
def test_tick_optional_float_parser_rejects_non_finite(value, expected):
    result = parse_tick_optional_float(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", None),
        ("inf", None),
        ("-inf", None),
        ("nan", None),
        ("0.0001", 0.0001),
    ],
)
def test_funding_optional_float_parser_rejects_non_finite(value, expected):
    result = parse_funding_optional_float(value)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


@pytest.mark.parametrize("value", ["inf", "-inf", "nan"])
def test_orderbook_required_float_rejects_non_finite(value):
    with pytest.raises(ValueError):
        _parse_required_float(value)


def test_orderbook_parse_levels_rejects_non_finite_level_values():
    with pytest.raises(ValueError):
        _parse_levels('[["inf", 1.0], [100.0, "nan"]]')


def test_orderbook_parse_levels_accepts_finite_level_values():
    assert _parse_levels('[[100.0, 1.5], [99.5, 2.0]]') == [
        (100.0, 1.5),
        (99.5, 2.0),
    ]
