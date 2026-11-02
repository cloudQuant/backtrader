"""Pure projections for Backtrader order requests and broker events.

This module owns no Store, queue, facade, or account state. It translates the
public Backtrader order surface into neutral SDK requests and normalized Broker
updates into Store runtime-event payloads. The Store remains the sole owner of
notification publication and lifecycle.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def extract_dataname(data: Any) -> str:
    """Extract the configured feed name used by Backtrader's order API."""
    return (
        getattr(data, "_name", None)
        or getattr(data, "_dataname", None)
        or getattr(getattr(data, "p", None), "dataname", None)
        or getattr(data, "_dataname", None)
        or repr(data)
    )


def order_type_to_payload(order: Any) -> str:
    """Return the canonical generic order type for a Backtrader order."""
    from ..order import OrderBase

    exectype = getattr(order, "exectype", None)
    mapping = {
        OrderBase.Market: "market",
        OrderBase.Close: "market",
        OrderBase.Limit: "limit",
        OrderBase.Stop: "stop",
        OrderBase.StopLimit: "stop_limit",
    }
    if exectype in mapping:
        return mapping[exectype]

    name = str(order.getordername() or "").strip().lower()
    name = name.replace("-", "_").replace(" ", "_")
    aliases = {
        "stoplimit": "stop_limit",
        "stoptraillimit": "stop_trail_limit",
        "stoptrail": "stop_trail",
    }
    return aliases.get(name, name)


def order_to_payload(order: Any) -> Dict[str, Any]:
    """Project one Backtrader order into the Store's neutral request mapping."""
    from ..order import OrderBase

    order_type = order_type_to_payload(order)
    if getattr(order, "exectype", None) == OrderBase.Market or order_type == "market":
        price = None
    elif order_type == "stop_limit":
        price = order.pricelimit if order.pricelimit is not None else order.created.price
        if price is not None and float(price) <= 0:
            price = None
    else:
        price = order.price if order.price is not None else order.created.price
        if price is not None and float(price) <= 0:
            price = order.created.price if order.created.price is not None else None

    data_name = extract_dataname(order.data)
    payload = {
        "symbol": data_name,
        "data_name": data_name,
        "bt_order_ref": getattr(order, "ref", None),
        "side": "buy" if order.isbuy() else "sell",
        "size": abs(order.size),
        "price": price,
        "order_type": order_type,
        "valid": order.valid,
        "tradeid": getattr(order, "tradeid", 0),
    }

    if order.pricelimit is not None:
        payload["pricelimit"] = order.pricelimit
        payload["limit_price"] = order.pricelimit
    if order_type in {"stop", "stop_limit"} and order.price is not None:
        payload["stop_price"] = order.price
        extra_data = dict(payload.get("extra_data") or {})
        extra_data.setdefault("aux_price", order.price)
        payload["extra_data"] = extra_data

    info = getattr(order, "info", {})
    get_info = getattr(info, "get", lambda *_args, **_kwargs: None)
    for key in ("offset", "position_side"):
        value = get_info(key)
        if value:
            payload[key] = value

    for key in (
        "time_in_force",
        "reduce_only",
        "quantity_unit",
        "position_id",
        "position_mode",
        "execution_cycle_id",
        "execution_role",
        "hedge_class",
        "strategy_identity_sha256",
    ):
        value = get_info(key)
        if value is not None:
            payload[key] = value

    return payload


def project_broker_runtime_event(
    update: Dict[str, Any],
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Project one normalized Broker update into a Store event call.

    The returned pair is ``(event_type, keyword_arguments)`` for
    ``BtApiStore.emit_runtime_event``. Unknown update kinds remain ignored, as
    they were by the Store's previous inline dispatcher.
    """
    kind = str(update.get("kind") or "").lower()
    details = {
        "data_name": update.get("data_name"),
        "side": update.get("side"),
        "offset": update.get("offset"),
        "size": update.get("size"),
        "price": update.get("price"),
        "trade_id": update.get("trade_id"),
    }
    for key in (
        "order_id",
        "external_order_id",
        "order_ref",
        "client_order_id",
        "bt_order_ref",
        "filled",
        "remaining",
        "position_side",
        "trade_type",
        "liquidity",
        "commission_role",
        "commission",
        "comm",
        "fee",
        "fees",
        "trade_fee",
        "trade_commission",
        "commission_amount",
        "fee_currency",
        "commission_asset",
        "trade_fee_symbol",
        "status_msg",
        "error_code",
    ):
        value = update.get(key)
        if value not in (None, ""):
            details[key] = value
    for key, value in dict(update.get("details") or {}).items():
        if key not in details or details.get(key) in (None, ""):
            details[key] = value

    if kind == "order":
        status = str(update.get("status") or "submitted")
        event_type = {
            "submitted": "order_status_submitted",
            "accepted": "order_status_accepted",
            "partial": "order_status_partial",
            "completed": "order_status_completed",
            "canceled": "order_status_canceled",
            "rejected": "order_reject_remote",
        }.get(status, "order_status_update")
        return event_type, {
            "level": "ERROR" if status == "rejected" else "INFO",
            "status": status,
            "order_ref": update.get("external_order_id") or update.get("order_ref"),
            "error_msg": str(update.get("status_msg") or ""),
            "details": details,
        }

    if kind == "trade":
        return "trade_execution", {
            "status": "completed",
            "order_ref": update.get("external_order_id") or update.get("order_ref"),
            "details": details,
        }

    if kind == "position":
        details.update(
            {
                "position_id": update.get("position_id"),
                "volume": update.get("volume"),
                "profit": update.get("profit"),
                "commission": update.get("commission"),
            }
        )
        return "position_update", {"status": "updated", "details": details}

    if kind == "error":
        event_type = "order_reject_remote" if update.get("order_ref") else "store_error"
        return event_type, {
            "level": "ERROR",
            "status": "error",
            "order_ref": update.get("order_ref"),
            "error_code": str(update.get("error_code") or ""),
            "error_msg": str(update.get("error_msg") or ""),
            "details": details,
        }

    return None


__all__ = (
    "extract_dataname",
    "order_to_payload",
    "order_type_to_payload",
    "project_broker_runtime_event",
)
