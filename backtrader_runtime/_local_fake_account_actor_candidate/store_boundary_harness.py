"""Tiny fake Store boundary. It models ordering only and never imports Backtrader."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from .account_actor_port import (
    AccountActorGateError,
    ActorCommandContextV1,
    ActorCommandExpectationV2,
    CtpAccountActorPort,
    CtpCancelIntentV2,
    CtpSubmitIntentV2,
    FakeLocalActorReplayLedger,
    RouteKind,
    StoreRouteDescriptor,
    classify_store_route,
    reject_ctp_legacy_dispatch,
    require_account_actor_before_local_client,
    validate_actor_receipt,
)


class StoreBoundaryHarness:
    def __init__(
        self,
        route: StoreRouteDescriptor,
        *,
        actor_port: Optional[CtpAccountActorPort] = None,  # noqa: UP045 - Python 3.8
        actor_context: Optional[ActorCommandContextV1] = None,  # noqa: UP045 - Python 3.8
        receipt_ledger: Optional[FakeLocalActorReplayLedger] = None,  # noqa: UP045 - Python 3.8
        credential_resolver: Optional[Callable[[], Any]] = None,  # noqa: UP045 - Python 3.8
        api_factory: Optional[Callable[[], Any]] = None,  # noqa: UP045 - Python 3.8
        gateway_factory: Optional[Callable[[], Any]] = None,  # noqa: UP045 - Python 3.8
    ) -> None:
        # This is the candidate integration order: gate before retaining or
        # invoking any local API/API class/gateway factory.
        self.route_kind = classify_store_route(route)
        self.actor_port = require_account_actor_before_local_client(route, actor_port)
        if self.route_kind is RouteKind.CTP:
            if type(actor_context) is not ActorCommandContextV1:
                raise AccountActorGateError("actor_command_context_required")
            if type(receipt_ledger) is FakeLocalActorReplayLedger:
                self.receipt_ledger = receipt_ledger
            else:
                raise AccountActorGateError("fake_replay_ledger_required")
            self.actor_context = actor_context
        else:
            self.receipt_ledger = receipt_ledger
            self.actor_context = actor_context
        self.api = None
        self.legacy_calls = 0
        # This ordering models the production boundary: classification and the
        # unavailable-actor rejection precede credential resolution too.
        if self.route_kind is RouteKind.NON_CTP and credential_resolver is not None:
            credential_resolver()
        if self.route_kind is RouteKind.NON_CTP:
            if route.api is not None:
                self.api = route.api
            elif route.backend == "gateway":
                self.api = gateway_factory() if gateway_factory is not None else None
            elif route.api_cls is not None:
                self.api = api_factory() if api_factory is not None else route.api_cls()
        elif route.api is not None or route.api_cls is not None:
            # The gate above rejects these for an actor-owned CTP route.
            raise AccountActorGateError("local_ctp_client_injection_forbidden")

    def submit_order(self, intent: object) -> Any:
        if self.route_kind is RouteKind.CTP:
            if type(intent) is not CtpSubmitIntentV2:
                raise AccountActorGateError("typed_submit_intent_required")
            self._require_current_actor_context(intent)
            expected = ActorCommandExpectationV2.from_intent(intent)
            self.receipt_ledger.claim_once(intent)
            receipt = self.actor_port.submit_order(intent)
            return validate_actor_receipt(receipt, expected=expected)
        return self._submit_order_legacy(intent)

    def cancel_order(self, intent: object) -> Any:
        if self.route_kind is RouteKind.CTP:
            if type(intent) is not CtpCancelIntentV2:
                raise AccountActorGateError("typed_cancel_intent_required")
            self._require_current_actor_context(intent)
            expected = ActorCommandExpectationV2.from_intent(intent)
            self.receipt_ledger.claim_once(intent)
            receipt = self.actor_port.cancel_order(intent)
            return validate_actor_receipt(receipt, expected=expected)
        return self._cancel_order_legacy(intent)

    def _require_current_actor_context(self, intent: Any) -> None:
        if type(intent.context) is not ActorCommandContextV1:
            raise AccountActorGateError("actor_intent_context_invalid")
        try:
            intent.context.__post_init__()
            intent.__post_init__()
        except (AttributeError, TypeError, ValueError):
            raise AccountActorGateError("actor_intent_invalid") from None
        if intent.context != self.actor_context:
            raise AccountActorGateError("actor_intent_context_mismatch")

    def _submit_order_legacy(self, value: object) -> str:
        del value
        reject_ctp_legacy_dispatch(self.route_kind)
        self.legacy_calls += 1
        return "legacy_non_ctp"

    def _cancel_order_legacy(self, value: object) -> str:
        del value
        reject_ctp_legacy_dispatch(self.route_kind)
        self.legacy_calls += 1
        return "legacy_non_ctp"
