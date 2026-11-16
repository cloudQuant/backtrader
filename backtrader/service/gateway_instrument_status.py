"""Validate detached SDK Gateway status diagnostics, without granting authority."""
from __future__ import annotations

import math
import threading


def validate_timeout(timeout_seconds):
    if type(timeout_seconds) not in (int, float):
        raise ValueError("INVALID_INSTRUMENT_STATUS_TIMEOUT")
    try:
        value = float(timeout_seconds)
    except (OverflowError, ValueError):
        raise ValueError("INVALID_INSTRUMENT_STATUS_TIMEOUT") from None
    if not math.isfinite(value) or not 0 < value <= threading.TIMEOUT_MAX:
        raise ValueError("INVALID_INSTRUMENT_STATUS_TIMEOUT")
    return value


def detached_instrument(instrument):
    from bt_api_base.market_protocol import MarketInstrumentKey
    from bt_api_py.gateway_instrument_status_query import decode_query

    if type(instrument) is not MarketInstrumentKey:
        raise ValueError("INVALID_INSTRUMENT_STATUS_INSTRUMENT")
    try:
        return decode_query({"instrument": instrument.to_dict()})
    except Exception:
        raise ValueError("INVALID_INSTRUMENT_STATUS_INSTRUMENT") from None


def unavailable(instrument, code="INSTRUMENT_STATUS_UNAVAILABLE"):
    from bt_api_py.gateway_strategy_instrument_status import GatewayInstrumentStatusQueryResult

    return GatewayInstrumentStatusQueryResult("UNAVAILABLE", instrument, code=code)


def detached_result(result, instrument):
    """Delegate neutral DTO validation and detachment to its SDK owner."""
    from bt_api_py.gateway_strategy_instrument_status import detached_query_result

    return detached_query_result(result, expected_instrument=instrument)
