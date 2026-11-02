"""Project SDK-verified reconciliation DTOs into Store-local neutral records.

The projector owns only the schema conversion.  The Store injects its live
session, route, local-order binding, error-envelope, and one-shot retention
ports so there is one owner for those lifecycles and registries.
"""

from __future__ import annotations

import datetime as _dt

from collections.abc import Mapping
from typing import Any, Callable, Dict, Optional


def project_reconciliation_result(
    api: Any,
    route: str,
    facade: Any,
    handle: Any,
    result: Any,
    *,
    verified: Any,
    incomplete: Callable[[str], Dict[str, Any]],
    facade_is_current: Callable[[Any, str, Any], Any],
    data_name_for: Callable[[str, str, str], Optional[str]],
    bound_order: Callable[[str, str, str, Any], Optional[Mapping]],
    retain_projection: Callable[..., Dict[str, Any]],
    retain_kind: Optional[str] = None,
    order_specific: bool = False,
    order_local_ref: Optional[int] = None,
    expected_correlation: Any = None,
) -> Dict[str, Any]:
    """Project an exact SDK result without retaining Store or account state.

    ``verified`` must be the exact result of the Store's SDK lease verifier.
    The callbacks own all live Store state; this function only checks neutral
    DTO structure and emits the internal Broker projection.
    """
    try:
        # Keep the result contract as an import-time availability guard.
        from bt_api_py.facade_protocol import OrderCorrelation, ReconciliationResult  # noqa: F401
        from bt_api_py.reconciliation_projection_inputs import (
            reconciliation_order_identity,
            reconciliation_projection_inputs,
            valid_reconciliation_fill_binding as _valid_fill_binding,
            valid_reconciliation_fill_economics as _valid_fill_economics,
            valid_reconciliation_order_facts as _valid_order_facts,
            valid_reconciliation_position_economics as _valid_position_economics,
            valid_reconciliation_position_side as _valid_position_side,
            valid_reconciliation_text as _valid_text,
        )
    except ImportError:
        return incomplete("reconciliation_contract_unavailable")

    inputs, input_error = reconciliation_projection_inputs(
        api, route, facade, result, verified, facade_is_current
    )
    if input_error is not None:
        return incomplete(input_error)
    orders, fills, positions, consistency_token, snapshot_id = inputs

    order_envelopes = []
    order_bindings = {}
    open_orders = []
    for row in orders:
        identity, identity_error = reconciliation_order_identity(row)
        if identity_error is not None:
            return incomplete(identity_error)
        order, client_order_id, intent_ref, symbol, instrument_ref, order_id = identity
        try:
            data_name = data_name_for(route, instrument_ref, symbol)
        except Exception:
            data_name = None
        if not _valid_text(data_name):
            return incomplete("reconciliation_order_instrument_unbound")

        try:
            binding = bound_order(route, client_order_id, data_name, api)
        except Exception:
            return incomplete("reconciliation_order_store_binding_mismatch")
        local_ref = None
        correlation = None
        if binding is not None:
            if not isinstance(binding, Mapping):
                return incomplete("reconciliation_order_store_binding_mismatch")
            correlation = binding.get("correlation")
            if (
                binding.get("api") is not api
                or binding.get("exchange_name") != route
                or binding.get("symbol") != data_name
                or binding.get("client_order_id") != client_order_id
                or type(correlation) is not OrderCorrelation
                or getattr(correlation, "client_order_id", None) != client_order_id
                or getattr(correlation, "exchange_name", None) != route
                or getattr(correlation, "symbol", None) != data_name
            ):
                return incomplete("reconciliation_order_store_binding_mismatch")
            local_ref = binding.get("bt_order_ref")
            if type(local_ref) is not int or local_ref <= 0:
                return incomplete("reconciliation_order_local_reference_invalid")

        terminal_confirmed = getattr(order, "terminal_confirmed", None)
        status = getattr(order, "status", None)
        quantity = getattr(order, "quantity", None)
        filled_quantity = getattr(order, "filled_quantity", None)
        quantity_unit = getattr(order, "quantity_unit", None)
        price = getattr(order, "price", None)
        average_price = getattr(order, "average_price", None)
        side = getattr(order, "side", None)
        if (
            (local_ref is None and terminal_confirmed is not True)
            or not _valid_order_facts(
                status, terminal_confirmed, side, quantity, filled_quantity,
                quantity_unit, price, average_price,
            )
        ):
            return incomplete("reconciliation_order_facts_invalid")

        key = (instrument_ref, order_id)
        if key in order_bindings:
            return incomplete("reconciliation_order_identity_ambiguous")
        order_payload = {
            "instrument_ref": instrument_ref,
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "status": status,
            "terminal_confirmed": terminal_confirmed,
            "quantity": quantity,
            "filled_quantity": filled_quantity,
            "quantity_unit": quantity_unit,
            "price": price,
            "average_price": average_price,
            "observed_at": getattr(order, "observed_at", None),
        }
        envelope = {
            "local_ref": local_ref,
            "bt_order_ref": local_ref,
            "client_order_id": client_order_id,
            "intent_ref": intent_ref,
            "data_name": data_name,
            "order": order_payload,
        }
        order_envelopes.append(envelope)
        order_bindings[key] = {
            "local_ref": local_ref,
            "client_order_id": client_order_id,
            "intent_ref": intent_ref,
            "data_name": data_name,
            "order": order,
            "correlation": correlation,
        }
        if terminal_confirmed is not True:
            if local_ref is None:
                return incomplete("reconciliation_open_order_unbound")
            open_orders.append(
                {
                    "local_ref": local_ref,
                    "bt_order_ref": local_ref,
                    "client_order_id": client_order_id,
                    "intent_ref": intent_ref,
                    "data_name": data_name,
                    **order_payload,
                }
            )

    fill_envelopes = []
    seen_fills = set()
    for fill in fills:
        fill_id = getattr(fill, "fill_id", None)
        order_id = getattr(fill, "order_id", None)
        instrument_ref = getattr(fill, "instrument_ref", None)
        parent = order_bindings.get((instrument_ref, order_id))
        quantity = getattr(fill, "quantity", None)
        price = getattr(fill, "price", None)
        commission = getattr(fill, "commission", None)
        if (
            parent is None
            or not _valid_text(fill_id)
            or fill_id in seen_fills
            or not _valid_fill_binding(fill, parent)
            or not _valid_fill_economics(quantity, price, commission)
        ):
            return incomplete("reconciliation_fill_projection_invalid")
        seen_fills.add(fill_id)
        fill_envelopes.append(
            {
                "local_ref": parent["local_ref"],
                "bt_order_ref": parent["local_ref"],
                "client_order_id": parent["client_order_id"],
                "intent_ref": parent["intent_ref"],
                "data_name": parent["data_name"],
                "fill_id": fill_id,
                "order_id": order_id,
                "instrument_ref": instrument_ref,
                "symbol": getattr(fill, "symbol"),
                "side": getattr(fill, "side"),
                "quantity": quantity,
                "quantity_unit": getattr(fill, "quantity_unit"),
                "price": price,
                "fee": getattr(commission, "amount", None),
                "fee_currency": getattr(commission, "currency", None),
                "fee_unit": getattr(commission, "unit", None),
                "timestamp": getattr(fill, "timestamp", None),
            }
        )

    position_envelopes = []
    seen_positions = set()
    for position in positions:
        instrument_ref = getattr(position, "instrument_ref", None)
        symbol = getattr(position, "symbol", None)
        try:
            data_name = data_name_for(route, instrument_ref, symbol)
        except Exception:
            data_name = None
        position_side = getattr(position, "position_side", None)
        quantity = getattr(position, "quantity", None)
        quantity_unit = getattr(position, "quantity_unit", None)
        average_price = getattr(position, "average_price", None)
        position_key = (instrument_ref, position_side)
        if (
            not _valid_text(data_name)
            or not _valid_position_side(position_side)
            or position_key in seen_positions
            or not _valid_position_economics(
                position_side, quantity, quantity_unit, average_price
            )
        ):
            return incomplete("reconciliation_position_projection_invalid")
        seen_positions.add(position_key)
        position_envelopes.append(
            {
                "data_name": data_name,
                "instrument_ref": instrument_ref,
                "symbol": symbol,
                "position_side": position_side,
                "quantity": quantity,
                "quantity_unit": quantity_unit,
                "average_price": average_price,
            }
        )

    if order_specific:
        if (
            type(order_local_ref) is not int
            or order_local_ref <= 0
            or type(expected_correlation) is not OrderCorrelation
            or len(order_envelopes) != 1
        ):
            return incomplete("order_reconciliation_binding_invalid")
        order_envelope = order_envelopes[0]
        order_binding = order_bindings.get(
            (
                order_envelope["order"]["instrument_ref"],
                order_envelope["order"]["order_id"],
            )
        )
        if (
            order_envelope.get("local_ref") != order_local_ref
            or order_envelope.get("client_order_id")
            != expected_correlation.client_order_id
            or order_envelope.get("data_name") != expected_correlation.symbol
            or order_binding is None
            or order_binding.get("intent_ref") != order_envelope.get("intent_ref")
            or order_binding.get("correlation") is not expected_correlation
        ):
            return incomplete("order_reconciliation_result_mismatch")
        if retain_kind not in (None, "order"):
            return incomplete("order_reconciliation_retention_kind_invalid")
        projection = {
            "schema_version": "backtrader.execution.order_reconciliation.v1",
            "kind": "order_reconciliation",
            "complete": True,
            "evidence_complete": True,
            "safe_to_resume": False,
            "snapshot_id": snapshot_id,
            "consistency_digest": consistency_token,
            "local_ref": order_local_ref,
            "bt_order_ref": order_local_ref,
            "client_order_id": order_envelope["client_order_id"],
            "intent_ref": order_envelope["intent_ref"],
            "data_name": order_envelope["data_name"],
            "order": order_envelope["order"],
            "fills": fill_envelopes,
            "reason": "reconciliation_order_verified",
        }
        if retain_kind == "order":
            try:
                retained = retain_projection(
                    "order",
                    projection,
                    api,
                    route,
                    facade,
                    handle,
                    result,
                    expected_correlation,
                    order_local_ref,
                )
            except Exception:
                return incomplete("order_reconciliation_retention_failed")
            if type(retained) is not dict:
                return incomplete("order_reconciliation_retention_failed")
            projection = retained
        return projection

    if retain_kind not in (None, "account"):
        return incomplete("reconciliation_retention_kind_invalid")
    projection = {
        "schema_version": "backtrader.execution.reconciliation.v1",
        "complete": True,
        "safe_to_resume": True,
        "evidence_complete": True,
        "consistency_digest": consistency_token,
        "snapshot_id": snapshot_id,
        "orders": order_envelopes,
        "fills": fill_envelopes,
        "positions": position_envelopes,
        "open_orders": open_orders,
        "reason": "reconciliation_verified",
    }
    if retain_kind == "account":
        try:
            retained = retain_projection(
                "account",
                projection,
                api,
                route,
                facade,
                handle,
                result,
                None,
                None,
            )
        except Exception:
            return incomplete("reconciliation_retention_failed")
        if type(retained) is not dict:
            return incomplete("reconciliation_retention_failed")
        projection = retained
    return projection


_UTC = _dt.timezone.utc


def project_store_reconciliation_result(
    store,
    api,
    route,
    facade,
    handle,
    result,
    *,
    verified=None,
    retain_for_apply=False,
    order_specific=False,
    retain_for_order=False,
    order_local_ref=None,
    expected_correlation=None,
):
    """Delegate neutral row projection while Store retains live bindings."""
    try:
        from bt_api_py.facade_protocol import OrderCorrelation
    except ImportError:
        return store._incomplete_reconciliation_snapshot(
            "reconciliation_contract_unavailable"
        )

    def facade_is_current(candidate_api, candidate_route, expected_facade):
        if (
            candidate_api is not store._api
            or not store._connected
            or not store._started
        ):
            return False
        selected = store._select_reconciliation_route(candidate_api, candidate_route)
        if selected != candidate_route:
            return False
        return store._reconciliation_facade(candidate_api, candidate_route) is expected_facade

    if verified is None:
        try:
            if facade_is_current(api, route, facade):
                verified = store._sdk_reconciliation_adapter.validate_snapshot(
                    facade,
                    handle,
                    result,
                    now=_dt.datetime.now(_UTC),
                )
            else:
                verified = False
        except Exception:
            verified = False

    def data_name_for(candidate_route, instrument_ref, symbol):
        if (
            type(instrument_ref) is not str
            or not instrument_ref
            or instrument_ref != instrument_ref.strip()
            or type(symbol) is not str
            or not symbol
            or symbol != symbol.strip()
        ):
            return None
        candidates = set(store._sdk_routes)
        candidates.update(store.contract_metadata)
        candidates.update(store._subscribed_datanames)
        for feed in store._data_feeds:
            try:
                name = store._extract_dataname(feed)
            except Exception:
                name = None
            if type(name) is str and name:
                candidates.add(name)
        matches = []
        for candidate in candidates:
            if type(candidate) is not str or not candidate:
                continue
            try:
                if store._sdk_exchange(candidate) != candidate_route:
                    continue
                key = store.get_market_instrument_key(candidate)
            except Exception:
                continue
            if (
                key.instrument_id == instrument_ref
                and key.native_symbol == symbol
                and candidate == symbol
            ):
                matches.append(candidate)
        return matches[0] if len(matches) == 1 else None

    def bound_order(candidate_route, client_order_id, data_name, candidate_api):
        binding = store._sdk_execution_bindings.bound_order_by_client_id(
            candidate_route,
            client_order_id,
            api=candidate_api,
            symbol=data_name,
        )
        if binding is None:
            return None
        correlation = binding.get("correlation")
        local_ref = binding.get("bt_order_ref")
        if (
            type(correlation) is not OrderCorrelation
            or type(local_ref) is not int
            or local_ref <= 0
            or correlation.client_order_id != client_order_id
            or correlation.exchange_name != candidate_route
            or correlation.symbol != data_name
        ):
            raise ValueError("reconciliation order binding changed")
        return {
            "api": candidate_api,
            "exchange_name": candidate_route,
            "symbol": data_name,
            "client_order_id": client_order_id,
            "correlation": correlation,
            "bt_order_ref": local_ref,
        }

    def retain_projection(
        kind,
        payload,
        candidate_api,
        candidate_route,
        candidate_facade,
        candidate_handle,
        candidate_result,
        correlation,
        local_ref,
    ):
        if type(payload) is not dict or "store_verification_id" in payload:
            raise ValueError("reconciliation projection cannot be retained")
        if kind == "order":
            if (
                type(correlation) is not OrderCorrelation
                or type(local_ref) is not int
                or local_ref <= 0
            ):
                raise ValueError("order reconciliation binding is invalid")
        elif kind == "account":
            if correlation is not None or local_ref is not None:
                raise ValueError("account reconciliation binding is invalid")
        else:
            raise ValueError("reconciliation projection kind is invalid")

        return store._sdk_execution_bindings.retain_reconciliation_projection(
            kind,
            payload,
            api=candidate_api,
            route=candidate_route,
            facade=candidate_facade,
            handle=candidate_handle,
            result=candidate_result,
            correlation=correlation,
            local_ref=local_ref,
        )

    retain_kind = (
        "order"
        if retain_for_order
        else "account"
        if retain_for_apply
        else None
    )
    return project_reconciliation_result(
        api,
        route,
        facade,
        handle,
        result,
        verified=verified,
        incomplete=store._incomplete_reconciliation_snapshot,
        facade_is_current=facade_is_current,
        data_name_for=data_name_for,
        bound_order=bound_order,
        retain_projection=retain_projection,
        retain_kind=retain_kind,
        order_specific=order_specific,
        order_local_ref=order_local_ref,
        expected_correlation=expected_correlation,
    )


def apply_reconcile_snapshot(store, snapshot: Mapping[str, Any], *, error_type) -> None:
    """Accept only the exact Store projection retained from SDK verification."""
    if not isinstance(snapshot, Mapping):
        raise error_type("reconciliation projection must be a mapping")
    projection_id = snapshot.get("store_verification_id")
    if type(projection_id) is not str or not projection_id:
        raise error_type("reconciliation projection has no Store verification binding")
    entry = store._sdk_execution_bindings.consume_reconciliation_projection(
        projection_id
    )
    if entry is None:
        raise error_type("reconciliation projection binding is unavailable")
    if entry.get("kind") != "account":
        raise error_type("reconciliation projection scope is not account-wide")
    if dict(snapshot) != entry.get("projection"):
        raise error_type("reconciliation projection changed after verification")
    api = entry.get("api")
    route = entry.get("route")
    facade = entry.get("facade")
    handle = entry.get("handle")
    result = entry.get("result")
    try:
        from bt_api_py.facade_protocol import ReconciliationResult
        if (
            api is not store._api
            or type(result) is not ReconciliationResult
            or snapshot.get("complete") is not True
            or snapshot.get("safe_to_resume") is not True
            or snapshot.get("snapshot_id") != result.snapshot_id
            or snapshot.get("consistency_digest") != result.consistency_token
        ):
            raise error_type("reconciliation projection verification is stale")
        store._select_reconciliation_route(api, route)
        if store._reconciliation_facade(api, route) is not facade:
            raise error_type("reconciliation facade changed after verification")
        valid = store._sdk_reconciliation_adapter.validate_snapshot(
            facade,
            handle,
            result,
            now=_dt.datetime.now(_UTC),
        )
    except error_type:
        raise
    except Exception as exc:
        store.sanitize_exception(exc)
        raise error_type("reconciliation SDK verification is unavailable") from None
    if type(valid) is not bool or valid is not True:
        raise error_type("reconciliation SDK verification is no longer valid")


def verify_reconciliation_snapshot(store, snapshot) -> bool:
    """Revalidate one queued account projection before Broker consumes it."""
    try:
        from bt_api_py.facade_protocol import ReconciliationResult
    except ImportError:
        return False
    if type(snapshot) is not dict:
        return False
    verification_id = snapshot.get("store_verification_id")
    if type(verification_id) is not str or not verification_id:
        return False
    entry = store._sdk_execution_bindings.consume_reconciliation_projection(
        verification_id
    )
    if not isinstance(entry, Mapping) or entry.get("kind") != "account":
        return False
    api = entry.get("api")
    route = entry.get("route")
    facade = entry.get("facade")
    handle = entry.get("handle")
    result = entry.get("result")
    try:
        if (
            dict(snapshot) != entry.get("projection")
            or snapshot.get("complete") is not True
            or snapshot.get("safe_to_resume") is not True
            or type(snapshot.get("consistency_digest")) is not str
            or not snapshot.get("consistency_digest")
            or api is not store._api
            or not store._started
            or not store._connected
            or store._sdk_reconciliation_adapter.is_request_handle(handle) is not True
            or type(result) is not ReconciliationResult
            or snapshot.get("snapshot_id") != result.snapshot_id
            or snapshot.get("consistency_digest") != result.consistency_token
        ):
            return False
        store._select_reconciliation_route(api, route)
        if store._reconciliation_facade(api, route) is not facade:
            return False
        valid = store._sdk_reconciliation_adapter.validate_snapshot(
            facade,
            handle,
            result,
            now=_dt.datetime.now(_UTC),
        )
    except Exception:
        return False
    return type(valid) is bool and valid is True


def verify_order_reconciliation(store, correlation, response) -> bool:
    """Verify one queued order projection before Broker applies it.

    The response mapping is only a Store-local envelope.  Broker may apply
    it to one Backtrader order only after this one-shot check revalidates
    the exact SDK result, route facade, correlation and current provider
    lease.  This method never promotes an order result to account-level
    ``safe_to_resume`` evidence.
    """
    try:
        from bt_api_py.facade_protocol import (
            OrderCorrelation,
            ReconciliationResult,
        )
    except ImportError:
        return False
    if type(correlation) is not OrderCorrelation or type(response) is not dict:
        return False
    verification_id = response.get("store_verification_id")
    if type(verification_id) is not str or not verification_id:
        return False
    entry = store._sdk_execution_bindings.consume_reconciliation_projection(
        verification_id
    )
    if not isinstance(entry, Mapping) or entry.get("kind") != "order":
        return False
    api = entry.get("api")
    route = entry.get("route")
    facade = entry.get("facade")
    handle = entry.get("handle")
    result = entry.get("result")
    local_ref = entry.get("local_ref")
    try:
        exact_handle = store._sdk_reconciliation_adapter.is_request_handle(handle)
    except ImportError:
        return False
    if exact_handle is not True or type(result) is not ReconciliationResult:
        return False
    try:
        if (
            dict(response) != entry.get("projection")
            or entry.get("correlation") is not correlation
            or type(local_ref) is not int
            or local_ref <= 0
            or response.get("kind") != "order_reconciliation"
            or response.get("complete") is not True
            or response.get("evidence_complete") is not True
            or response.get("safe_to_resume") is not False
            or response.get("local_ref") != local_ref
            or response.get("bt_order_ref") != local_ref
            or response.get("client_order_id") != correlation.client_order_id
            or response.get("data_name") != correlation.symbol
            or type(response.get("consistency_digest")) is not str
            or not response.get("consistency_digest")
            or response.get("snapshot_id") != result.snapshot_id
            or response.get("consistency_digest") != result.consistency_token
            or api is not store._api
            or not store._started
            or not store._connected
        ):
            return False
        store._select_reconciliation_route(api, route)
        if store._reconciliation_facade(api, route) is not facade:
            return False
        binding = store._sdk_execution_bindings.by_correlation(correlation)
        if (
            binding is None
            or binding.get("bt_order_ref") != local_ref
            or not store._sdk_execution_bindings.binding_matches(
                binding,
                correlation=correlation,
                api=api,
                exchange_name=route,
                symbol=correlation.symbol,
                states={"prepared", "queued", "completed", "unknown"},
                require_all_indexes=True,
            )
        ):
            return False
        valid = store._sdk_reconciliation_adapter.validate_snapshot(
            facade,
            handle,
            result,
            now=_dt.datetime.now(_UTC),
        )
    except Exception:
        return False
    return type(valid) is bool and valid is True


__all__ = (
    "project_reconciliation_result", "project_store_reconciliation_result",
    "apply_reconcile_snapshot", "verify_reconciliation_snapshot",
    "verify_order_reconciliation",
)
