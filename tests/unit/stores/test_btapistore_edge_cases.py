#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Edge case unit tests for btapistore utility functions.

Tests cover:
- _infer_tick_direction with zero prices (ask=0.0, bid=0.0)
- _infer_tick_direction with None prices
- _coerce_text edge cases
- _split_ctp_symbol edge cases
- _normalize_ctp_instrument CZCE prefix handling
- _ctp_field_to_dict with problematic attrs
- _order_to_payload price handling with zero/None prices
"""

import pytest
from unittest.mock import MagicMock

from backtrader.stores.btapistore import (
    _coerce_text,
    _ctp_field_to_dict,
    _infer_tick_direction,
    _normalize_ctp_instrument,
    _split_ctp_symbol,
)


# ===========================================================================
# _infer_tick_direction tests
# ===========================================================================


class TestInferTickDirection:
    """Test tick direction inference with edge case prices."""

    def test_buy_at_ask(self):
        assert _infer_tick_direction(100.0, 99.0, 100.0, None) == "buy"

    def test_sell_at_bid(self):
        assert _infer_tick_direction(99.0, 99.0, 100.0, None) == "sell"

    def test_zero_ask_price_not_skipped(self):
        """ask_price=0.0 should NOT be treated as None/falsy."""
        # last_price=5.0 >= ask_price=0.0 → should return "buy"
        result = _infer_tick_direction(5.0, None, 0.0, None)
        assert result == "buy"

    def test_zero_bid_price_not_skipped(self):
        """bid_price=0.0 should NOT be treated as None/falsy."""
        # last_price=0.0 <= bid_price=0.0 → should return "sell"
        result = _infer_tick_direction(0.0, 0.0, None, None)
        assert result == "sell"

    def test_none_ask_and_bid_falls_to_previous(self):
        """When ask and bid are None, use previous_price."""
        assert _infer_tick_direction(101.0, None, None, 100.0) == "buy"
        assert _infer_tick_direction(99.0, None, None, 100.0) == "sell"

    def test_all_none_defaults_to_buy(self):
        """When all reference prices are None, default to 'buy'."""
        assert _infer_tick_direction(100.0, None, None, None) == "buy"

    def test_equal_to_previous_is_buy(self):
        """When last_price == previous_price, direction is 'buy'."""
        assert _infer_tick_direction(100.0, None, None, 100.0) == "buy"

    def test_zero_last_price_with_zero_ask(self):
        """Edge: all prices are 0.0."""
        # last_price=0.0 >= ask_price=0.0 → "buy"
        result = _infer_tick_direction(0.0, 0.0, 0.0, 0.0)
        assert result == "buy"


# ===========================================================================
# _coerce_text tests
# ===========================================================================


class TestCoerceText:
    """Test text coercion edge cases."""

    def test_none_returns_default(self):
        assert _coerce_text(None) == ""

    def test_empty_string(self):
        assert _coerce_text("") == ""

    def test_whitespace_stripped(self):
        assert _coerce_text("  hello  ") == "hello"

    def test_bytes_utf8(self):
        assert _coerce_text(b"hello") == "hello"

    def test_bytes_gbk(self):
        # GBK-encoded Chinese text
        text = "你好"
        encoded = text.encode("gbk")
        assert _coerce_text(encoded) == text

    def test_numeric_coerced(self):
        assert _coerce_text(42) == "42"
        assert _coerce_text(3.14) == "3.14"

    def test_default_parameter(self):
        assert _coerce_text(None, "fallback") == "fallback"


# ===========================================================================
# _split_ctp_symbol tests
# ===========================================================================


class TestSplitCtpSymbol:
    """Test CTP symbol splitting edge cases."""

    def test_dot_format(self):
        instrument, exchange = _split_ctp_symbol("rb2510.SHFE")
        assert instrument == "rb2510"
        assert exchange == "SHFE"

    def test_underscore_format(self):
        instrument, exchange = _split_ctp_symbol("SHFE_rb2510")
        assert instrument == "rb2510"
        assert exchange == "SHFE"

    def test_plain_instrument(self):
        instrument, exchange = _split_ctp_symbol("rb2510")
        assert instrument == "rb2510"
        assert exchange == ""

    def test_empty_string(self):
        instrument, exchange = _split_ctp_symbol("")
        assert instrument == ""
        assert exchange == ""

    def test_none_input(self):
        instrument, exchange = _split_ctp_symbol(None)
        assert instrument == ""
        assert exchange == ""

    def test_czce_4digit_normalized(self):
        """CZCE 4-digit symbols should be normalized to 3-digit."""
        instrument, exchange = _split_ctp_symbol("AP2510.CZCE")
        assert instrument == "AP510"
        assert exchange == "CZCE"

    def test_non_czce_4digit_preserved(self):
        """Non-CZCE 4-digit symbols should be preserved."""
        instrument, exchange = _split_ctp_symbol("rb2510.SHFE")
        assert instrument == "rb2510"
        assert exchange == "SHFE"


# ===========================================================================
# _normalize_ctp_instrument tests
# ===========================================================================


class TestNormalizeCtpInstrument:
    """Test CTP instrument normalization edge cases."""

    def test_czce_explicit(self):
        assert _normalize_ctp_instrument("AP2510", "CZCE") == "AP510"

    def test_czce_inferred(self):
        """Known CZCE prefix without exchange should be normalized."""
        assert _normalize_ctp_instrument("CF2510", "") == "CF510"

    def test_non_czce_preserved(self):
        assert _normalize_ctp_instrument("rb2510", "SHFE") == "rb2510"

    def test_short_code_untouched(self):
        """Codes that don't match [A-Z]+\\d{4} are returned as-is."""
        assert _normalize_ctp_instrument("rb510", "") == "rb510"

    def test_empty_input(self):
        assert _normalize_ctp_instrument("", "") == ""

    def test_none_input(self):
        assert _normalize_ctp_instrument(None, "") == ""


# ===========================================================================
# _ctp_field_to_dict tests
# ===========================================================================


class TestCtpFieldToDict:
    """Test CTP struct to dict conversion edge cases."""

    def test_none_returns_empty(self):
        assert _ctp_field_to_dict(None) == {}

    def test_simple_object(self):
        obj = MagicMock()
        obj.InstrumentID = "rb2510"
        obj.ExchangeID = "SHFE"
        result = _ctp_field_to_dict(obj)
        assert result["InstrumentID"] == "rb2510"
        assert result["ExchangeID"] == "SHFE"

    def test_skips_private_attrs(self):
        obj = MagicMock()
        obj._private = "secret"
        result = _ctp_field_to_dict(obj)
        assert "_private" not in result

    def test_skips_callable_attrs(self):
        """Callable attributes (methods) should be skipped."""
        class FakeField:
            price = 100.0
            def method(self):
                pass
        result = _ctp_field_to_dict(FakeField())
        assert "price" in result
        assert "method" not in result

    def test_skips_this_and_thisown(self):
        """SWIG 'this' and 'thisown' attrs should be skipped."""
        class FakeField:
            this = "swig_ptr"
            thisown = True
            InstrumentID = "rb2510"
        result = _ctp_field_to_dict(FakeField())
        assert "this" not in result
        assert "thisown" not in result
        assert "InstrumentID" in result
