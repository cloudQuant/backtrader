"""Framework-side extension point for managed order execution.

The Store delegates managed writes to an explicitly supplied adapter. This
module describes that framework boundary only: SDK correlation identities,
provider acknowledgements, native request fields, and durable execution
receipts belong to ``bt_api_py`` and its provider packages.

The adapter may use the injected SDK-dispatch callable only after its own
admission and journal checks. The Store never retries a failed adapter through
the ordinary path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional, Protocol


class ManagedExecutionAdapterError(RuntimeError):
    """A supplied managed adapter is absent, malformed, or unsupported."""


class ManagedExecutionAdapter(Protocol):
    """The narrow managed-execution port accepted by :class:`BtApiStore`.

    The ``sdk_dispatch`` callables are private Store internals. An adapter
    may call one once only after its own intent, authorization, and risk gates
    have made a durable decision. Adapter failure never permits a direct
    fallback by the Store.
    """

    def submit_order(self, order: Any, sdk_dispatch: Callable[[Any], Any]) -> Any:
        """Return the adapter's framework-facing submission projection."""

    def cancel_order(
        self,
        order_or_ref: Any,
        dataname: Optional[str],
        sdk_dispatch: Callable[[Any, Optional[str]], Any],
    ) -> Any:
        """Return the adapter's framework-facing cancellation projection."""


def require_managed_execution_adapter(value: Any) -> Optional[ManagedExecutionAdapter]:
    """Validate the deliberate managed-adapter attachment without SDK imports."""

    if value is None:
        return None
    if not callable(getattr(value, "submit_order", None)):
        raise ManagedExecutionAdapterError("managed adapter must implement submit_order")
    return value


def require_managed_cancel(
    adapter: ManagedExecutionAdapter,
) -> Callable[[Any, Optional[str], Any], Any]:
    """Return the explicit cancellation port or fail closed before provider I/O."""

    cancel = getattr(adapter, "cancel_order", None)
    if not callable(cancel):
        raise ManagedExecutionAdapterError("managed adapter does not implement cancellation")
    return cancel


__all__ = (
    "ManagedExecutionAdapter",
    "ManagedExecutionAdapterError",
    "require_managed_cancel",
    "require_managed_execution_adapter",
)
