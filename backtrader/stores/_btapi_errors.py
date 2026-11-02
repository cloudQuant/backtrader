"""Errors for the Backtrader unified SDK Store and its bridges."""

class BtApiStoreError(Exception):
    """Base error for btapi store failures."""


class LegacyGatewayMigrationRequiredError(BtApiStoreError):
    """An old Store gateway/forwarding entry point requires offline migration."""

    code = "MIGRATION_REVIEW_REQUIRED"

    def __init__(self, target: str) -> None:
        self.target = str(target)
        super().__init__(
            f"BtApiStore legacy entry point {self.target!r} is retired "
            f"({self.code}); use bt_api_py.service_runtime.ServiceClientRuntime with a typed "
            "ServiceMarketClient, ServiceAccountClient, or ServiceExecutionClient. "
            "For managed Backtrader execution, configure "
            "backtrader.service.service_execution_session.ServiceExecutionSession(...) "
            "and then call .run(cerebro). "
            "Keep a matching historical release when no service binding exists."
        )


class _ApprovalLeaseRejected(BtApiStoreError):
    """Definite local rejection raised before an SDK write crosses its lease."""

    definite_reject = True

    def __init__(self, code: str):
        """Record the rejection code carried by this error.

        Args:
            code: Stable machine-readable rejection reason.
        """
        self.code = code
        super().__init__(code)


class BtApiMissingDependencyError(ImportError, BtApiStoreError):
    """Raised when bt_api_py is required but unavailable."""


class BtApiProviderNotImplementedError(NotImplementedError, BtApiStoreError):
    """Raised when a provider is intentionally left as a placeholder."""


