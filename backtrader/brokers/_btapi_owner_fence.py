"""Account-owner dispatch fence for ``BtApiBroker`` (iteration 60, P0-1).

The SDK ``bt_api_py.account_owner_handoff.AccountOwnerHandoff`` persists which
owner and generation may dispatch for one account. Once a Broker is bound to
it, the Broker checks ``may_dispatch(owner_id, generation)`` before handing a
submit or cancel to the Store, and a ``BtApiStore`` checks it again in its
command worker before entering the SDK write. A handoff in progress, a newer
generation, or an unreadable fence blocks calls which have not passed their
check. These checks are not atomic with the provider write: an already
admitted call may still arrive after QUIESCE. A ledger-gated Broker refuses
orders until bound, and rejects conflicting owner and ledger account references;
matching references do not authenticate the provider account.
"""

from __future__ import annotations


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


class AccountOwnerFenceBrokerMixin:
    """Gate provider writes on the persisted account-owner generation."""

    _account_owner_fence = None

    def bind_account_owner(self, handoff, owner_id):
        """Dispatch only while ``owner_id`` is the current owner of ``handoff``.

        The generation is pinned at bind time; after a handoff to another
        owner (or back again) this Broker instance never dispatches again.
        """

        from bt_api_py.account_owner_handoff import AccountOwnerHandoff

        if type(handoff) is not AccountOwnerHandoff:
            raise ValueError("a bt_api_py AccountOwnerHandoff is required")
        if self._account_owner_fence is not None:
            raise ValueError("this broker is already bound to an account owner")
        if not _account_references_match(self, handoff):
            raise ValueError("owner and strategy ledger account references differ")
        owner, generation = handoff.owner
        if owner != owner_id or handoff.stage is not None:
            raise ValueError("owner_id is not the current account owner")
        store = getattr(self, "store", None)
        bind_store = getattr(store, "bind_account_owner_fence", None)
        if callable(bind_store):
            # Recheck the stage and local scope before entering the SDK. This
            # is not an atomic fence at the provider or a proof of identity.
            bind_store(
                lambda: _account_references_match(self, handoff)
                and _may_dispatch(handoff, owner_id, generation)
            )
        elif self._uses_async_commands():
            raise ValueError("queued provider writes need a Store that rechecks the owner fence")
        self._account_owner_fence = (handoff, owner_id, generation)
        return generation

    def _account_owner_fence_error(self):
        fence = self._account_owner_fence
        if fence is None:
            return None
        handoff, owner_id, generation = fence
        if not _account_references_match(self, handoff):
            return (
                "account_owner_scope_mismatch",
                "Owner and strategy ledger account references conflict",
            )
        if _may_dispatch(handoff, owner_id, generation):
            return None
        return (
            "account_owner_fenced",
            "This process is not the current account owner generation; nothing was sent",
        )
