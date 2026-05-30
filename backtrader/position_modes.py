"""Shared helpers for net and dual-side position handling."""

from __future__ import annotations

POSITION_MODE_NET = "net"
POSITION_MODE_DUAL_SIDE = "dual_side"

POSITION_SIDE_LONG = "long"
POSITION_SIDE_SHORT = "short"

POSITION_OFFSET_OPEN = "open"
POSITION_OFFSET_CLOSE = "close"
POSITION_OFFSET_CLOSE_TODAY = "close_today"
POSITION_OFFSET_CLOSE_YESTERDAY = "close_yesterday"

_VALID_POSITION_MODES = {
    POSITION_MODE_NET,
    POSITION_MODE_DUAL_SIDE,
}
_VALID_POSITION_SIDES = {
    POSITION_SIDE_LONG,
    POSITION_SIDE_SHORT,
}
_VALID_POSITION_OFFSETS = {
    POSITION_OFFSET_OPEN,
    POSITION_OFFSET_CLOSE,
    POSITION_OFFSET_CLOSE_TODAY,
    POSITION_OFFSET_CLOSE_YESTERDAY,
}
_VALID_DUAL_SIDE_COMBOS = {
    (True, POSITION_SIDE_LONG, POSITION_OFFSET_OPEN),
    (False, POSITION_SIDE_LONG, POSITION_OFFSET_CLOSE),
    (False, POSITION_SIDE_SHORT, POSITION_OFFSET_OPEN),
    (True, POSITION_SIDE_SHORT, POSITION_OFFSET_CLOSE),
}


def normalize_position_mode(mode):
    """Normalize and validate a broker position mode."""
    mode = POSITION_MODE_NET if mode in (None, "") else str(mode).strip().lower()
    if mode not in _VALID_POSITION_MODES:
        raise ValueError(f"Unsupported position_mode {mode!r}. Expected 'net' or 'dual_side'")
    return mode


def normalize_position_side(side):
    """Normalize and validate a position side."""
    if side in (None, ""):
        return None

    side = str(side).strip().lower()
    if side not in _VALID_POSITION_SIDES:
        raise ValueError(f"Unsupported position_side {side!r}. Expected 'long' or 'short'")
    return side


def normalize_position_offset(offset):
    """Normalize and validate a position offset."""
    if offset in (None, ""):
        return None

    offset = str(offset).strip().lower()
    if offset not in _VALID_POSITION_OFFSETS:
        raise ValueError(f"Unsupported offset {offset!r}. Expected 'open' or 'close'")
    return offset


def validate_dual_side_action(isbuy, position_side, offset):
    """Validate a dual-side order action."""
    position_side = normalize_position_side(position_side)
    offset = normalize_position_offset(offset)

    if position_side is None or offset is None:
        raise ValueError("dual_side mode requires both position_side and offset to be specified")

    if (bool(isbuy), position_side, offset) not in _VALID_DUAL_SIDE_COMBOS:
        action = "buy" if isbuy else "sell"
        raise ValueError(
            f"Invalid dual-side order combination: action={action}, "
            f"position_side={position_side}, offset={offset}"
        )

    return position_side, offset


def normalize_order_position_meta(mode, isbuy, position_side=None, offset=None):
    """Normalize broker order metadata for the configured position mode."""
    mode = normalize_position_mode(mode)
    position_side = normalize_position_side(position_side)
    offset = normalize_position_offset(offset)

    if mode == POSITION_MODE_DUAL_SIDE:
        return validate_dual_side_action(isbuy, position_side, offset)

    return position_side, offset


def infer_position_side(isbuy, offset):
    """Infer the target leg from order direction and offset."""
    offset = normalize_position_offset(offset)
    if offset is None:
        return None

    if offset == POSITION_OFFSET_OPEN:
        return POSITION_SIDE_LONG if isbuy else POSITION_SIDE_SHORT

    return POSITION_SIDE_SHORT if isbuy else POSITION_SIDE_LONG


def trade_key_from_order(order):
    """Return the trade-group key used by strategy notifications."""
    raw_position_side = getattr(getattr(order, "info", None), "position_side", None)
    try:
        position_side = normalize_position_side(raw_position_side)
    except ValueError:
        position_side = None
    if position_side is None:
        return order.tradeid
    return (order.tradeid, position_side)


def signed_position_size(position_side, quantity):
    """Convert a positive leg quantity into backtrader signed size semantics."""
    position_side = normalize_position_side(position_side)
    quantity = abs(float(quantity or 0.0))
    if position_side == POSITION_SIDE_SHORT:
        return -quantity
    return quantity
