"""Reusable strict CTP instrument, margin, and commission contract."""

from __future__ import annotations

import math
from typing import Any


def field_value(source: Any, *names: str) -> Any:
    for name in names:
        if isinstance(source, dict) and name in source:
            value = source.get(name)
            if value not in (None, ""):
                return value
        if source is not None and hasattr(source, name):
            try:
                value = getattr(source, name)
            except Exception:
                continue
            if value not in (None, ""):
                return value
    return None


def field_float(source: Any, *names: str) -> float | None:
    value = field_value(source, *names)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reference_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            value = value.decode("gb18030", errors="replace")
    return str(value).strip().strip("\x00") or None


def _reference_number(source: Any, *names: str) -> float | None:
    value = field_value(source, *names)
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    # Native CTP uses DBL_MAX as an unavailable-price sentinel.
    return number if math.isfinite(number) and 0 < number < 1e308 else None


def normalize_ctp_instrument(instrument_info: Any) -> dict[str, Any]:
    """Normalize native reference fields without guessing absent product rules.

    ProductClass, OptionsType and InstLifePhase values follow the bundled CTP
    ThostFtdcUserApiDataType.h. Names do not determine instrument type. Dates
    remain native YYYYMMDD strings, and IsTrading is a reference flag, not a
    real-time session status. Exercise style/calendar/settlement rules require
    independently sourced exchange product rules.
    """

    def text(*names):
        return _reference_text(field_value(instrument_info, *names))

    product_class = text("ProductClass", "product_class")
    kind = {
        "1": "future",
        "2": "option",
        "3": "combination",
        "4": "spot",
        "5": "efp",
        "6": "spot_option",
        "7": "tas",
        "I": "mi",
    }.get(product_class, "unknown")
    is_option = kind in {"option", "spot_option"}
    raw_trading = field_value(instrument_info, "IsTrading", "is_trading")
    if raw_trading in (1, "1", b"1", True):
        is_trading = True
    elif raw_trading in (0, "0", b"0", False):
        is_trading = False
    else:
        is_trading = None
    return {
        "metadata_source": "ctp_instrument_field",
        "instrument_id": text("InstrumentID", "instrument_id"),
        "instrument_name": text("InstrumentName", "instrument_name"),
        "exchange_id": text("ExchangeID", "exchange_id"),
        "exchange_instrument_id": text("ExchangeInstID", "exchange_instrument_id"),
        "product_id": text("ProductID", "product_id"),
        "product_class": product_class,
        "asset_type": kind,
        "contract_type": kind,
        "multiplier": _reference_number(
            instrument_info, "VolumeMultiple", "multiplier", "contract_size"
        ),
        "price_tick": _reference_number(instrument_info, "PriceTick", "price_tick", "tick_size"),
        "min_limit_order_volume": _reference_number(
            instrument_info, "MinLimitOrderVolume", "min_limit_order_volume"
        ),
        "max_limit_order_volume": _reference_number(
            instrument_info, "MaxLimitOrderVolume", "max_limit_order_volume"
        ),
        "min_market_order_volume": _reference_number(
            instrument_info, "MinMarketOrderVolume", "min_market_order_volume"
        ),
        "max_market_order_volume": _reference_number(
            instrument_info, "MaxMarketOrderVolume", "max_market_order_volume"
        ),
        "underlying_instrument": (
            text("UnderlyingInstrID", "underlying_instrument") if is_option else None
        ),
        "strike_price": (
            _reference_number(instrument_info, "StrikePrice", "strike_price") if is_option else None
        ),
        "option_type": ({"1": "call", "2": "put"}.get(text("OptionsType")) if is_option else None),
        "underlying_multiple": (
            _reference_number(instrument_info, "UnderlyingMultiple", "underlying_multiple")
            if is_option
            else None
        ),
        "create_date": text("CreateDate", "create_date"),
        "open_date": text("OpenDate", "open_date"),
        "expiry_date": text("ExpireDate", "expiry_date"),
        "start_delivery_date": text("StartDelivDate", "start_delivery_date"),
        "end_delivery_date": text("EndDelivDate", "end_delivery_date"),
        "delivery_year": field_value(instrument_info, "DeliveryYear", "delivery_year"),
        "delivery_month": field_value(instrument_info, "DeliveryMonth", "delivery_month"),
        "life_phase": {
            "0": "not_started",
            "1": "started",
            "2": "paused",
            "3": "expired",
        }.get(text("InstLifePhase"), "unknown"),
        "is_trading": is_trading,
        "status": (
            "trading" if is_trading is True else "disabled" if is_trading is False else "unknown"
        ),
        "exercise_style": None,
    }


def _finite_non_negative_field(source: Any, *names: str) -> bool:
    """Return whether at least one named field is explicit and financially valid."""
    value = field_value(source, *names)
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= 0


def ctp_instrument_evidence_errors(
    instrument: str,
    exchange_id: str,
    instrument_info: Any,
    margin_info: Any,
    commission_info: Any,
) -> tuple[str, ...]:
    """Validate that three terminal queries prove one complete tradable contract."""
    expected_instrument = str(instrument or "").strip()
    expected_exchange = str(exchange_id or "").strip().upper()
    errors: list[str] = []

    for label, source in (
        ("instrument", instrument_info),
        ("margin", margin_info),
        ("commission", commission_info),
    ):
        if source is None:
            errors.append(f"missing_{label}_record")
            continue
        actual_instrument = str(field_value(source, "InstrumentID") or "").strip()
        if not actual_instrument:
            errors.append(f"missing_{label}_instrument_id")
        elif expected_instrument and actual_instrument != expected_instrument:
            errors.append(f"mismatched_{label}_instrument_id")
        actual_exchange = str(field_value(source, "ExchangeID") or "").strip().upper()
        if expected_exchange and actual_exchange and actual_exchange != expected_exchange:
            errors.append(f"mismatched_{label}_exchange_id")

    multiplier = field_float(instrument_info, "VolumeMultiple", "contract_size", "multiplier")
    price_tick = field_float(instrument_info, "PriceTick", "price_tick", "tick_size")
    if multiplier is None or not math.isfinite(multiplier) or multiplier <= 0:
        errors.append("invalid_volume_multiple")
    if price_tick is None or not math.isfinite(price_tick) or price_tick <= 0:
        errors.append("invalid_price_tick")

    if not _finite_non_negative_field(
        margin_info,
        "LongMarginRatioByMoney",
        "LongMarginRatioByVolume",
        "long_margin_rate",
    ):
        errors.append("missing_long_margin")
    if not _finite_non_negative_field(
        margin_info,
        "ShortMarginRatioByMoney",
        "ShortMarginRatioByVolume",
        "short_margin_rate",
    ):
        errors.append("missing_short_margin")

    for label, money_name, volume_name in (
        ("open", "OpenRatioByMoney", "OpenRatioByVolume"),
        ("close", "CloseRatioByMoney", "CloseRatioByVolume"),
        ("close_today", "CloseTodayRatioByMoney", "CloseTodayRatioByVolume"),
    ):
        if not _finite_non_negative_field(
            commission_info,
            money_name,
            volume_name,
            f"{label}_fee_rate",
            f"{label}_fee_amount",
        ):
            errors.append(f"missing_{label}_commission")
    return tuple(errors)


def ctp_query_bundle_errors(
    results: tuple[Any, ...],
    *,
    current_session: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Require one account and connection generation across a query bundle."""
    errors: list[str] = []
    generations = {int(getattr(result, "connection_generation", 0) or 0) for result in results}
    account_fingerprints = {
        str(getattr(result, "account_fingerprint", "") or "") for result in results
    }
    if len(generations) != 1 or not generations or 0 in generations:
        errors.append("mixed_query_connection_generation")
    if len(account_fingerprints) != 1 or not account_fingerprints or "" in account_fingerprints:
        errors.append("mixed_query_account_fingerprint")

    session = current_session or {}
    session_generation = int(session.get("connection_generation", 0) or 0)
    session_fingerprint = str(session.get("account_fingerprint", "") or "")
    if not session_generation:
        errors.append("missing_current_session_generation")
    elif generations and generations != {session_generation}:
        errors.append("query_generation_not_current")
    if not session_fingerprint:
        errors.append("missing_current_session_account_fingerprint")
    elif account_fingerprints and account_fingerprints != {session_fingerprint}:
        errors.append("query_account_not_current")
    return tuple(errors)


def ctp_query_bundle_identity_error(
    results: tuple[Any, ...], current_session: dict[str, Any] | None = None
) -> str | None:
    """Require every component query to belong to one current account generation."""
    generations = {getattr(result, "connection_generation", None) for result in results}
    fingerprints = {str(getattr(result, "account_fingerprint", "") or "") for result in results}
    if len(generations) != 1 or None in generations:
        return "component_query_generation_mismatch"
    if len(fingerprints) != 1 or "" in fingerprints:
        return "component_query_account_mismatch"
    if current_session:
        generation = next(iter(generations))
        fingerprint = next(iter(fingerprints))
        if generation != current_session.get("connection_generation"):
            return "component_query_generation_stale"
        if fingerprint != str(current_session.get("account_fingerprint") or ""):
            return "component_query_account_stale"
    return None


def build_ctp_instrument_spec(
    instrument: str,
    exchange_id: str,
    instrument_info: Any,
    margin_info: Any,
    commission_info: Any,
) -> dict[str, Any]:
    """Merge three terminal CTP queries without fabricating missing rules."""
    if not any((instrument_info, margin_info, commission_info)):
        return {}
    exchange = str(
        field_value(instrument_info, "ExchangeID")
        or field_value(margin_info, "ExchangeID")
        or field_value(commission_info, "ExchangeID")
        or exchange_id
        or ""
    ).strip()
    symbol = str(
        field_value(instrument_info, "InstrumentID")
        or field_value(margin_info, "InstrumentID")
        or field_value(commission_info, "InstrumentID")
        or instrument
        or ""
    ).strip()
    metadata = normalize_ctp_instrument(instrument_info)
    multiplier = metadata["multiplier"]
    price_tick = metadata["price_tick"]
    long_margin_rate = field_float(margin_info, "LongMarginRatioByMoney", "long_margin_rate")
    short_margin_rate = field_float(margin_info, "ShortMarginRatioByMoney", "short_margin_rate")
    open_fee_rate = field_float(commission_info, "OpenRatioByMoney", "open_fee_rate")
    open_fee_amount = field_float(commission_info, "OpenRatioByVolume", "open_fee_amount")
    close_fee_rate = field_float(commission_info, "CloseRatioByMoney", "close_fee_rate")
    close_fee_amount = field_float(commission_info, "CloseRatioByVolume", "close_fee_amount")
    close_today_fee_rate = field_float(
        commission_info,
        "CloseTodayRatioByMoney",
        "close_today_fee_rate",
    )
    close_today_fee_amount = field_float(
        commission_info,
        "CloseTodayRatioByVolume",
        "close_today_fee_amount",
    )
    margin_rate = long_margin_rate if long_margin_rate is not None else short_margin_rate
    max_quantity = field_float(instrument_info, "MaxLimitOrderVolume", "max_limit_order_volume")

    spec: dict[str, Any] = {
        **metadata,
        "source": "ctp_query_contract",
        "symbol": symbol,
        "instrument": symbol,
        "exchange": exchange,
        "exchange_id": exchange,
        "product_id": field_value(instrument_info, "ProductID"),
        "expiry_date": field_value(instrument_info, "ExpireDate", "expiry_date"),
        "trading_calendar_evidence_complete": bool(
            field_value(instrument_info, "trading_calendar_evidence_complete")
        ),
        "prior_day_ranking_evidence_complete": bool(
            field_value(instrument_info, "prior_day_ranking_evidence_complete")
        ),
        "price_tick": price_tick,
        "tick_size": price_tick,
        "multiplier": multiplier,
        "contract_multiplier": 1,
        "contract_size": multiplier,
        "volume_multiple": multiplier,
        "contract_value": multiplier,
        "quantity_step": 1,
        "min_quantity": 1,
        "max_quantity": max_quantity,
        "quantity_unit": "lots",
        "base_currency": field_value(instrument_info, "ProductID") or symbol,
        "quote_currency": "CNY",
        "linear": (
            True
            if metadata["asset_type"] == "future"
            else False
            if metadata["asset_type"] in {"option", "spot_option"}
            else None
        ),
        "margin": margin_rate,
        "margin_rate": margin_rate,
        "long_margin_rate": long_margin_rate,
        "short_margin_rate": short_margin_rate,
        "long_margin_amount": field_float(margin_info, "LongMarginRatioByVolume"),
        "short_margin_amount": field_float(margin_info, "ShortMarginRatioByVolume"),
        "open_fee_rate": open_fee_rate,
        "open_commission_rate": open_fee_rate,
        "commission_rate": open_fee_rate,
        "open_fee_amount": open_fee_amount,
        "open_commission_amount": open_fee_amount,
        "commission_amount": open_fee_amount,
        "close_fee_rate": close_fee_rate,
        "close_commission_rate": close_fee_rate,
        "close_fee_amount": close_fee_amount,
        "close_commission_amount": close_fee_amount,
        "close_yesterday_fee_rate": close_fee_rate,
        "close_yesterday_commission_rate": close_fee_rate,
        "close_yesterday_fee_amount": close_fee_amount,
        "close_yesterday_commission_amount": close_fee_amount,
        "close_today_fee_rate": close_today_fee_rate,
        "close_today_commission_rate": close_today_fee_rate,
        "close_today_fee_amount": close_today_fee_amount,
        "close_today_commission_amount": close_today_fee_amount,
    }
    return {key: value for key, value in spec.items() if value not in (None, "")}


__all__ = [
    "normalize_ctp_instrument",
    "build_ctp_instrument_spec",
    "ctp_instrument_evidence_errors",
    "ctp_query_bundle_errors",
    "ctp_query_bundle_identity_error",
    "field_float",
    "field_value",
]
