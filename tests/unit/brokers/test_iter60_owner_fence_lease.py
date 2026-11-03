"""Iteration 60 (G1): Broker binding to an account-bound, host-locked owner.

The Broker binds only to an ``AccountOwnerHandoff`` that is bound to an
account coordination identity and whose host owner lock this process holds.
Synchronous Store writes run under an SDK dispatch lease taken by the Broker;
queued Stores receive the lease-granting fence. Synthetic accounts only.
"""

from types import SimpleNamespace

import pytest

from backtrader.brokers._btapi_owner_fence import (
    AccountOwnerDispatchFence,
    AccountOwnerFenceBrokerMixin,
    finish_dispatch_lease,
    lease_outcome_for_error,
    lease_outcome_for_response,
)
from bt_api_py.account_coordination import AccountCoordinationBinding, HostAccountRegistry
from bt_api_py.account_owner_handoff import AccountOwnerHandoff

ACCOUNT = "account-A"


class _Store:
    def __init__(self):
        self.fence = None

    def bind_account_owner_fence(self, fence):
        self.fence = fence


class _Broker(AccountOwnerFenceBrokerMixin):
    def __init__(self, *, queued=False):
        self.store = _Store()
        self._account_owner_fence = None
        self._direct_strategy_ledger = None
        self._queued = queued

    def _uses_async_commands(self):
        return self._queued


class _Order:
    def __init__(self, **info):
        self.info = dict(info)

    def addinfo(self, **kwargs):
        self.info.update(kwargs)


def _handoff(tmp_path, *, lock=True, bound=True):
    kwargs = {}
    if bound:
        kwargs = {
            "binding": AccountCoordinationBinding(ACCOUNT, "fake:route-1"),
            "host_registry": HostAccountRegistry(tmp_path / "host"),
        }
    handoff = AccountOwnerHandoff(tmp_path / "owner.db", ACCOUNT, initial_owner="owner", **kwargs)
    if lock:
        handoff.hold_owner_lock("owner", provider_session_ref="fake-session-1")
    return handoff


def test_unbound_coordination_handoff_cannot_be_bound(tmp_path):
    handoff = _handoff(tmp_path, lock=False, bound=False)
    try:
        with pytest.raises(ValueError, match="account-bound coordination"):
            _Broker().bind_account_owner(handoff, "owner")
    finally:
        handoff.close()


def test_owner_without_the_host_lock_cannot_be_bound(tmp_path):
    holder = _handoff(tmp_path)
    other = _handoff(tmp_path, lock=False)
    broker = _Broker()
    try:
        with pytest.raises(ValueError, match="host owner lock"):
            broker.bind_account_owner(other, "owner")
        assert broker._account_owner_fence is None and broker.store.fence is None
    finally:
        other.close()
        holder.close()


def test_store_receives_a_lease_granting_fence(tmp_path):
    handoff = _handoff(tmp_path)
    broker = _Broker(queued=True)
    try:
        assert broker.bind_account_owner(handoff, "owner") == 1
        fence = broker.store.fence
        assert type(fence) is AccountOwnerDispatchFence and fence() is True
        lease = fence.acquire_dispatch_lease("submit", "cid-1")
        lease.finish("ACKNOWLEDGED")
        # Queued Stores take the lease in their worker, not in the Broker.
        assert broker._acquire_account_owner_lease("submit", _Order()) == (None, None)
    finally:
        handoff.close()


def test_sync_write_lease_is_refused_after_quiesce(tmp_path):
    handoff = _handoff(tmp_path)
    broker = _Broker()
    try:
        broker.bind_account_owner(handoff, "owner")
        lease, error = broker._acquire_account_owner_lease("submit", _Order(client_order_id="c1"))
        assert error is None
        handoff.begin(from_owner="owner", to_owner="new-owner")
        _late, error = broker._acquire_account_owner_lease("submit", _Order(client_order_id="c2"))
        assert error[0] == "account_owner_fenced"
        finish_dispatch_lease(lease, "ACKNOWLEDGED")  # the in-flight write completes
        assert handoff.unresolved_dispatches() == ()
    finally:
        handoff.close()


def test_sync_write_never_resubmits_an_unknown_intent(tmp_path):
    handoff = _handoff(tmp_path)
    broker = _Broker()
    try:
        broker.bind_account_owner(handoff, "owner")
        order = _Order(strategy_ledger_intent_id="ledger-intent-1")
        lease, _error = broker._acquire_account_owner_lease("submit", order)
        finish_dispatch_lease(lease, lease_outcome_for_error(TimeoutError("timed out")))
        _lease, error = broker._acquire_account_owner_lease("submit", order)
        assert error[0] == "account_owner_intent_unresolved"
        (unresolved,) = handoff.unresolved_dispatches()
        assert unresolved.intent_id == "ledger-intent-1"
        # A cancel of the same order uses its own intent and may proceed.
        cancel, error = broker._acquire_account_owner_lease("cancel", order)
        assert error is None
        finish_dispatch_lease(cancel, "UNKNOWN")
    finally:
        handoff.close()


def test_order_without_a_stable_identity_gets_one_reused_on_retry(tmp_path):
    handoff = _handoff(tmp_path)
    broker = _Broker()
    try:
        broker.bind_account_owner(handoff, "owner")
        order = _Order()
        lease, _error = broker._acquire_account_owner_lease("submit", order)
        finish_dispatch_lease(lease, "ACKNOWLEDGED")
        intent = order.info["account_owner_intent"]
        _lease, error = broker._acquire_account_owner_lease("submit", order)
        assert error[0] == "account_owner_intent_already_sent"
        assert handoff.unresolved_dispatches() == ()
        assert intent.startswith("bt-order:")
    finally:
        handoff.close()


def test_lease_outcomes_are_conservative():
    assert lease_outcome_for_response({"verified_order_ack": True, "status": "accepted"}) == (
        "ACKNOWLEDGED"
    )
    assert lease_outcome_for_response({"verified_order_ack": True, "status": "rejected"}) == (
        "REJECTED"
    )
    assert lease_outcome_for_response({"kind": "command_receipt"}) == "UNKNOWN"
    assert lease_outcome_for_response(None) == "UNKNOWN"
    rejected = SimpleNamespace(definite_reject=True, execution_unknown=False)
    assert lease_outcome_for_error(rejected) == "REJECTED"
    assert lease_outcome_for_error(TimeoutError()) == "UNKNOWN"
    assert lease_outcome_for_error(TimeoutError(), dispatched=False) == "NOT_SENT"
