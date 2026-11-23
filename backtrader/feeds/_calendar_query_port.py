"""Mode-specific trading calendar query ports (T-026).

Enforces single-source calendar discipline across Direct and Gateway modes:
- ``LocalCalendarQueryPort``: Direct mode reads ``calendars.root`` +
  ``calendars.feed_scope`` (or Feed ``calendar_*`` parameters).
- ``GatewayCalendarQueryPort``: Gateway mode reads ``gateway_strategy.calendar_settings``
  only and rejects local ``calendars.feed_scope`` / ``feed.calendar_*`` overrides
  with ``CALENDAR_SCOPE_CONFLICT``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Optional, Tuple
from typing_extensions import Protocol, runtime_checkable

from ..stores._btapi_errors import LiveCompositionError

__all__ = [
    "CALENDAR_PARAM_FIELDS",
    "CalendarQueryPort",
    "GatewayCalendarQueryPort",
    "LocalCalendarQueryPort",
]

CALENDAR_PARAM_FIELDS: Tuple[str, ...] = ("route", "venue", "kind", "product", "contract")


@runtime_checkable
class CalendarQueryPort(Protocol):
    """Neutral read-only calendar port owned by a live Feed."""

    @property
    def mode(self) -> str: ...

    def validate_feed_scope(
        self,
        calendar_scope: Mapping[str, Optional[str]],
        *,
        config: Optional[Mapping[str, Any]] = None,
    ) -> None: ...


class LocalCalendarQueryPort:
    """Direct-mode local calendar scope validator (calendars.root + feed_scope)."""

    mode: str = "direct"

    def validate_feed_scope(
        self,
        calendar_scope: Mapping[str, Optional[str]],
        *,
        config: Optional[Mapping[str, Any]] = None,
    ) -> None:
        for field_name in CALENDAR_PARAM_FIELDS:
            value = calendar_scope.get(field_name)
            if value is not None and (
                type(value) is not str or not value or value != value.strip()
            ):
                raise ValueError(
                    f"calendar_{field_name} must be non-empty trimmed text or None"
                )


class GatewayCalendarQueryPort:
    """Gateway-mode calendar scope validator (forbids local feed_scope/calendar_*)."""

    mode: str = "gateway"

    def validate_feed_scope(
        self,
        calendar_scope: Mapping[str, Optional[str]],
        *,
        config: Optional[Mapping[str, Any]] = None,
    ) -> None:
        for field_name in CALENDAR_PARAM_FIELDS:
            if calendar_scope.get(field_name) is not None:
                raise LiveCompositionError(
                    "CALENDAR_SCOPE_CONFLICT",
                    detail=f"gateway_feed_forbids_calendar_{field_name}",
                )
        if isinstance(config, Mapping):
            calendars = config.get("calendars")
            if isinstance(calendars, Mapping) and "feed_scope" in calendars:
                raise LiveCompositionError(
                    "CALENDAR_SCOPE_CONFLICT",
                    detail="calendars.feed_scope",
                )

    @staticmethod
    def active_gateway_calendar_settings(store: Any) -> Optional[Dict[str, Any]]:
        cfg = getattr(store, "gateway_strategy_config", None)
        if cfg is None:
            return None
        cal = getattr(cfg, "calendar_settings", None)
        if cal is None:
            return None
        return {
            "mode": getattr(cal, "mode", None),
            "scopes": tuple(getattr(cal, "scopes", ())),
            "range_read": bool(getattr(cal, "range_read", False)),
        }
