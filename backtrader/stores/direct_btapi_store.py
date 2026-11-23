"""Strict Direct-mode bt_api_py Store implementation.

Owns the Iteration 62 Direct connection lifecycle only:
- Rejects all Gateway, hybrid routing (path 5), legacy managed execution
  (paths 2/3), and service passthrough keys (path 6: ``market_runtime_factory``,
  ``forwarding_config``, ``transport_mode``) before any I/O.
- Rejects non-live tools (``ServiceReadProxy``, ``local_replay``).
- Enforces immutable ``LiveRunBinding(mode='direct', ...)`` and read-only
  rehearsal fail-closed semantics (``market_data_only=True`` or
  ``write_admission={route: False}``).
- Maintains zero direct imports of optional SDK service subpackages.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Iterable, Optional

from ._btapi_errors import LiveCompositionError
from .btapi_composition import (
    LiveRunBinding,
    _is_service_read_proxy_instance,
    _reject_direct_forbidden_keys,
    verify_run_binding,
)
from .btapistore import BtApiStore

__all__ = ["DirectBtApiStore"]


class DirectBtApiStore(BtApiStore):
    """Concrete Direct-mode live Store (no Gateway / service passthrough surface)."""

    def __init__(
        self,
        provider: str = "btapi",
        api: Any = None,
        api_cls: Any = None,
        config: Optional[Dict[str, Any]] = None,
        api_kwargs: Optional[Dict[str, Any]] = None,
        cash: float = 0.0,
        value: Optional[float] = None,
        account_cache_ttl: float = 0.0,
        positions_cache_ttl: float = 0.0,
        open_orders_cache_ttl: float = 0.0,
        positions: Optional[Iterable[Dict[str, Any]]] = None,
        historical_bars: Optional[Dict[str, Iterable[Any]]] = None,
        live_bars: Optional[Dict[str, Iterable[Any]]] = None,
        preserve_raw_bars: bool = False,
        contract_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        backend: Optional[str] = None,
        autostart: bool = False,
        calendar_config_file: Any = None,
        calendar_config: Any = None,
        calendar_ctp_routes: Any = None,
        run_binding: Optional[LiveRunBinding] = None,
        **kwargs: Any,
    ) -> None:
        if _is_service_read_proxy_instance(api):
            raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="service_read_proxy")

        cfg_copy: Dict[str, Any] = dict(config) if isinstance(config, Mapping) else {}
        if config is not None and not isinstance(config, Mapping):
            raise LiveCompositionError("MODE_CONFLICT", detail="config_not_mapping")
        if "mode" in cfg_copy:
            if cfg_copy["mode"] != "direct":
                raise LiveCompositionError("MODE_CONFLICT", detail="direct_store_mode_mismatch")
            cfg_copy.pop("mode")

        extra_check: Dict[str, Any] = dict(kwargs)
        extra_check["provider"] = provider
        if backend is not None:
            extra_check["backend"] = backend
        if api_kwargs is not None:
            if not isinstance(api_kwargs, Mapping):
                raise LiveCompositionError("MODE_CONFLICT", detail="api_kwargs_not_mapping")
            extra_check["api_kwargs"] = dict(api_kwargs)
        _reject_direct_forbidden_keys(cfg_copy, extra_check)

        if run_binding is None:
            broker_cfg = cfg_copy.get("broker") if isinstance(cfg_copy.get("broker"), Mapping) else {}
            mdo = bool(broker_cfg.get("market_data_only", cfg_copy.get("market_data_only", False)))
            pos_mode = str(broker_cfg.get("position_mode", "net"))
            ex_kwargs = cfg_copy.get("exchange_kwargs")
            route = (
                next(iter(ex_kwargs))
                if isinstance(ex_kwargs, Mapping) and len(ex_kwargs) == 1
                else None
            )
            run_binding = LiveRunBinding(
                mode="direct",
                position_mode=pos_mode,
                market_data_only=mdo,
                route=route if isinstance(route, str) else None,
            )
        elif not isinstance(run_binding, LiveRunBinding) or run_binding.mode != "direct":
            raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="direct_store_requires_direct_binding")

        super().__init__(
            provider=provider,
            api=api,
            api_cls=api_cls,
            config=cfg_copy,
            api_kwargs=dict(api_kwargs) if api_kwargs is not None else None,
            cash=cash,
            value=value,
            account_cache_ttl=account_cache_ttl,
            positions_cache_ttl=positions_cache_ttl,
            open_orders_cache_ttl=open_orders_cache_ttl,
            positions=positions,
            historical_bars=historical_bars,
            live_bars=live_bars,
            preserve_raw_bars=preserve_raw_bars,
            contract_metadata=contract_metadata,
            backend=backend,
            autostart=autostart,
            calendar_config_file=calendar_config_file,
            calendar_config=calendar_config,
            calendar_ctp_routes=calendar_ctp_routes,
            run_binding=run_binding,
            **kwargs,
        )
        if run_binding.market_data_only:
            self._direct_write_mode = False
            self._direct_write_routes = frozenset()

    def gateway_instrument_status(self, route: Any, instrument: Any, *, timeout_seconds: float = 5.0) -> Any:
        """Gateway instrument status queries are unavailable on DirectBtApiStore."""
        raise LiveCompositionError("MODE_CONFLICT", detail="gateway_instrument_status_on_direct_store")

    def verify_component_binding(self, candidate: Any) -> None:
        """Verify that *candidate* carries this exact Direct LiveRunBinding."""
        assert self._run_binding is not None
        other = (
            candidate
            if isinstance(candidate, LiveRunBinding)
            else getattr(candidate, "run_binding", getattr(candidate, "_run_binding", None))
        )
        verify_run_binding(self._run_binding, other)
