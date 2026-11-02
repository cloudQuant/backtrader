"""Project a neutral SDK order request onto a Store-local BT contract."""

from __future__ import annotations

from typing import Any, Dict


def execution_contract_from_order_request(request: Any) -> Dict[str, Any]:
    """Project a typed neutral order request into the Store-local BT contract."""

    def public_value(value: Any) -> Any:
        return getattr(value, "value", value)

    return {
        "side": str(public_value(request.side)).strip().lower(),
        "position_side": public_value(getattr(request, "position_side", None)),
        "offset": public_value(getattr(request, "offset", None)),
        "position_mode": public_value(getattr(request, "position_mode", None)),
        "hedge_class": getattr(request, "hedge_class", None),
        "quantity_unit": str(public_value(request.quantity_unit)).strip().lower(),
        "requested_quantity": str(request.quantity),
        "reduce_only": bool(request.reduce_only),
        "strategy_identity_sha256": getattr(request, "strategy_identity_sha256", None),
        "execution_cycle_id": getattr(request, "execution_cycle_id", None),
        "execution_role": getattr(request, "execution_role", None),
    }


__all__ = (
    "execution_contract_from_order_request",
)
