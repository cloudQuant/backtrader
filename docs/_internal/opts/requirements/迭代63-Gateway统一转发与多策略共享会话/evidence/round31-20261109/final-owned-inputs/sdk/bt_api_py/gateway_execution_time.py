"""Explicit interpretation of execution date and time, without source proof.

The policy describes a caller-selected interpretation only. It does not prove
the provider's timezone, timestamp provenance, or freshness.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class GatewayExecutionTimeError(ValueError):
    """A bounded, input-independent error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _text(value: object, *, limit: int) -> bool:
    if type(value) is not str or not value or value != value.strip():
        return False
    try:
        return len(value.encode("utf-8")) <= limit and all(
            ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in value
        )
    except UnicodeEncodeError:
        return False


@dataclass(frozen=True, slots=True)
class GatewayExecutionTimePolicy:
    """Versioned, immutable interpretation chosen explicitly for one route."""

    route: str
    timezone: str
    format: str = "date_hms_seconds_v1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not _text(self.route, limit=256):
            raise GatewayExecutionTimeError("INVALID_ROUTE")
        if not _text(self.timezone, limit=255):
            raise GatewayExecutionTimeError("INVALID_TIMEZONE")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise GatewayExecutionTimeError("INVALID_TIMEZONE") from None
        if type(self.format) is not str or self.format != "date_hms_seconds_v1":
            raise GatewayExecutionTimeError("INVALID_FORMAT")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise GatewayExecutionTimeError("INVALID_SCHEMA_VERSION")

    def to_mapping(self) -> dict[str, object]:
        return {
            "route": self.route,
            "timezone": self.timezone,
            "format": self.format,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> GatewayExecutionTimePolicy:
        if not isinstance(value, Mapping) or set(value) != {
            "route",
            "timezone",
            "format",
            "schema_version",
        }:
            raise GatewayExecutionTimeError("INVALID_MAPPING")
        return cls(**value)

    @property
    def digest(self) -> str:
        """SHA-256 of UTF-8 JSON with sorted keys and no insignificant spaces."""
        payload = json.dumps(
            self.to_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def project(self, trade_date: object, trade_time: object) -> datetime | None:
        """Interpret complete natural date/time fields as UTC; missing is unknown."""
        parsed_date = None
        parsed_time = None
        if trade_date is not None:
            if type(trade_date) is not str or re.fullmatch(r"[0-9]{8}", trade_date) is None:
                raise GatewayExecutionTimeError("INVALID_DATE")
            try:
                parsed_date = date(int(trade_date[:4]), int(trade_date[4:6]), int(trade_date[6:8]))
            except ValueError:
                raise GatewayExecutionTimeError("INVALID_DATE_TIME") from None
        if trade_time is not None:
            if (
                type(trade_time) is not str
                or re.fullmatch(r"[0-9]{2}:[0-9]{2}:[0-9]{2}", trade_time) is None
            ):
                raise GatewayExecutionTimeError("INVALID_TIME")
            try:
                parsed_time = time(int(trade_time[:2]), int(trade_time[3:5]), int(trade_time[6:8]))
            except ValueError:
                raise GatewayExecutionTimeError("INVALID_DATE_TIME") from None
        if parsed_date is None or parsed_time is None:
            return None
        local = datetime.combine(parsed_date, parsed_time)

        zone = ZoneInfo(self.timezone)
        candidates = set()
        try:
            for fold in (0, 1):
                candidate = local.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                if candidate.astimezone(zone).replace(tzinfo=None) == local:
                    candidates.add(candidate)
        except (OverflowError, ValueError):
            raise GatewayExecutionTimeError("INVALID_DATE_TIME") from None
        if len(candidates) != 1:
            raise GatewayExecutionTimeError("AMBIGUOUS_OR_NONEXISTENT_TIME")
        return candidates.pop()
