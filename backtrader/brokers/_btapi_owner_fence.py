"""Account-owner dispatch fence for ``BtApiBroker`` (iteration 60, G1).

The SDK ``bt_api_py.account_owner_handoff.AccountOwnerHandoff`` persists which
owner and generation may dispatch for one account and grants dispatch
leases. A Broker binds only to an account-bound handoff whose host owner lock
this process holds. Every provider write then runs under an SDK
``DispatchLease`` held for the whole provider call:

* synchronous Stores: the Broker takes the lease around ``store.submit_order``
  / ``store.cancel_order``;
* queued Stores: the ``BtApiStore`` command worker takes it in the SDK
  adapter's last pre-dispatch step and finishes it when the provider call
  returns (``SdkCorrelatedOrderAdapter.dispatch_command``).

A handoff's QUIESCE is the exclusive side: after it commits no new lease is
granted, and leases already running are waited for or recorded UNKNOWN. The
Broker pre-check (``_account_owner_fence_error``) remains an early, local
rejection only. Matching ledger and owner account references are names, not
provider authentication; cross-host exclusivity is not proven here.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from ..utils.log_message import get_logger

_LOG = get_logger(__name__)


def _may_dispatch(handoff, owner_id, generation) -> bool:
    try:
        return handoff.may_dispatch(owner_id, generation) is True
    except Exception:
        return False


def _account_references_match(broker, handoff) -> bool:
    """Reject conflicts, without treating matching names as account proof."""

    try:
        ledger = getattr(broker, "_direct_strategy_ledger", None)
        if ledger is None:
            return True
        account_ref = ledger.account_ref
        account_key = handoff.account_key
        return (
            type(account_ref) is str
            and bool(account_ref)
            and type(account_key) is str
            and account_ref == account_key
        )
    except Exception:
        return False


class AccountOwnerLeaseRefused(RuntimeError):
    """The SDK refused a dispatch lease; nothing was sent to the provider."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AccountOwnerDispatchFence:
    """Owner-generation fence bound to one Broker; grants SDK dispatch leases.

    Calling the fence is the early pre-check. ``acquire_dispatch_lease`` is
    the atomic exit: the returned SDK lease must be held across the provider
    call and finished with its outcome.
    """

    def __init__(self, broker, handoff, owner_id, generation) -> None:
        self._broker = broker
        self.handoff = handoff
        self.owner_id = owner_id
        self.generation = generation

    def scope_matches(self) -> bool:
        return _account_references_match(self._broker, self.handoff)

    def __call__(self) -> bool:
        return self.scope_matches() and _may_dispatch(self.handoff, self.owner_id, self.generation)

    def acquire_dispatch_lease(self, operation, intent_id):
        if not self.scope_matches():
            raise AccountOwnerLeaseRefused("account_owner_scope_mismatch")
        try:
            return self.handoff.acquire_dispatch_lease(
                self.owner_id, self.generation, operation=operation, intent_id=intent_id
            )
        except Exception as error:
            code = getattr(error, "code", None)
            raise AccountOwnerLeaseRefused(
                code if type(code) is str and code else "account_owner_lease_unavailable"
            ) from None

    def unresolved_dispatches(self):
        """Old-owner writes whose outcome recovery must reconcile (never resubmit)."""

        return self.handoff.unresolved_dispatches()


def lease_outcome_for_error(error, *, dispatched=True) -> str:
    """Map a provider-call failure to a conservative lease outcome."""

    if not dispatched:
        return "NOT_SENT"
    if bool(getattr(error, "definite_reject", False)) and not bool(
        getattr(error, "execution_unknown", False)
    ):
        return "REJECTED"
    return "UNKNOWN"


def lease_outcome_for_response(response) -> str:
    """Only an SDK-verified acknowledgement resolves a write."""

    if isinstance(response, Mapping) and response.get("verified_order_ack") is True:
        return "REJECTED" if response.get("status") == "rejected" else "ACKNOWLEDGED"
    return "UNKNOWN"


def finish_dispatch_lease(lease, outcome) -> None:
    """Finish ``lease``; a failure leaves it IN_FLIGHT, i.e. UNKNOWN at FENCE."""

    if lease is None:
        return
    try:
        lease.finish(outcome)
    except Exception:
        _LOG.warning("account-owner dispatch lease could not record its outcome")


class AccountOwnerFenceBrokerMixin:
    """Gate provider writes on the persisted account-owner generation."""

    _account_owner_fence = None

    def bind_account_owner(self, handoff, owner_id):
        """Dispatch only while ``owner_id`` owns ``handoff`` and holds its host lock.

        The generation is pinned at bind time; after a handoff to another
        owner (or back again) this Broker instance never dispatches again.
        """

        from bt_api_py.account_owner_handoff import AccountOwnerHandoff

        if type(handoff) is not AccountOwnerHandoff:
            raise ValueError("a bt_api_py AccountOwnerHandoff is required")
        if self._account_owner_fence is not None:
            raise ValueError("this broker is already bound to an account owner")
        if getattr(handoff, "binding", None) is None:
            raise ValueError("an account-bound coordination handoff is required")
        if not _account_references_match(self, handoff):
            raise ValueError("owner and strategy ledger account references differ")
        owner, generation = handoff.owner
        if owner != owner_id or handoff.stage is not None:
            raise ValueError("owner_id is not the current account owner")
        if handoff.holds_owner_lock != owner_id:
            raise ValueError("this process does not hold the host owner lock for owner_id")
        fence = AccountOwnerDispatchFence(self, handoff, owner_id, generation)
        store = getattr(self, "store", None)
        bind_store = getattr(store, "bind_account_owner_fence", None)
        if callable(bind_store):
            # The Store worker takes the SDK dispatch lease at the exit.
            bind_store(fence)
        elif self._uses_async_commands():
            raise ValueError("queued provider writes need a Store that holds dispatch leases")
        self._account_owner_fence = fence
        return generation

    def _account_owner_fence_error(self):
        fence = self._account_owner_fence
        if fence is None:
            return None
        if not fence.scope_matches():
            return (
                "account_owner_scope_mismatch",
                "Owner and strategy ledger account references conflict",
            )
        if fence():
            return None
        return (
            "account_owner_fenced",
            "This process is not the current account owner generation; nothing was sent",
        )

    def _account_owner_dispatch_intent(self, order, operation):
        info = getattr(order, "info", None)
        get = getattr(info, "get", None)
        intent = None
        if callable(get):
            for key in ("client_order_id", "strategy_ledger_intent_id", "account_owner_intent"):
                value = get(key)
                if type(value) is str and value:
                    intent = value
                    break
        if intent is None:
            intent = f"bt-order:{uuid.uuid4().hex}"
            if hasattr(order, "addinfo"):
                order.addinfo(account_owner_intent=intent)
        return intent if operation == "submit" else f"{operation}:{intent}"

    def _acquire_account_owner_lease(self, operation, order):
        """Return ``(lease, fence_error)`` for a synchronous Store write.

        Queued Stores take the lease in their command worker instead.
        """

        fence = self._account_owner_fence
        if fence is None or self._uses_async_commands():
            return None, None
        try:
            lease = fence.acquire_dispatch_lease(
                operation, self._account_owner_dispatch_intent(order, operation)
            )
        except AccountOwnerLeaseRefused as error:
            if error.code in {"HANDOFF_DISPATCH_FENCED", "HANDOFF_HOST_OWNER_LOCK_NOT_HELD"}:
                code = "account_owner_fenced"
            elif error.code == "HANDOFF_DISPATCH_INTENT_ALREADY_SENT":
                code = "account_owner_intent_already_sent"
            elif error.code.startswith("HANDOFF_DISPATCH_INTENT_"):
                code = "account_owner_intent_unresolved"
            else:
                code = error.code
            return None, (code, "The account-owner dispatch lease was refused; nothing was sent")
        return lease, None
