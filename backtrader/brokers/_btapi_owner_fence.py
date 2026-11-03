"""Account-owner dispatch fence for ``BtApiBroker`` (iteration 60, P0-1).

The SDK ``bt_api_py.account_owner_handoff.AccountOwnerHandoff`` persists which
owner and generation may dispatch for one account. Once a Broker is bound to
it, the Broker checks ``may_dispatch(owner_id, generation)`` immediately
before every provider write (submit and cancel). A handoff in progress, a
newer generation, or an unreadable fence blocks the write; nothing is sent.
"""

from __future__ import annotations


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
        owner, generation = handoff.owner
        if owner != owner_id or handoff.stage is not None:
            raise ValueError("owner_id is not the current account owner")
        self._account_owner_fence = (handoff, owner_id, generation)
        return generation

    def _account_owner_fence_error(self):
        fence = self._account_owner_fence
        if fence is None:
            return None
        handoff, owner_id, generation = fence
        try:
            allowed = handoff.may_dispatch(owner_id, generation) is True
        except Exception:
            allowed = False
        if allowed:
            return None
        return (
            "account_owner_fenced",
            "This process is not the current account owner generation; nothing was sent",
        )
