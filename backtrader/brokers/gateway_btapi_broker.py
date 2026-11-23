"""Strict Gateway-mode bt_api_py Broker implementation (T-033).

Implements the frozen Scheme A + Scheme A2 Gateway execution boundary:
- Exposes ONLY shared Broker parameters (strips all 24 ``direct_params()``
  keys from its parameter descriptors and rejects them on construction with
  ``GATEWAY_CONFIGURATION_CONFLICT``).
- Enforces immutable ``LiveRunBinding(mode='gateway', ...)`` and rejects
  Direct Stores.
- Checkpoint 1 pre-dispatch gate (``contracts/readiness_and_auth_proof_v1.md``):
  verifies valid non-expired ``GatewayReadinessProof``, enforces mandatory
  Risk (``D62S-04``) and Execution (``D62S-05``), forbids ``DIRECT_PATH``
  bypass (``GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN``), refuses BOTH new opens
  AND close/reduce orders when Execution is unavailable (``D62S-09b``), blocks
  new opens when ``monitor_stop_new_active=True`` while allowing closes and
  ``direct.delegated_cancel``, and keeps running open/close/cancel unaffected
  when Runtime supervision control disconnects (``D62S-09c``).
- Emits canonical :mod:`backtrader.live_trading.run_status` shutdown summaries
  directly (retiring ``gateway_client_runner.contract_broker_summary``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..parameters import ParameterDescriptor
from ..stores._btapi_errors import LiveCompositionError
from ..stores.btapi_composition import (
    GatewayReadinessProof,
    LiveRunBinding,
    validate_gateway_readiness_proof,
    verify_run_binding,
)
from .base_btapi_broker import (
    DIRECT_ONLY_BROKER_PARAM_NAMES,
    SHARED_BTAPI_BROKER_PARAMS,
    normalize_shutdown_summary,
)
from .btapibroker import BtApiBroker

__all__ = ["GatewayBtApiBroker"]

_CLOSE_OFFSETS = frozenset({"close", "close_today", "close_yesterday", "reduce", "reduce_only"})


class GatewayBtApiBroker(BtApiBroker):
    """Concrete Gateway-mode live Broker (strict five-component Scheme A + A2)."""

    params = SHARED_BTAPI_BROKER_PARAMS

    @classmethod
    def _compute_parameter_descriptors(cls) -> Dict[str, ParameterDescriptor]:
        """Strip Direct-only parameter descriptors inherited via compat BtApiBroker."""
        descriptors = super()._compute_parameter_descriptors()
        return {
            name: desc
            for name, desc in descriptors.items()
            if name not in DIRECT_ONLY_BROKER_PARAM_NAMES
        }

    def __init__(self, **kwargs: Any) -> None:
        explicit_binding: Optional[LiveRunBinding] = kwargs.pop("run_binding", None)
        expected_run_id: Optional[str] = kwargs.pop("expected_run_id", None)
        require_readiness_proof: bool = bool(kwargs.pop("require_readiness_proof", False))

        # Reject Direct-only parameters before ParameterizedBase touches them.
        for key in sorted(DIRECT_ONLY_BROKER_PARAM_NAMES):
            if key in kwargs:
                raise LiveCompositionError("GATEWAY_CONFIGURATION_CONFLICT", detail=key)

        store = kwargs.get("store")
        from ..stores.direct_btapi_store import DirectBtApiStore

        if isinstance(store, DirectBtApiStore) or (
            store is not None
            and not getattr(store, "_gateway_mode", False)
            and getattr(store, "live_mode", None) == "direct"
        ):
            raise LiveCompositionError(
                "RUN_BINDING_MISMATCH", detail="direct_store_on_gateway_broker"
            )

        store_binding = getattr(store, "run_binding", None) if store is not None else None
        if explicit_binding is not None:
            if (
                not isinstance(explicit_binding, LiveRunBinding)
                or explicit_binding.mode != "gateway"
            ):
                raise LiveCompositionError(
                    "RUN_BINDING_MISMATCH", detail="gateway_broker_binding_mode"
                )
            if store_binding is not None:
                verify_run_binding(store_binding, explicit_binding)
            resolved_binding = explicit_binding
        elif store_binding is not None:
            if store_binding.mode != "gateway":
                raise LiveCompositionError(
                    "RUN_BINDING_MISMATCH", detail="gateway_broker_store_mode"
                )
            resolved_binding = store_binding
        else:
            resolved_binding = LiveRunBinding(
                mode="gateway",
                position_mode=str(kwargs.get("position_mode", "net")),
                market_data_only=bool(kwargs.get("market_data_only", False)),
            )

        if resolved_binding.market_data_only:
            kwargs["market_data_only"] = True

        super().__init__(run_binding=resolved_binding, **kwargs)
        self._strict_gateway_no_direct_path = True
        self._expected_run_id = expected_run_id
        self._require_readiness_proof = require_readiness_proof
        self._runtime_control_connected = True

    def set_runtime_control_connected(self, connected: bool) -> None:
        """Record Runtime supervisor channel connectivity (D62S-09c: informational only)."""
        self._runtime_control_connected = bool(connected)

    @property
    def runtime_control_connected(self) -> bool:
        return self._runtime_control_connected

    def check_gateway_dispatch_preconditions(
        self,
        *,
        action: str = "open",
        now_ns: Optional[int] = None,
    ) -> Optional[GatewayReadinessProof]:
        """Checkpoint 1 pre-dispatch gate implementing D62S-01..D62S-05 & D62S-09b/c.

        ``action`` is one of ``"open"``, ``"close"``, or ``"cancel"``.
        - ``"cancel"`` (``direct.delegated_cancel``): remains allowed even when
          Risk or Execution is unavailable, or Monitor ``STOP_NEW`` is active, or
          Runtime control is disconnected; still blocked if ``market_data_only=True``.
        - ``"open"`` and ``"close"``: require ``mode == "gateway"``,
          ``not market_data_only``, Risk ``READY`` (D62S-04), Execution ``READY``
          with ``execution_direct_path_disabled=True`` (D62S-05 / D62S-09b), and
          strategy principal stripped of ``SUBMIT``/``RESERVE`` (D62S-03).
          ``"open"`` additionally fails closed when ``monitor_stop_new_active=True``.
          Runtime control disconnection (``runtime_control_connected=False``) NEVER
          blocks an already-running strategy's open/close/cancel (D62S-09c).
        """
        if self._run_binding is None or self._run_binding.mode != "gateway":
            raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="non_gateway_broker")
        if self.p.market_data_only or self._run_binding.market_data_only:
            raise LiveCompositionError("MODE_CONFLICT", detail="market_data_only_forbids_write")

        norm_action = str(action or "open").strip().lower()
        if norm_action in _CLOSE_OFFSETS:
            norm_action = "close"

        proof = getattr(self.store, "gateway_readiness_proof", None) if self.store is not None else None
        if proof is None:
            if self._require_readiness_proof:
                raise LiveCompositionError(
                    "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="proof_missing"
                )
            return None

        if norm_action == "cancel":
            # D62S-04 / D62S-09b: delegated_cancel remains allowed during Risk/Execution outage,
            # while still checking Gateway reachability/version/principal/delegated_cancel_enabled.
            parsed = validate_gateway_readiness_proof(
                proof,
                expected_binding=self._run_binding,
                expected_run_id=self._expected_run_id,
                now_ns=now_ns,
                require_ready_for_write=False,
                allow_cancel_during_outage=True,
            )
            return parsed

        # Open and close both require full Risk + Execution readiness (D62S-04, D62S-05, D62S-09b).
        parsed = validate_gateway_readiness_proof(
            proof,
            expected_binding=self._run_binding,
            expected_run_id=self._expected_run_id,
            now_ns=now_ns,
            require_ready_for_write=True,
        )
        if norm_action == "open" and parsed.monitor_stop_new_active:
            raise LiveCompositionError(
                "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="monitor_stop_new_active"
            )
        return parsed

    def get_shutdown_summary(self) -> Any:
        raw = super().get_shutdown_summary()
        return normalize_shutdown_summary(raw, mode="gateway")
