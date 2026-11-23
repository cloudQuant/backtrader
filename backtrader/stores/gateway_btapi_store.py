"""Strict Gateway-mode bt_api_py Store implementation.

Implements the frozen Gateway mode boundary (D62S-01 through D62S-09):
- Accepts only strict Gateway configuration (``gateway_strategy`` with mandatory
  non-'none' ``risk`` and ``execution``, no ``DIRECT_PATH`` bypass, CTP routes
  only per D63-10 / D62S-08c, no local ``calendars.feed_scope``).
- Rejects all Direct provider keys, hybrid routing keys, and service passthrough
  keys before any I/O.
- Validates and holds neutral ``GatewayReadinessProof`` without opening any
  Monitor or Runtime RPC port inside the strategy process (D62S-02).
- Maintains zero direct imports of optional SDK service subpackages.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Optional

from ._btapi_errors import LiveCompositionError
from .btapi_composition import (
    GatewayReadinessProof,
    LiveRunBinding,
    _reject_gateway_forbidden_keys,
    _validate_strict_gateway_section,
    validate_gateway_readiness_proof,
    verify_run_binding,
)
from .btapistore import BtApiStore

__all__ = ["GatewayBtApiStore"]


class GatewayBtApiStore(BtApiStore):
    """Concrete Gateway-mode live Store (strict five-component deployment contract)."""

    def __init__(
        self,
        *,
        config: Mapping[str, Any],
        gateway_host: Any,
        gateway_security_profiles: Mapping[str, Any],
        gateway_readiness_proof: Any = None,
        gateway_api_factory: Any = None,
        expected_run_id: Optional[str] = None,
        calendar_config_file: Any = None,
        calendar_config: Any = None,
        cash: float = 0.0,
        value: Optional[float] = None,
        preserve_raw_bars: bool = False,
        contract_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        autostart: bool = False,
        run_binding: Optional[LiveRunBinding] = None,
        **kwargs: Any,
    ) -> None:
        if not isinstance(config, Mapping):
            raise LiveCompositionError("MODE_REQUIRED", detail="config_not_mapping")
        cfg_copy: Dict[str, Any] = dict(config)
        if "mode" in cfg_copy:
            if cfg_copy["mode"] != "gateway":
                raise LiveCompositionError("MODE_CONFLICT", detail="gateway_store_mode_mismatch")
            cfg_copy.pop("mode")

        raw_proof = gateway_readiness_proof
        if raw_proof is None and "gateway_readiness_proof" in cfg_copy:
            raw_proof = cfg_copy.pop("gateway_readiness_proof")

        _reject_gateway_forbidden_keys(cfg_copy, kwargs)
        _validate_strict_gateway_section(cfg_copy)

        if run_binding is None:
            broker_cfg = cfg_copy.get("broker") if isinstance(cfg_copy.get("broker"), Mapping) else {}
            mdo = bool(broker_cfg.get("market_data_only", cfg_copy.get("market_data_only", False)))
            pos_mode = str(broker_cfg.get("position_mode", "net"))
            gw_sec = cfg_copy["gateway_strategy"]
            gw_binding = gw_sec.get("binding") if isinstance(gw_sec.get("binding"), Mapping) else {}
            run_binding = LiveRunBinding(
                mode="gateway",
                position_mode=pos_mode,
                market_data_only=mdo,
                account_scope=(
                    gw_binding.get("account_scope")
                    if isinstance(gw_binding.get("account_scope"), str)
                    else None
                ),
                strategy_scope=(
                    gw_binding.get("strategy_scope")
                    if isinstance(gw_binding.get("strategy_scope"), str)
                    else None
                ),
                route=(
                    gw_sec.get("exchange_name")
                    if isinstance(gw_sec.get("exchange_name"), str)
                    else None
                ),
            )
        elif not isinstance(run_binding, LiveRunBinding) or run_binding.mode != "gateway":
            raise LiveCompositionError(
                "RUN_BINDING_MISMATCH", detail="gateway_store_requires_gateway_binding"
            )

        validated_proof: Optional[GatewayReadinessProof] = None
        if raw_proof is not None:
            validated_proof = validate_gateway_readiness_proof(
                raw_proof,
                expected_binding=run_binding,
                expected_run_id=expected_run_id,
                require_ready_for_write=not run_binding.market_data_only,
            )

        # Strip top-level market_data_only so legacy BtApiStore._exec_keys check
        # does not misclassify Gateway read-only rehearsal as Direct execution config.
        cfg_copy.pop("market_data_only", None)

        self._gateway_api_factory = gateway_api_factory
        super().__init__(
            provider="btapi",
            config=cfg_copy,
            cash=cash,
            value=value,
            preserve_raw_bars=preserve_raw_bars,
            contract_metadata=contract_metadata,
            autostart=autostart,
            gateway_host=gateway_host,
            gateway_security_profiles=gateway_security_profiles,
            calendar_config_file=calendar_config_file,
            calendar_config=calendar_config,
            run_binding=run_binding,
            gateway_readiness_proof=validated_proof,
            **kwargs,
        )

    def getdata(self, *args: Any, **kwargs: Any) -> Any:
        """Return a GatewayBtApiFeed bound to this Gateway Store."""
        from ..feeds.direct_btapi_feed import DirectBtApiFeed
        from ..feeds.gateway_btapi_feed import GatewayBtApiFeed

        data_cls = kwargs.get("data_cls", self.DataCls)
        if data_cls is None:
            kwargs["data_cls"] = GatewayBtApiFeed
        elif isinstance(data_cls, type) and issubclass(data_cls, DirectBtApiFeed):
            raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="direct_feed_on_gateway_store")
        return super().getdata(*args, **kwargs)

    @property
    def gateway_readiness_proof(self) -> Optional[GatewayReadinessProof]:
        """Most recently validated GatewayReadinessProof snapshot."""
        return self._gateway_readiness_proof

    def update_gateway_readiness_proof(
        self,
        proof: Any,
        *,
        expected_run_id: Optional[str] = None,
        now_ns: Optional[int] = None,
        require_ready_for_write: Optional[bool] = None,
    ) -> GatewayReadinessProof:
        """Validate and store an updated GatewayReadinessProof snapshot."""
        assert self._run_binding is not None
        need_write = (
            (not self._run_binding.market_data_only)
            if require_ready_for_write is None
            else require_ready_for_write
        )
        validated = validate_gateway_readiness_proof(
            proof,
            expected_binding=self._run_binding,
            expected_run_id=expected_run_id,
            now_ns=now_ns,
            require_ready_for_write=need_write,
        )
        self._gateway_readiness_proof = validated
        return validated

    def require_gateway_readiness_proof(
        self,
        *,
        expected_run_id: Optional[str] = None,
        now_ns: Optional[int] = None,
        require_ready_for_write: bool = True,
    ) -> GatewayReadinessProof:
        """Fail closed unless a valid, non-expired GatewayReadinessProof is active."""
        if self._gateway_readiness_proof is None:
            raise LiveCompositionError(
                "GATEWAY_READINESS_COMPONENT_NOT_READY", detail="proof_missing"
            )
        return validate_gateway_readiness_proof(
            self._gateway_readiness_proof,
            expected_binding=self._run_binding,
            expected_run_id=expected_run_id,
            now_ns=now_ns,
            require_ready_for_write=require_ready_for_write,
        )

    def verify_component_binding(self, candidate: Any) -> None:
        """Verify that *candidate* carries this exact Gateway LiveRunBinding."""
        assert self._run_binding is not None
        other = (
            candidate
            if isinstance(candidate, LiveRunBinding)
            else getattr(candidate, "run_binding", getattr(candidate, "_run_binding", None))
        )
        verify_run_binding(self._run_binding, other)
