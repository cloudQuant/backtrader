"""Thin shared Store base class for Direct and Gateway bt_api_py live stores.

Intentionally defines NO class-level ``params`` tuple (``StoreParams`` does not
merge parent class ``params`` tuples). All configuration enters through explicit
``__init__`` arguments and an immutable ``LiveRunBinding``.
"""

from __future__ import annotations

from typing import Any, Optional

from ._btapi_errors import LiveCompositionError
from .btapi_composition import LiveRunBinding, verify_run_binding
from .livestore import LiveStoreBase

__all__ = ["BaseBtApiStore"]


class BaseBtApiStore(LiveStoreBase):
    """Shared base class for ``BtApiStore``, ``DirectBtApiStore``, and ``GatewayBtApiStore``."""

    BrokerCls: Any = None
    DataCls: Any = None

    def __init__(self) -> None:
        super().__init__()
        self._run_binding: Optional[LiveRunBinding] = None

    @property
    def _broker(self) -> Any:
        """Compatibility alias for the inherited single broker field."""
        return self.broker

    @_broker.setter
    def _broker(self, broker: Any) -> None:
        self.broker = broker

    @property
    def _data_feeds(self) -> list:
        """Compatibility alias for the inherited Store data list."""
        if self.datas is None:
            self.datas = []
        return self.datas

    @_data_feeds.setter
    def _data_feeds(self, feeds: Optional[list]) -> None:
        self.datas = feeds

    @property
    def run_binding(self) -> Optional[LiveRunBinding]:
        """Immutable composition-root run binding for this Store, if bound."""
        return self._run_binding

    @property
    def live_mode(self) -> Optional[str]:
        """Explicit live mode ('direct' | 'gateway') when bound, else inferred compat mode."""
        if self._run_binding is not None:
            return self._run_binding.mode
        if getattr(self, "_gateway_mode", False):
            return "gateway"
        if getattr(self, "_sdk_mode", False):
            return "direct"
        return None

    @property
    def is_direct_mode(self) -> bool:
        return self.live_mode == "direct"

    @property
    def is_gateway_mode(self) -> bool:
        return self.live_mode == "gateway"

    def verify_run_binding_for(self, candidate: Any) -> None:
        """Fail closed if *candidate* carries an incompatible LiveRunBinding."""
        if self._run_binding is None:
            return
        if isinstance(candidate, LiveRunBinding):
            verify_run_binding(self._run_binding, candidate)
            return
        other = getattr(candidate, "run_binding", getattr(candidate, "_run_binding", None))
        if other is None:
            raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="missing_component_binding")
        verify_run_binding(self._run_binding, other)
