"""Store-owned contract metadata cache and bounded-probe adapters.

The Store keeps the public, mutable ``contract_metadata`` mapping and controls
when SDK calls are admitted.  This module contains the alias-aware cache
operations and the Store-specific checks at the SDK probe boundary; it does
not own probe threads, Store lifecycle, or SDK/provider facts.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Callable, Dict, List, Tuple

from ..utils.coercion import coerce_text as _coerce_text


def contract_metadata_aliases(symbol: Any) -> List[str]:
    """Return the SDK-selected aliases for one configured instrument name."""

    from bt_api_py.instrument_metadata_aliases import contract_metadata_aliases

    return contract_metadata_aliases(_coerce_text(symbol))


class StoreContractMetadataCache:
    """Alias-aware operations over the Store's live mutable metadata mapping.

    ``mapping_getter`` intentionally resolves the mapping on every operation.
    Callers can keep mutating or replacing the historical public
    ``store.contract_metadata`` attribute without introducing a second source
    of truth here.
    """

    def __init__(self, *, mapping_getter: Callable[[], Any]) -> None:
        if not callable(mapping_getter):
            raise TypeError("contract metadata cache requires a mapping callback")
        self._mapping_getter = mapping_getter

    def snapshot_all(self) -> Dict[str, Dict[str, Any]]:
        """Return the same per-row shallow copy as the Store's old getter."""

        return {
            key: dict(value)
            for key, value in self._mapping_getter().items()
        }

    def lookup(
        self,
        dataname: Any,
        *,
        metadata: Any,
        aliases: List[str],
        alias_fn: Callable[[Any], List[str]],
        find_alias_match: Callable[..., Any],
    ) -> Tuple[Any, Any]:
        """Match using the current query's captured SDK alias functions."""

        found, value = find_alias_match(
            metadata,
            aliases,
            alias_fn=alias_fn,
            require_truthy=True,
        )
        if found:
            # The original Store resolves its public mapping again after the
            # matcher returns.  Preserve that re-entrant replacement behavior
            # instead of writing through the mapping used for the lookup.
            self._mapping_getter().setdefault(str(dataname), dict(value))
            return found, dict(value)
        return found, value

    def store_normalized(self, dataname: Any, metadata: Any) -> None:
        """Cache one Backtrader-compatible projection with a deep copy."""

        self._mapping_getter()[str(dataname)] = deepcopy(metadata)


def bounded_metadata_probe_shutdown_proven(health: Any) -> bool:
    """Return whether the one-shot probe has no Store-owned work left behind."""

    return bool(
        isinstance(health, Mapping)
        and health.get("shutdown_state") == "PASS"
        and int(health.get("queue_depth", 0) or 0) == 0
        and not health.get("inflight")
        and not health.get("worker_alive")
        and not health.get("close_thread_alive")
        and health.get("broker_update_conservation") is True
        and not health.get("last_error_code")
    )


def configure_bounded_metadata_probe_sdk_market_data_only(
    store: Any,
    *,
    error_type: type,
    safe_log: Callable[..., Any],
) -> None:
    """Reapply the probe's existing zero-write SDK settings and verify them."""

    try:
        # Reapply the same identity contract used to create the owned client.
        # The probe has already forced ``market_data_only`` in that mapping;
        # dropping required environments here would make a second idempotency
        # check fail before public metadata is read.
        assembly = store._sdk_direct_api_assembly
        if assembly is None:
            raise error_type("direct SDK assembly is unavailable")
        assembly.reapply_execution_config()
    except Exception as exc:
        safe_log("error", "btapistore:4070 exception before re-raise (Exception)")
        store.sanitize_exception(exc)
        raise error_type(
            "bounded read-only metadata probe could not configure SDK market-data-only mode"
        ) from None

    # Keep Store method dispatch so lifecycle/test overrides retain their
    # historical behavior.
    store._verify_bounded_metadata_probe_sdk_market_data_only()


def verify_bounded_metadata_probe_sdk_market_data_only(
    store: Any,
    *,
    error_type: type,
    missing_dependency_error_type: type,
    safe_log: Callable[..., Any],
) -> None:
    """Require public SDK execution-summary state after lifecycle transitions."""

    api = store._api
    get_execution_summary = getattr(api, "get_execution_summary", None)
    if not callable(get_execution_summary):
        raise error_type(
            "bounded read-only metadata probe cannot verify SDK market-data-only mode"
        )
    try:
        summary = get_execution_summary()
    except Exception as exc:
        safe_log("error", "btapistore:4089 exception before re-raise (Exception)")
        store.sanitize_exception(exc)
        raise error_type(
            "bounded read-only metadata probe cannot verify SDK market-data-only mode"
        ) from None
    try:
        from bt_api_py.bounded_metadata_probe import is_market_data_only_execution_summary
    except ImportError as exc:
        raise missing_dependency_error_type(
            "bt_api_py metadata probe summary contract is required"
        ) from exc
    if not is_market_data_only_execution_summary(summary):
        raise error_type(
            "bounded read-only metadata probe cannot verify SDK market-data-only mode"
        )


__all__ = (
    "StoreContractMetadataCache",
    "bounded_metadata_probe_shutdown_proven",
    "configure_bounded_metadata_probe_sdk_market_data_only",
    "contract_metadata_aliases",
    "verify_bounded_metadata_probe_sdk_market_data_only",
)
