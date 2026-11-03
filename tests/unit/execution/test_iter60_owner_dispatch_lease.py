"""Iteration 60 (G1): the Store worker's SDK write runs under a dispatch lease.

``SdkCorrelatedOrderAdapter.dispatch_command`` takes the account-owner
``DispatchLease`` as its last pre-dispatch step and holds it until the
provider call returns. These tests drive a fake SDK facade with events so a
handoff QUIESCE lands at exact points of the dispatch, and check that no
provider write of the old generation starts after QUIESCE commits.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")  # SDK-free envs skip

from backtrader.brokers._btapi_owner_fence import AccountOwnerDispatchFence
from backtrader.execution.sdk_correlated_order_adapter import SdkCorrelatedOrderAdapter
from bt_api_py.account_coordination import AccountCoordinationBinding, HostAccountRegistry
from bt_api_py.account_owner_handoff import AccountOwnerHandoff
from bt_api_py.provider_session_revocation import ProviderSessionRevocationEvidence

ACCOUNT = "account-lease"
ROUTE = "fake:route-lease"
OLD, NEW = "owner-old", "owner-new"
SESSION = "fake-session-old"


class _Error(RuntimeError):
    pass


class _Correlation:
    def __init__(self, client_order_id):
        self.client_order_id = client_order_id
        self.exchange_name = "FAKE"
        self.symbol = "SYM"


class _Ack:
    def __init__(self, correlation, operation, disposition="accepted"):
        self.correlation = correlation
        self.operation = operation
        self.disposition = disposition


class _Bindings:
    def __init__(self, facade):
        self.facade = facade

    def by_correlation(self, correlation):
        return {"execution_facade": self.facade}

    def binding_matches(self, *_args, **_kwargs):
        return True

    def record_verified_response(self, *_args, **_kwargs):
        return True


class _Facade:
    """Fake SDK facade; ``submit`` records provider starts and may block."""

    def __init__(self):
        self.started = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.fail = None

    def claim_correlated_order(self, *_args, **_kwargs):
        return object()

    async def submit_correlated_order(self, correlation, request, **_kwargs):
        self.started.append(correlation.client_order_id)
        self.entered.set()
        if self.block:
            await asyncio.to_thread(self.release.wait, 10)
        if self.fail is not None:
            raise self.fail
        return {"ok": True}

    def verify_order_response(self, correlation, result):
        return _Ack(correlation, "submit")


class _Revoked:
    def verify_session_revocation(self, evidence):
        return True


def _handoff(tmp_path):
    return AccountOwnerHandoff(
        tmp_path / "owner.sqlite3",
        ACCOUNT,
        initial_owner=OLD,
        binding=AccountCoordinationBinding(ACCOUNT, ROUTE),
        revocation_verifier=_Revoked(),
        host_registry=HostAccountRegistry(tmp_path / "host"),
    )


@pytest.fixture
def setup(tmp_path):
    owner = _handoff(tmp_path)
    owner.hold_owner_lock(OLD, provider_session_ref=SESSION)
    controller = _handoff(tmp_path)
    fence = AccountOwnerDispatchFence(SimpleNamespace(), owner, OLD, 1)
    facade = _Facade()
    adapter = SdkCorrelatedOrderAdapter(error_type=_Error, bindings=_Bindings(facade))
    adapter.require_facade = lambda api: {
        "OrderCorrelation": _Correlation,
        "VerifiedOrderAcknowledgement": _Ack,
        "is_correlated_order_execution_facade": lambda value: value is facade,
    }
    yield SimpleNamespace(
        owner=owner, controller=controller, fence=fence, facade=facade, adapter=adapter
    )
    controller.close()
    owner.close()


def _dispatch(setup, client_order_id, *, route_hook=None, owner_fence=None):
    correlation = _Correlation(client_order_id)
    request = SimpleNamespace(client_order_id=client_order_id, symbol="SYM")
    authorization = object()
    command = {
        "request": request,
        "correlation": correlation,
        "venue": "FAKE",
        "symbol": "SYM",
    }
    calls = []

    def route(**_kwargs):
        calls.append("route")
        if route_hook is not None:
            route_hook(len(calls))

    return asyncio.run(
        setup.adapter.dispatch_command(
            "submit",
            command,
            api=object(),
            authorization=authorization,
            current_authorization=lambda: authorization,
            assert_write_route_identity=route,
            validate_approval_lease_command=lambda command: None,
            sanitize_exception=lambda error: None,
            owner_fence=setup.fence if owner_fence is None else owner_fence,
        )
    )


def _evidence():
    return ProviderSessionRevocationEvidence(
        ACCOUNT, ROUTE, 1, SESSION, "PROVIDER_LOGOUT_RECEIPT", time.time_ns(), "logout-1"
    )


def test_dispatch_finishes_its_lease_with_the_verified_outcome(setup):
    response = _dispatch(setup, "cid-1")
    assert response["status"] == "accepted" and setup.facade.started == ["cid-1"]
    assert setup.owner.unresolved_dispatches() == ()
    with pytest.raises(_Error) as info:  # the same client identity is never re-sent
        _dispatch(setup, "cid-1")
    assert info.value.code == "account_owner_fenced" and info.value.execution_unknown
    assert setup.facade.started == ["cid-1"]


def test_quiesce_between_precheck_and_lease_refuses_before_the_provider(setup):
    def quiesce_at_last_check(call_number):
        if call_number == 2:  # before_dispatch: the pre-claim pre-check has passed
            setup.controller.begin(from_owner=OLD, to_owner=NEW)

    with pytest.raises(_Error) as info:
        _dispatch(setup, "cid-race", route_hook=quiesce_at_last_check)
    assert info.value.code == "account_owner_fenced"
    assert info.value.execution_unknown is True  # after the claim: conservative
    assert setup.facade.started == []  # no provider write began after QUIESCE
    assert setup.owner.unresolved_dispatches() == ()


def test_quiesce_during_the_provider_call_waits_for_the_lease(setup):
    setup.facade.block = True
    result = {}
    worker = threading.Thread(target=lambda: result.update(r=_dispatch(setup, "cid-slow")))
    worker.start()
    assert setup.facade.entered.wait(10)
    setup.controller.begin(from_owner=OLD, to_owner=NEW)
    fenced = threading.Event()
    fencer = threading.Thread(
        target=lambda: (
            setup.controller.fence(to_owner=NEW, evidence=_evidence(), drain_timeout=10),
            fenced.set(),
        )
    )
    fencer.start()
    assert not fenced.wait(0.2)
    setup.facade.release.set()
    worker.join(10)
    fencer.join(10)
    assert fenced.is_set() and result["r"]["status"] == "accepted"
    assert dict(setup.controller.audit())["FENCE"]["unknown_inflight"] == []
    # After QUIESCE the pre-check rejects definitively, before any claim.
    with pytest.raises(_Error) as info:
        _dispatch(setup, "cid-after")
    assert info.value.code == "account_owner_fenced" and info.value.definite_reject
    assert setup.facade.started == ["cid-slow"]


def test_provider_failure_leaves_the_intent_unknown_for_recovery(setup):
    setup.facade.fail = TimeoutError("provider timed out")
    with pytest.raises(TimeoutError):
        _dispatch(setup, "cid-timeout")
    (unresolved,) = setup.controller.unresolved_dispatches()
    assert (unresolved.intent_id, unresolved.state) == ("cid-timeout", "UNKNOWN")
    setup.facade.fail = None
    with pytest.raises(_Error):
        _dispatch(setup, "cid-timeout")  # recovery must reconcile, not resubmit
    assert setup.facade.started == ["cid-timeout"]


def test_fence_without_a_lease_api_is_refused_before_the_claim(setup):
    with pytest.raises(_Error) as info:
        _dispatch(setup, "cid-plain", owner_fence=lambda: True)
    assert info.value.code == "account_owner_fence_unleased" and info.value.definite_reject
    assert setup.facade.started == []
