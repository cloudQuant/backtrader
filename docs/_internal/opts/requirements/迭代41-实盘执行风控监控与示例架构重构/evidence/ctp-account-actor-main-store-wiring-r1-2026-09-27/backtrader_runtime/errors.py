"""Stable, redacted errors for the configuration-first runtime.

The runtime loader is deliberately small and has no provider, gateway, or
plugin imports.  Keeping its error vocabulary here gives callers a stable
machine-readable boundary before any optional trading dependency can be
considered.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


CONFIG_REQUIRED = "CONFIG_REQUIRED"
CONFIG_SCHEMA_UNSUPPORTED = "CONFIG_SCHEMA_UNSUPPORTED"
MODE_PRESET_MISMATCH = "MODE_PRESET_MISMATCH"
PRESET_POLICY_VIOLATION = "PRESET_POLICY_VIOLATION"
ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
CONFIG_EXISTS = "CONFIG_EXISTS"
MIGRATION_REVIEW_REQUIRED = "MIGRATION_REVIEW_REQUIRED"


ERROR_CODES = frozenset(
    (
        CONFIG_REQUIRED,
        CONFIG_SCHEMA_UNSUPPORTED,
        MODE_PRESET_MISMATCH,
        PRESET_POLICY_VIOLATION,
        ENVIRONMENT_MISMATCH,
        CONFIG_EXISTS,
        MIGRATION_REVIEW_REQUIRED,
    )
)


class RuntimeConfigError(Exception):
    """A deterministic configuration or policy rejection.

    Args:
        code: One of :data:`ERROR_CODES`.
        message: Safe, operator-facing explanation.  Never include a raw
            configuration value that might be a credential.
        field_path: Optional dotted configuration path associated with the
            rejection.
        reason: Stable lower-case reason suitable for tests and automation.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field_path: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        if code not in ERROR_CODES:
            raise ValueError("unsupported runtime configuration error code: {0}".format(code))

        self.code = code
        self.message = message
        self.field_path = field_path
        self.reason = reason
        super().__init__(self._display_message())

    def _display_message(self) -> str:
        parts = [self.code, self.message]
        if self.field_path:
            parts.append("field={0}".format(self.field_path))
        if self.reason:
            parts.append("reason={0}".format(self.reason))
        return ": ".join((parts[0], " ".join(parts[1:])))

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe error payload without source configuration data."""

        payload = {"error_code": self.code, "message": self.message}
        if self.field_path is not None:
            payload["field_path"] = self.field_path
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload
