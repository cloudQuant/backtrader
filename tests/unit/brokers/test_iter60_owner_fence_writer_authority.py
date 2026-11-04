"""Iteration 60 (G1 cross-host): a Broker bound to the SDK writer authority.

Two Brokers stand for two hosts. Each binds a ``RemoteAccountOwnerHandoff`` of
one in-process writer authority (loopback TCP, HMAC frames, injected authority
clock). Only the writer-lease holder's Broker obtains dispatch leases; after the
lease is lost the old Broker is fenced and a new holder stays fenced until the
previous session's revocation is verified. Synthetic accounts only.
"""

import time

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")
authority_module = pytest.importorskip(
    "bt_api_py.account_writer_authority", reason="needs the SDK writer authority"
)

from backtrader.brokers._btapi_owner_fence import (  # noqa: E402
    AccountOwnerFenceBrokerMixin,
    finish_dispatch_lease,
)
from bt_api_py.account_coordination import AccountCoordinationBinding  # noqa: E402
from bt_api_py.provider_session_revocation import (  # noqa: E402
    ProviderSessionRevocationEvidence,
)

ACCOUNT = "account-A"
SECRET = b"w" * 32
SECOND = 1_000_000_000


class _Clock:
    def __init__(self):
        self.now = 50 * SECOND

    def __call__(self):
        return self.now


class _Verifier:
    def verify_session_revocation(self, evidence):
        return True


class _Store:
    fence = None

    def bind_account_owner_fence(self, fence):
        self.fence = fence


class _Broker(AccountOwnerFenceBrokerMixin):
    def __init__(self):
        self.store = _Store()
        self._account_owner_fence = None
        self._direct_strategy_ledger = None

    def _uses_async_commands(self):
        return False


class _Order:
    def __init__(self, **info):
        self.info = dict(info)

    def addinfo(self, **kwargs):
        self.info.update(kwargs)


@pytest.fixture
def authority(tmp_path):
    clock = _Clock()
    policy = authority_module.WriterLeasePolicy(
        ttl_seconds=10, grace_seconds=4, max_dispatch_seconds=2
    )
    server = authority_module.WriterAuthorityServer(
        tmp_path / "authority",
        clients={"host-a": SECRET, "host-b": SECRET},
        policy=policy,
        revocation_verifier=_Verifier(),
        monotonic_ns=clock,
    )
    server.start()
    yield server, clock, policy
    server.stop()


def _remote(server, host):
    return authority_module.RemoteAccountOwnerHandoff(
        server.address,
        client_id=host,
        secret=SECRET,
        binding=AccountCoordinationBinding(ACCOUNT, "fake:route-1"),
        initial_owner="owner",
        host_id=host,
    )


def test_only_the_writer_lease_holder_broker_dispatches(authority):
    server, clock, policy = authority
    a, b = _remote(server, "host-a"), _remote(server, "host-b")
    broker_a, broker_b = _Broker(), _Broker()
    try:
        a.hold_owner_lock("owner", provider_session_ref="session-a")
        assert broker_a.bind_account_owner(a, "owner") == 1
        with pytest.raises(ValueError, match="writer lease"):
            broker_b.bind_account_owner(b, "owner")

        lease, error = broker_a._acquire_account_owner_lease("submit", _Order(client_order_id="c1"))
        assert error is None
        finish_dispatch_lease(lease, "ACKNOWLEDGED")

        # Host A stops renewing (partition/pause); the authority clock moves on.
        clock.now += int((policy.ttl_seconds + policy.grace_seconds + 1) * SECOND)
        _lease, error = broker_a._acquire_account_owner_lease(
            "submit", _Order(client_order_id="c2")
        )
        assert error[0] == "account_owner_fenced"

        b.hold_owner_lock("owner", provider_session_ref="session-b")
        assert broker_b.bind_account_owner(b, "owner") == 1
        _lease, error = broker_b._acquire_account_owner_lease(
            "submit", _Order(client_order_id="c3")
        )
        assert error[0] == "account_owner_fenced"  # PENDING_REVOCATION
        b.confirm_previous_session_revoked(
            ProviderSessionRevocationEvidence(
                account_ref=ACCOUNT,
                provider_route="fake:route-1",
                revoked_owner_generation=1,
                revoked_session_ref="session-a",
                kind="PROVIDER_LOGOUT_RECEIPT",
                observed_at_ns=time.time_ns(),
                evidence_ref="logout-1",
            )
        )
        lease, error = broker_b._acquire_account_owner_lease(
            "submit", _Order(client_order_id="c3")
        )
        assert error is None
        finish_dispatch_lease(lease, "ACKNOWLEDGED")
        _lease, error = broker_a._acquire_account_owner_lease(
            "submit", _Order(client_order_id="c4")
        )
        assert error[0] == "account_owner_fenced"
    finally:
        a.close()
        b.close()
