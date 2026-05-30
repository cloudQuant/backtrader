#!/usr/bin/env python
"""Smoke tests for backtrader.position_modes.

Covers the net/dual-side normalization and validation helpers used by the
brokers: mode/side/offset normalization, dual-side action validation, order
metadata normalization, side inference, trade keys and signed sizes.
"""

import pytest

from backtrader import position_modes as pm


def test_normalize_position_mode():
    assert pm.normalize_position_mode(None) == pm.POSITION_MODE_NET
    assert pm.normalize_position_mode("") == pm.POSITION_MODE_NET
    assert pm.normalize_position_mode("DUAL_SIDE") == pm.POSITION_MODE_DUAL_SIDE
    assert pm.normalize_position_mode(" net ") == pm.POSITION_MODE_NET
    with pytest.raises(ValueError):
        pm.normalize_position_mode("hedge")


def test_normalize_position_side_and_offset():
    assert pm.normalize_position_side(None) is None
    assert pm.normalize_position_side("LONG") == pm.POSITION_SIDE_LONG
    with pytest.raises(ValueError):
        pm.normalize_position_side("sideways")

    assert pm.normalize_position_offset(None) is None
    assert pm.normalize_position_offset("OPEN") == pm.POSITION_OFFSET_OPEN
    with pytest.raises(ValueError):
        pm.normalize_position_offset("flatten")


def test_validate_dual_side_action():
    # buy + long + open is a valid opening combo
    assert pm.validate_dual_side_action(True, "long", "open") == ("long", "open")
    # sell + long + close is valid (closing a long)
    assert pm.validate_dual_side_action(False, "long", "close") == ("long", "close")
    # missing side/offset is rejected
    with pytest.raises(ValueError):
        pm.validate_dual_side_action(True, None, None)
    # buy + short + open is valid; buy + long + close is NOT
    assert pm.validate_dual_side_action(False, "short", "open") == ("short", "open")
    with pytest.raises(ValueError):
        pm.validate_dual_side_action(True, "long", "close")


def test_normalize_order_position_meta():
    # net mode: passes side/offset through (normalized), no combo validation
    assert pm.normalize_order_position_meta("net", True, None, None) == (None, None)
    # dual-side mode: validates the combo
    assert pm.normalize_order_position_meta("dual_side", True, "long", "open") == (
        "long",
        "open",
    )


def test_infer_position_side():
    assert pm.infer_position_side(True, "open") == pm.POSITION_SIDE_LONG
    assert pm.infer_position_side(False, "open") == pm.POSITION_SIDE_SHORT
    assert pm.infer_position_side(True, "close") == pm.POSITION_SIDE_SHORT
    assert pm.infer_position_side(False, "close") == pm.POSITION_SIDE_LONG
    assert pm.infer_position_side(True, None) is None


def test_signed_position_size():
    assert pm.signed_position_size("long", 3) == 3.0
    assert pm.signed_position_size("short", 3) == -3.0
    assert pm.signed_position_size("long", 0) == 0.0


def test_trade_key_from_order():
    class _Info:
        def __init__(self, side):
            self.position_side = side

    class _Order:
        def __init__(self, tradeid, side):
            self.tradeid = tradeid
            self.info = _Info(side)

    # no position side -> plain tradeid
    assert pm.trade_key_from_order(_Order(7, None)) == 7
    # with side -> (tradeid, side) tuple
    assert pm.trade_key_from_order(_Order(7, "long")) == (7, "long")
    # invalid side falls back to plain tradeid
    assert pm.trade_key_from_order(_Order(9, "bogus")) == 9
