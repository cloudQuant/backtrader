"""Backtrader history timeframe, bar and cache bridge for the SDK facade."""

from __future__ import annotations

from typing import Any, List, Optional


def fetch_store_history(
    dataname: str,
    timeframe=None,
    compression: int = 1,
    since=None,
    limit: Optional[int] = None,
    *,
    service_read_only,
    history_cache,
    ensure_api_ready,
    copy_or_normalize_bar,
    sdk_exchange,
    get_market_instrument_key,
    error_type,
    missing_dependency_error_type,
) -> List[Any]:
    """Fetch historical bars through the configured route and local BT cache."""
    if service_read_only:
        api = ensure_api_ready()
        bars = api.fetch_bars(
            dataname,
            timeframe=timeframe,
            compression=compression,
            since=since,
            limit=limit,
        )
        if type(bars) is not list:
            raise error_type("read-only service history is incomplete")
        return [copy_or_normalize_bar(bar) for bar in bars]
    if compression is None:
        history_compression = 1
    elif type(compression) is int and compression > 0:
        history_compression = compression
    else:
        raise error_type("history compression must be a positive integer")
    hit, request_key, default_request, cached_bars = history_cache.lookup(
        dataname,
        timeframe,
        history_compression,
        since,
        limit,
    )
    if hit:
        return cached_bars

    api = ensure_api_ready()
    try:
        from bt_api_py.facade_protocol import is_market_history_facade
        from bt_api_py.market_history_composition import (
            MarketHistoryCompositionError,
            market_history_collection_invalid,
        )
    except ImportError as exc:
        raise missing_dependency_error_type(
            "bt_api_py market-history facade contracts are required"
        ) from exc

    if not is_market_history_facade(api):
        if default_request and history_cache.has_default_history(dataname):
            return history_cache.cached_default_history(dataname)
        raise error_type("SDK facade does not expose typed market history")

    from ..dataseries import TimeFrame

    units = {
        TimeFrame.Seconds: "s",
        TimeFrame.Minutes: "m",
        TimeFrame.Days: "d",
        TimeFrame.Weeks: "w",
    }
    unit = units.get(timeframe) if type(timeframe) is int else None
    neutral_timeframe = (
        f"{history_compression}{unit}"
        if unit is not None
        else None
    )
    exchange_name = sdk_exchange(dataname)
    instrument = get_market_instrument_key(dataname)
    try:
        bars = api.fetch_market_history(
            exchange_name,
            instrument,
            neutral_timeframe,
            since=since,
            limit=limit,
            preserve_raw_bars=history_cache.preserve_raw_bars,
        )
    except MarketHistoryCompositionError as exc:
        if (
            exc.code == "MARKET_HISTORY_PROVIDER_CAPABILITY_UNAVAILABLE"
            and default_request
            and history_cache.has_default_history(dataname)
        ):
            return history_cache.cached_default_history(dataname)
        raise

    if market_history_collection_invalid(bars):
        raise error_type("SDK market history returned an invalid typed bar collection")
    if history_cache.preserve_raw_bars:
        # MarketBar intentionally contains only neutral OHLCV fields. A
        # typed projection cannot satisfy a caller that requested source
        # fields, so reject a malformed SDK implementation instead of
        # silently dropping those fields.
        raise error_type("SDK market history does not preserve raw source fields")

    projected = [
        {
            "timestamp": bar.open_time_utc,
            "close_time_utc": bar.close_time_utc,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "openinterest": bar.open_interest,
        }
        for bar in bars
    ]
    normalized = [
        history_cache.copy_or_normalize_bar(bar) for bar in projected
    ]
    history_cache.cache_result(
        dataname,
        request_key,
        default_request,
        normalized,
    )
    return history_cache.copy_history_sequence(normalized)
