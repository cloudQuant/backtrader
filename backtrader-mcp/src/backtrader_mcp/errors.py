"""Stable product errors exposed by the service and MCP boundary."""


class ProductError(RuntimeError):
    """Base error with a stable machine-readable code."""

    code = "product_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class InvalidRequest(ProductError):
    code = "invalid_request"


class NotFound(ProductError):
    code = "not_found"


class Conflict(ProductError):
    code = "conflict"


class Forbidden(ProductError):
    code = "forbidden"


class StaleState(ProductError):
    code = "stale_state"


class ApprovalRequired(ProductError):
    code = "approval_required"
