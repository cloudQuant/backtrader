"""Own the SDK-facing half of Store-correlated order commands.

The Store keeps Backtrader references, route policy, and command-runtime
lifecycle. This adapter owns the optional SDK type cache, route-facade shape,
correlation issuance, typed request construction from Store-resolved context,
and exact acknowledgement handoff. It uses the Store's existing binding
registry and command dispatcher; it creates no worker and keeps no second copy
of order state or verification receipts.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Mapping, Optional, Type

from .order_request_projection import (
    execution_contract_from_order_request as _execution_contract_from_order_request,
)


class SdkCorrelatedOrderAdapter:
    """Bridge one Store-owned BT order binding to the neutral SDK facade."""

    def __init__(self, *, error_type: Type[Exception], bindings: Any) -> None:
        if not callable(error_type) or bindings is None:
            raise TypeError("SDK correlated-order adapter requires error and binding owners")
        self._error_type = error_type
        self._bindings = bindings
        self._command_types: Dict[str, Any] = {}

    def warm_command_types(self) -> Dict[str, Any]:
        """Load public SDK request, enum, correlation and acknowledgement types."""

        if not self._command_types:
            from bt_api_py.correlated_command_dispatch import correlated_command_types

            self._command_types.update(correlated_command_types())
        return self._command_types

    def require_facade(self, api: Any) -> Dict[str, Any]:
        """Require the SDK's optional route-bound correlated-write selector."""

        from bt_api_py.correlated_command_dispatch import require_correlated_selector

        command_types = self.warm_command_types()
        require_correlated_selector(api, error_type=self._error_type)
        return command_types

    def select_facade(self, api: Any, exchange_name: str):
        """Select and shape-check one SDK-owned route facade."""

        from bt_api_py.correlated_command_dispatch import select_correlated_facade

        command_types = self.warm_command_types()
        route_facade = select_correlated_facade(api, exchange_name, error_type=self._error_type)
        return route_facade, command_types

    def issue_correlation(self, facade: Any, exchange_name: str, symbol: str) -> Any:
        """Issue and validate one SDK correlation without creating Store state."""

        from bt_api_py.correlated_command_dispatch import issue_order_correlation

        self.warm_command_types()
        return issue_order_correlation(facade, exchange_name, symbol, error_type=self._error_type)

    def build_order_request(
        self,
        venue: str,
        payload: Mapping[str, Any],
        *,
        correlation: Any,
        framework_order: Any,
        api: Any,
        resolve_request_context: Callable[[], Mapping[str, Any]],
    ) -> Any:
        """Bind one BT order to its exact neutral SDK request and contract."""

        command_types = self.warm_command_types()
        if type(correlation) is not command_types["OrderCorrelation"]:
            raise self._error_type("an exact SDK OrderCorrelation is required")
        reference = payload.get("bt_order_ref")
        if type(reference) is not int:
            raise self._error_type("Backtrader order reference is unavailable")
        entry = self._bindings.by_correlation(correlation)
        if (
            entry is None
            or entry.get("bt_order_ref") != reference
            or entry.get("order") is not framework_order
            or not self._bindings.binding_matches(
                entry,
                correlation=correlation,
                api=api,
                exchange_name=venue,
                symbol=payload.get("symbol"),
                states={"prepared"},
                require_all_indexes=True,
            )
        ):
            raise self._error_type("SDK OrderCorrelation is not bound to this BT order")
        supplied_client_id = payload.get("client_order_id")
        if supplied_client_id not in (None, "", correlation.client_order_id):
            raise self._error_type("order client ID differs from the SDK correlation")
        context = resolve_request_context()
        if not isinstance(context, Mapping):
            raise self._error_type("SDK order request context is unavailable")

        from bt_api_py.correlated_command_dispatch import build_order_request

        request = build_order_request(
            command_types["OrderRequest"],
            command_types["OrderType"],
            command_types["Side"],
            payload,
            account_id=context["account_id"],
            client_order_id=correlation.client_order_id,
            default_quantity_unit=context["default_quantity_unit"],
            instrument=context["instrument"],
            include_instrument=context["include_instrument"],
            strategy_identity_sha256=context["strategy_identity_sha256"],
        )
        execution_contract = _execution_contract_from_order_request(request)
        if not self._bindings.set_execution_contract(
            venue,
            correlation.client_order_id,
            correlation,
            api,
            execution_contract,
        ):
            raise self._error_type("SDK correlation has no Store-local Backtrader binding")
        return request

    def build_cancel_request(
        self,
        reference: Any,
        dataname: Any,
        *,
        api: Any,
        sdk_exchange: Callable[[Any], str],
        configured_account_id: Callable[[str], str],
    ) -> tuple[str, Any, Mapping[str, Any], Any]:
        """Resolve an exact Store binding before constructing its neutral cancel."""

        command_types = self.warm_command_types()
        reference_key = str(reference)
        binding = self._bindings.by_local_ref(reference)
        if binding is None:
            candidates = [
                item
                for item in self._bindings.find_client_id(
                    reference_key,
                    api=api,
                    symbol=None if dataname is None else str(dataname),
                )
                if item.get("client_order_id") == reference_key
                and item.get("correlation") is not None
                and self._bindings.binding_matches(
                    item, api=api, require_all_indexes=True
                )
            ]
            if len(candidates) == 1:
                binding = candidates[0]
        if not isinstance(binding, Mapping):
            raise self._error_type(
                "cancellation requires a Store-bound SDK order correlation"
            )
        correlation = binding.get("correlation")
        if type(correlation) is not command_types["OrderCorrelation"]:
            raise self._error_type("cancellation target has no exact SDK OrderCorrelation")
        venue = binding.get("exchange_name")
        symbol = binding.get("symbol")
        if type(venue) is not str or type(symbol) is not str:
            raise self._error_type("cancellation route binding is unavailable")
        if dataname is not None and str(dataname) != symbol:
            raise self._error_type("cancellation feed differs from the bound order symbol")
        if correlation.exchange_name != venue or correlation.symbol != symbol:
            raise self._error_type("cancellation correlation differs from its Store binding")
        if sdk_exchange(symbol) != venue:
            raise self._error_type(
                "cancellation route no longer matches the Store symbol binding"
            )
        if not self._bindings.binding_matches(
            binding,
            correlation=correlation,
            api=api,
            exchange_name=venue,
            symbol=symbol,
            states={"queued", "completed", "unknown"},
            require_all_indexes=True,
        ):
            raise self._error_type(
                "cancellation requires a submitted or unresolved SDK order"
            )
        account_id = configured_account_id(venue)
        from bt_api_py.correlated_command_dispatch import build_cancel_order_request

        request = build_cancel_order_request(
            command_types["CancelOrderRequest"],
            symbol=symbol,
            account_id=account_id,
            client_order_id=correlation.client_order_id,
        )
        return venue, request, binding, correlation

    async def dispatch_command(
        self,
        operation: str,
        command: Dict[str, Any],
        *,
        api: Any,
        authorization: Any,
        current_authorization: Callable[[], Any],
        assert_write_route_identity: Callable[..., Any],
        validate_approval_lease_command: Callable[[Mapping[str, Any]], Any],
        sanitize_exception: Callable[[BaseException], Any],
        owner_fence: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Claim, dispatch once, verify the SDK acknowledgement, and retain it.

        Store provides only its live route/auth guards and reuses its single
        execution-binding registry. Dispatch still runs inside the existing
        command worker's coordinator call path.

        ``owner_fence`` (iteration 60, G1) is the Broker's account-owner
        fence. Calling it is an early pre-check: a failure before the claim is
        a definite local rejection. The exit itself is atomic with the
        handoff: the last pre-dispatch step takes an SDK ``DispatchLease``
        (``owner_fence.acquire_dispatch_lease``) and holds it until the
        provider call returns, then records the outcome. A handoff QUIESCE
        refuses new leases and waits for, or records UNKNOWN, those held. A
        lease refused after the claim is reported UNKNOWN; a fence that cannot
        grant leases is refused before the claim.
        """

        from bt_api_py.correlated_command_dispatch import (
            dispatch_correlated_command,
            require_correlated_request_binding,
        )

        if operation not in {"submit", "cancel"}:
            raise self._error_type("unsupported SDK command operation")
        if owner_fence is not None and not _fence_allows(owner_fence):
            error = self._error_type("account owner fence blocked the write before dispatch")
            error.definite_reject = True
            error.code = "account_owner_fenced"
            raise error
        if owner_fence is not None and not callable(
            getattr(owner_fence, "acquire_dispatch_lease", None)
        ):
            error = self._error_type("account owner fence cannot hold a dispatch lease")
            error.definite_reject = True
            error.code = "account_owner_fence_unleased"
            raise error
        request = command.get("request")
        try:
            assert_write_route_identity(expected_api=api, require_live_route=True)
        except Exception:
            error = self._error_type("SDK write route is unavailable before dispatch")
            error.definite_reject = True
            error.code = "sdk_write_route_unavailable"
            raise error from None
        try:
            command_types = self.require_facade(api)
        except Exception:
            error = self._error_type("SDK correlated write selector is unavailable")
            error.definite_reject = True
            error.code = "sdk_correlated_write_unavailable"
            raise error from None
        correlation = require_correlated_request_binding(
            command,
            request,
            authorization,
            correlation_type=command_types["OrderCorrelation"],
            error_type=self._error_type,
        )
        if operation == "submit":
            validate_approval_lease_command(command)

        allowed_states = (
            {"queued"}
            if operation == "submit"
            else {"queued", "completed", "unknown"}
        )
        entry = self._bindings.by_correlation(correlation)
        if entry is None or not self._bindings.binding_matches(
            entry,
            correlation=correlation,
            api=api,
            exchange_name=command.get("venue"),
            symbol=command.get("symbol"),
            states=allowed_states,
            require_all_indexes=True,
        ):
            error = self._error_type("SDK correlated write no longer matches its Store binding")
            error.definite_reject = True
            error.code = "sdk_store_correlation_binding_changed"
            raise error
        execution_facade = entry.get("execution_facade")
        if not command_types["is_correlated_order_execution_facade"](execution_facade):
            error = self._error_type("SDK route-bound correlated facade is unavailable")
            error.definite_reject = True
            error.code = "sdk_correlated_route_unavailable"
            raise error

        held_leases: list = []

        def before_dispatch() -> None:
            assert_write_route_identity(expected_api=api, require_live_route=True)
            if current_authorization() is not authorization:
                error = self._error_type("SDK execution authorization changed before dispatch")
                error.execution_unknown = True
                error.code = "sdk_execution_authorization_changed"
                raise error
            current = self._bindings.by_correlation(correlation)
            if current is None or not self._bindings.binding_matches(
                current,
                correlation=correlation,
                api=api,
                exchange_name=command.get("venue"),
                symbol=command.get("symbol"),
                require_all_indexes=True,
            ):
                error = self._error_type("SDK order correlation changed before dispatch")
                error.execution_unknown = True
                error.code = "sdk_order_correlation_changed"
                raise error
            if owner_fence is not None:
                # The lease is the last step: it is held for the whole
                # provider call, so a QUIESCE either precedes it (refused)
                # or waits for it / records it UNKNOWN.
                try:
                    held_leases.append(
                        owner_fence.acquire_dispatch_lease(
                            operation, _owner_dispatch_intent(operation, correlation)
                        )
                    )
                except Exception:
                    error = self._error_type("account owner fence refused the dispatch lease")
                    error.execution_unknown = True
                    error.code = "account_owner_fenced"
                    raise error from None
            command["_sdk_dispatch_method_entered"] = True

        try:
            acknowledgement = await dispatch_correlated_command(
                operation,
                execution_facade,
                correlation,
                request,
                authorization,
                acknowledgement_type=command_types["VerifiedOrderAcknowledgement"],
                error_type=self._error_type,
                before_dispatch=before_dispatch,
                sanitize_exception=sanitize_exception,
            )
        except BaseException as exc:
            for lease in held_leases:
                _finish_lease(lease, _lease_error_outcome(exc))
            raise
        for lease in held_leases:
            _finish_lease(
                lease,
                "REJECTED" if acknowledgement.disposition == "rejected" else "ACKNOWLEDGED",
            )

        verification_id = uuid.uuid4().hex
        status = acknowledgement.disposition
        response = {
            "kind": "verified_order_ack",
            "operation": operation,
            "status": status,
            "client_order_id": correlation.client_order_id,
            "symbol": correlation.symbol,
            "data_name": correlation.symbol,
            "exchange_name": correlation.exchange_name,
            "verified_order_ack": True,
            "verification_id": verification_id,
            "remote_write_attempted": True,
            "execution_unknown": False,
            "definite_reject": status == "rejected",
            "terminal_confirmed": status == "rejected",
        }
        if status == "rejected":
            reason_code = acknowledgement.reason_code
            response["error_code"] = (
                reason_code
                if type(reason_code) is str and reason_code
                else "sdk_order_rejected"
            )
            response["error_msg"] = "SDK verified a definite order rejection"

        current = self._bindings.by_correlation(correlation)
        if current is None or not self._bindings.record_verified_response(
            verification_id,
            snapshot=current,
            correlation=correlation,
            api=api,
            execution_facade=execution_facade,
            operation=operation,
            acknowledgement=acknowledgement,
            status=status,
        ):
            error = self._error_type(
                "SDK order correlation changed after response verification"
            )
            error.execution_unknown = True
            error.code = "sdk_order_response_unverified"
            raise error
        return response


def resolve_store_order_request_context(
    store, venue, payload, *, contract_metadata_aliases, error_type
):
    """Project framework configuration and instrument metadata for one request."""
    account_id = store._configured_sdk_account_id(venue)
    strategy_identity_sha256 = str(
        store._sdk_execution_config_value("strategy_identity_sha256") or ""
    )
    supplied_strategy_identity = str(payload.get("strategy_identity_sha256") or "")
    if supplied_strategy_identity and supplied_strategy_identity != strategy_identity_sha256:
        raise error_type("Order strategy identity differs from SDK execution config")
    instrument_candidates = []
    for alias in contract_metadata_aliases(payload["symbol"]):
        metadata = store.contract_metadata.get(alias)
        if isinstance(metadata, Mapping) and metadata.get("instrument_key") is not None:
            instrument_candidates.append(metadata.get("instrument_key"))
    instrument = (
        store.get_market_instrument_key(payload["symbol"]) if instrument_candidates else None
    )
    return {
        "account_id": account_id,
        "strategy_identity_sha256": strategy_identity_sha256,
        "default_quantity_unit": store.contract_metadata.get(payload["symbol"], {}).get(
            "quantity_unit"
        ),
        "instrument": instrument,
        "include_instrument": bool(instrument_candidates),
    }


def prepare_store_order_correlation(store, order, *, error_type):
    """Reserve one SDK-owned neutral client identity for a BT order.

    The Backtrader reference is retained only in this Store.  The SDK sees
    the exchange name and symbol and returns its opaque correlation; no
    provider-native identity is created or reconstructed here.
    """
    if store._service_read_only:
        raise error_type("read-only service proxy cannot prepare order writes")
    if not store._sdk_mode:
        raise error_type("order correlation requires the bt_api_py unified facade")
    if store._execution_authorization is None:
        raise error_type(
            "correlated order writes require an explicitly injected SDK authorization"
        )
    store._ensure_api_ready()
    api = store._api
    store._assert_write_route_identity(expected_api=api, require_live_route=True)
    if store._is_sdk_market_data_only():
        raise error_type("market-data-only facade cannot prepare order writes")
    payload = store._order_to_payload(order)
    reference = getattr(order, "ref", None)
    if type(reference) is not int:
        raise error_type("Backtrader order reference is unavailable")
    symbol = payload.get("symbol")
    if type(symbol) is not str or not symbol or symbol != symbol.strip():
        raise error_type("order symbol must be a non-empty trimmed string")
    venue = store._sdk_exchange(symbol)
    try:
        execution_facade, command_types = store._sdk_correlated_order_adapter.select_facade(
            api, venue
        )
    except Exception:
        raise error_type(
            "SDK correlated order capability is unavailable for the selected route"
        ) from None
    # OrderRequest requires account_id.  It is request data only; the SDK
    # correlated endpoint remains responsible for validating it against
    # the issued reservation and its own execution ledger.
    account_id = store._configured_sdk_account_id(venue)
    order_info = getattr(order, "info", {})
    get_info = getattr(order_info, "get", lambda *_args: None)

    preparation, existing = store._sdk_execution_bindings.begin_preparation(
        reference=reference,
        order=order,
        exchange_name=venue,
        symbol=symbol,
        api=api,
        execution_facade=execution_facade,
        supplied_client_order_id=get_info("client_order_id"),
    )
    if preparation is None:
        return existing

    try:
        correlation = store._sdk_correlated_order_adapter.issue_correlation(
            execution_facade, venue, symbol
        )
        store._assert_write_route_identity(expected_api=api, require_live_route=True)
        current_client_id = get_info("client_order_id")
        if current_client_id not in (None, "", correlation.client_order_id):
            raise error_type("SDK correlation conflicts with the Backtrader order")
        store._sdk_execution_bindings.complete_preparation(
            preparation,
            correlation=correlation,
            correlation_type=command_types["OrderCorrelation"],
            account_id=account_id,
        )
        if hasattr(order, "addinfo"):
            order.addinfo(client_order_id=correlation.client_order_id)
        elif isinstance(order_info, dict):
            order_info["client_order_id"] = correlation.client_order_id
        return correlation
    except Exception as exc:
        store.sanitize_exception(exc)
        store._sdk_execution_bindings.fail_preparation(preparation)
        if isinstance(exc, error_type):
            raise
        raise error_type("SDK order correlation preparation failed before dispatch") from None


__all__ = (
    "SdkCorrelatedOrderAdapter",
    "prepare_store_order_correlation",
    "resolve_store_order_request_context",
)


def _fence_allows(owner_fence: Any) -> bool:
    """An unreadable fence blocks the write."""

    try:
        return owner_fence() is True
    except Exception:
        return False


def _owner_dispatch_intent(operation: str, correlation: Any) -> str:
    """One provider-write intent per SDK client identity (never resubmitted)."""

    client_order_id = correlation.client_order_id
    return client_order_id if operation == "submit" else f"{operation}:{client_order_id}"


def _lease_error_outcome(error: BaseException) -> str:
    if bool(getattr(error, "definite_reject", False)) and not bool(
        getattr(error, "execution_unknown", False)
    ):
        return "REJECTED"
    return "UNKNOWN"


def _finish_lease(lease: Any, outcome: str) -> None:
    """A lease that cannot record its outcome stays IN_FLIGHT (UNKNOWN at FENCE)."""

    try:
        lease.finish(outcome)
    except Exception:
        from ..utils.log_message import get_logger

        get_logger(__name__).warning(
            "account-owner dispatch lease could not record its outcome"
        )
