"""Stable, redacted errors exposed by the product."""

from typing import Any, Dict, Optional


class AgentError(RuntimeError):
    """A safe failure with a stable diagnostic code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details or {}
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "code": self.code,
            "severity": "error",
            "message": self.message,
        }
        if self.hint:
            value["hint"] = self.hint
        if self.details:
            value["details"] = self.details
        return value
