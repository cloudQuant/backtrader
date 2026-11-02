"""Project SDK SimNow profile evidence into the example's public types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class SimNowProfileValidationError(ValueError):
    """A safe, value-free reason that the live CTP profile was not admitted."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class SimNowProfileEvidence:
    """Sanitized profile evidence; endpoint and credential values are omitted."""

    verified: bool
    environment: str
    profile: str


def validate_official_simnow_store_profile(
    config: Mapping[str, Any], api_kwargs: Mapping[str, Any]
) -> SimNowProfileEvidence:
    """Delegate the CTP profile check to the unified SDK."""
    try:
        from bt_api_py.ctp_profiles import (
            SimNowProfileError,
            validate_official_simnow_store_profile as validate_profile,
        )
    except ImportError:
        raise SimNowProfileValidationError("SDK_PROFILE_SELECTOR_UNAVAILABLE") from None
    try:
        evidence = validate_profile(config, api_kwargs)
    except SimNowProfileError as error:
        raise SimNowProfileValidationError(error.code) from None
    return SimNowProfileEvidence(
        verified=evidence["verified"],
        environment=evidence["environment"],
        profile=evidence["profile"],
    )
