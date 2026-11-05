"""Project validated neutral account-position rows into Store position mappings."""

from __future__ import annotations

import math
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Type


def project_account_position_rows(
    rows: Any,
    *,
    account_position_type: Type[Any],
    market_instrument_key_type: Type[Any],
    validate_row: Callable[..., None],
    feed_name_for: Callable[[Any], str],
    quantity_unit_for: Callable[[str, Any], str],
    unavailable: Callable[[str], None],
) -> List[Dict[str, Any]]:
    """Map already-validated neutral rows to Backtrader position dictionaries.

    Route selection, snapshot completeness, session binding, freshness, and
    lease validation belong to the caller. This function is stateless and only
    performs the feed/unit binding and row projection using injected callbacks.
    """
    projected: List[Dict[str, Any]] = []
    rows_by_name: Dict[str, List[Any]] = defaultdict(list)
    for row in rows:
        validate_row(
            row,
            account_position_type=account_position_type,
            market_instrument_key_type=market_instrument_key_type,
            unavailable=unavailable,
        )
        dataname = feed_name_for(row.instrument)
        quantity_unit = quantity_unit_for(dataname, row.instrument)
        if row.qty_unit != quantity_unit:
            unavailable("account_position_snapshot_quantity_unit_mismatch")
        rows_by_name[dataname].append(row)

    for dataname, grouped_rows in rows_by_name.items():
        if len(grouped_rows) > 2:
            unavailable("account_position_snapshot_multiple_rows_unsupported")
        if len(grouped_rows) == 2:
            sides = {row.side for row in grouped_rows}
            if (
                sides != {"long", "short"}
                or grouped_rows[0].resource != grouped_rows[1].resource
                or grouped_rows[0].qty_unit != grouped_rows[1].qty_unit
            ):
                unavailable("account_position_snapshot_multiple_rows_ambiguous")

        for row in grouped_rows:
            try:
                amount = Decimal(row.quantity)
                if not amount.is_finite():
                    raise InvalidOperation
                if row.side in {"long", "short"} and amount < 0:
                    raise InvalidOperation
                size = float(amount)
                if not math.isfinite(size):
                    raise OverflowError
                if row.average_price is None:
                    if amount:
                        unavailable(
                            "account_position_snapshot_average_price_unavailable"
                        )
                    price = 0.0
                else:
                    price = float(Decimal(row.average_price))
                    if not math.isfinite(price) or price < 0:
                        raise InvalidOperation
            except (InvalidOperation, TypeError, ValueError, OverflowError):
                unavailable("account_position_snapshot_numeric_projection_invalid")

            if row.side in {"long", "short"}:
                size = abs(size)
            projected.append(
                {
                    "data_name": dataname,
                    "symbol": row.instrument.native_symbol,
                    "instrument": row.instrument.to_dict(),
                    "quantity": row.quantity,
                    "quantity_unit": row.qty_unit,
                    "qty_unit": row.qty_unit,
                    "side": row.side,
                    "position_side": row.side,
                    "direction": row.side,
                    "size": size,
                    "volume": abs(size),
                    "average_price": row.average_price,
                    "price": price,
                    "price_currency": row.price_currency,
                    "resource": row.resource.to_dict(),
                    "observed_at_utc": row.observed_at_utc,
                }
            )
    return projected


def project_store_account_positions(
    store, *, error_type, missing_dependency_error_type, contract_metadata_aliases
) -> List[Dict[str, Any]]:
    """Read and project independent current snapshots for configured routes.

    The SDK owns account/query/session/lease evidence. Store only binds its
    neutral position rows to configured Backtrader feeds route by route and
    projects typed quantity, side, unit, and average price without provider
    parsing. The returned list is assembled only after every route projects.
    """

    def unavailable(code: str) -> None:
        error = error_type("SDK account position snapshot is unavailable")
        error.code = code
        raise error

    try:
        from bt_api_py.instrument_metadata_aliases import configured_position_quantity_unit
        from bt_api_py.account_position_read import (
            position_read_has_positions,
            validate_position_read_batch,
            validate_position_read_row,
        )
    except ImportError as exc:
        raise missing_dependency_error_type(
            "bt_api_py account position read contracts are required"
        ) from exc

    batch = store._sdk_position_read_adapter.read(
        tuple(store._sdk_exchanges),
        ensure_api_ready=store._ensure_api_ready,
        resolve_route_name=store._resolve_sdk_route_name,
        api_is_current=lambda api: store._api is api,
        timeout_seconds=store._sdk_position_query_timeout(),
    )
    validate_position_read_batch(batch, unavailable=unavailable)

    projected: List[Dict[str, Any]] = []
    for read in batch.routes:
        route = read.exchange_name
        if not position_read_has_positions(read, unavailable=unavailable):
            continue

        def feed_name_for(instrument: Any) -> str:
            matches = set()
            for feed in store._data_feeds:
                private_name = getattr(feed, "_dataname", None)
                params = getattr(feed, "p", None)
                public_name = getattr(params, "dataname", None)
                names = {
                    value
                    for value in (private_name, public_name)
                    if type(value) is str and value and value == value.strip()
                }
                if not names or (
                    private_name is not None
                    and public_name is not None
                    and private_name != public_name
                ):
                    continue
                for name in names:
                    try:
                        if store._sdk_exchange(name) != route:
                            continue
                        configured = store.get_market_instrument_key(name)
                    except Exception:
                        continue
                    if (
                        type(configured) is read.market_instrument_key_type
                        and configured == instrument
                    ):
                        matches.add(name)
            if len(matches) != 1:
                unavailable("account_position_snapshot_instrument_unbound")
            return next(iter(matches))

        def quantity_unit_for(dataname: str, instrument: Any) -> str:
            return configured_position_quantity_unit(
                store.contract_metadata, dataname, instrument,
                alias_fn=contract_metadata_aliases, unavailable=unavailable,
            )

        projected.extend(
            project_account_position_rows(
                read.positions,
                account_position_type=read.account_position_type,
                market_instrument_key_type=read.market_instrument_key_type,
                validate_row=validate_position_read_row,
                feed_name_for=feed_name_for,
                quantity_unit_for=quantity_unit_for,
                unavailable=unavailable,
            )
        )
    return projected


__all__ = ("project_account_position_rows", "project_store_account_positions")
