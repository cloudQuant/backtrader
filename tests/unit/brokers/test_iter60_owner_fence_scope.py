"""Local account-reference conflicts must fence the Broker and Store worker.

Matching references are only names; these tests do not authenticate a provider
account or establish an atomic fence at the provider write boundary.
"""

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")  # SDK-free envs skip

from backtrader.brokers._btapi_owner_fence import AccountOwnerFenceBrokerMixin
from bt_api_py.account_coordination import AccountCoordinationBinding, HostAccountRegistry
from bt_api_py.account_owner_handoff import AccountOwnerHandoff
from bt_api_py.strategy_ledger import SqliteStrategyLedger


def _handoff(tmp_path, account="account-A"):
    handoff = AccountOwnerHandoff(
        tmp_path / "owner.db",
        account,
        initial_owner="owner",
        binding=AccountCoordinationBinding(account, "fake:route-1"),
        host_registry=HostAccountRegistry(tmp_path / "host"),
    )
    handoff.hold_owner_lock("owner", provider_session_ref="fake-session-1")
    return handoff


class _Store:
    def __init__(self):
        self.fence = None

    def bind_account_owner_fence(self, fence):
        self.fence = fence


class _Broker(AccountOwnerFenceBrokerMixin):
    def __init__(self):
        self.store = _Store()
        self._account_owner_fence = None
        self._direct_strategy_ledger = None

    def _uses_async_commands(self):
        return True


def test_mismatched_ledger_first_prevents_owner_and_store_binding(tmp_path):
    handoff = _handoff(tmp_path)
    ledger = SqliteStrategyLedger(tmp_path / "ledger.db", account_ref="account-B")
    broker = _Broker()
    broker._direct_strategy_ledger = ledger
    try:
        with pytest.raises(ValueError, match="account references differ"):
            broker.bind_account_owner(handoff, "owner")
        assert broker._account_owner_fence is None
        assert broker.store.fence is None
    finally:
        ledger.close()
        handoff.close()


def test_mismatched_ledger_bound_later_fences_broker_and_store_worker(tmp_path):
    handoff = _handoff(tmp_path)
    ledger = SqliteStrategyLedger(tmp_path / "ledger.db", account_ref="account-B")
    broker = _Broker()
    try:
        assert broker.bind_account_owner(handoff, "owner") == 1
        assert broker.store.fence() is True
        broker._direct_strategy_ledger = ledger
        assert broker._account_owner_fence_error()[0] == "account_owner_scope_mismatch"
        assert broker.store.fence() is False
    finally:
        ledger.close()
        handoff.close()


def test_matching_account_names_do_not_disable_other_owner_checks(tmp_path):
    handoff = _handoff(tmp_path)
    ledger = SqliteStrategyLedger(tmp_path / "ledger.db", account_ref="account-A")
    broker = _Broker()
    broker._direct_strategy_ledger = ledger
    try:
        assert broker.bind_account_owner(handoff, "owner") == 1
        assert broker._account_owner_fence_error() is None
        assert broker.store.fence() is True
        handoff.begin(from_owner="owner", to_owner="new-owner")
        assert broker._account_owner_fence_error()[0] == "account_owner_fenced"
        assert broker.store.fence() is False
    finally:
        ledger.close()
        handoff.close()
