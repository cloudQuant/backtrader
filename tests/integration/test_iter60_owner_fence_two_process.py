"""Iteration 60 (G1): two processes share the account-owner coordination store.

The old owner process runs the real ``SdkCorrelatedOrderAdapter`` dispatch
under an SDK dispatch lease against a fake provider that blocks until told
to finish. The controller process (this test) begins the handoff while that
provider call is in flight. Simulation only: synthetic account, fake
provider, temporary SQLite and host registry; no network.
"""

from __future__ import annotations

import multiprocessing
import time

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")  # SDK-free envs skip

from bt_api_py.account_coordination import AccountCoordinationBinding, HostAccountRegistry
from bt_api_py.account_owner_handoff import AccountOwnerHandoff, HandoffError
from bt_api_py.provider_session_revocation import ProviderSessionRevocationEvidence

ACCOUNT = "account-two-process"
ROUTE = "fake:route-two-process"
OLD, NEW = "owner-old", "owner-new"
SESSION = "fake-session-old"


class _Revoked:
    def verify_session_revocation(self, evidence):
        return True


def _handoff(path, registry):
    return AccountOwnerHandoff(
        path,
        ACCOUNT,
        initial_owner=OLD,
        binding=AccountCoordinationBinding(ACCOUNT, ROUTE),
        revocation_verifier=_Revoked(),
        host_registry=HostAccountRegistry(registry),
    )


def _old_owner(path, registry, entered, release, replies):
    import asyncio
    from types import SimpleNamespace

    from backtrader.brokers._btapi_owner_fence import AccountOwnerDispatchFence
    from backtrader.execution.sdk_correlated_order_adapter import SdkCorrelatedOrderAdapter

    class _Error(RuntimeError):
        pass

    class _Correlation:
        exchange_name, symbol = "FAKE", "SYM"

        def __init__(self, client_order_id):
            self.client_order_id = client_order_id

    class _Ack:
        def __init__(self, correlation):
            self.correlation, self.operation, self.disposition = correlation, "submit", "accepted"

    started = []

    class _Facade:
        def claim_correlated_order(self, *_args, **_kwargs):
            return object()

        async def submit_correlated_order(self, correlation, request, **_kwargs):
            started.append(correlation.client_order_id)
            entered.set()
            await asyncio.to_thread(release.wait, 30)
            return {"ok": True}

        def verify_order_response(self, correlation, result):
            return _Ack(correlation)

    facade = _Facade()

    class _Bindings:
        def by_correlation(self, correlation):
            return {"execution_facade": facade}

        def binding_matches(self, *_args, **_kwargs):
            return True

        def record_verified_response(self, *_args, **_kwargs):
            return True

    handoff = _handoff(path, registry)
    try:
        handoff.hold_owner_lock(OLD, provider_session_ref=SESSION)
        adapter = SdkCorrelatedOrderAdapter(error_type=_Error, bindings=_Bindings())
        adapter.require_facade = lambda api: {
            "OrderCorrelation": _Correlation,
            "VerifiedOrderAcknowledgement": _Ack,
            "is_correlated_order_execution_facade": lambda value: value is facade,
        }
        fence = AccountOwnerDispatchFence(SimpleNamespace(), handoff, OLD, 1)

        def dispatch(client_order_id):
            authorization = object()
            command = {
                "request": SimpleNamespace(client_order_id=client_order_id, symbol="SYM"),
                "correlation": _Correlation(client_order_id),
                "venue": "FAKE",
                "symbol": "SYM",
            }
            try:
                response = asyncio.run(
                    adapter.dispatch_command(
                        "submit",
                        command,
                        api=object(),
                        authorization=authorization,
                        current_authorization=lambda: authorization,
                        assert_write_route_identity=lambda **_kwargs: None,
                        validate_approval_lease_command=lambda command: None,
                        sanitize_exception=lambda error: None,
                        owner_fence=fence,
                    )
                )
            except _Error as error:
                return error.code
            return response["status"]

        first = dispatch("cid-1")
        second = dispatch("cid-2")  # after QUIESCE (the controller waited for cid-1)
        replies.put((first, second, started[:]))
    finally:
        handoff.close()


def _evidence():
    return ProviderSessionRevocationEvidence(
        ACCOUNT, ROUTE, 1, SESSION, "PROVIDER_LOGOUT_RECEIPT", time.time_ns(), "logout-1"
    )


def _spawn(tmp_path):
    context = multiprocessing.get_context("spawn")
    entered, release, replies = context.Event(), context.Event(), context.Queue()
    path, registry = tmp_path / "owner.sqlite3", tmp_path / "host"
    process = context.Process(
        target=_old_owner, args=(str(path), str(registry), entered, release, replies)
    )
    process.start()
    return process, entered, release, replies, path, registry


def test_quiesce_while_old_process_writes_then_fence_drains(tmp_path):
    process, entered, release, replies, path, registry = _spawn(tmp_path)
    controller = None
    try:
        assert entered.wait(90)
        controller = _handoff(path, registry)
        with pytest.raises(HandoffError, match="HANDOFF_HOST_OWNER_LOCK_HELD"):
            controller.hold_owner_lock(OLD, provider_session_ref="intruder")
        controller.begin(from_owner=OLD, to_owner=NEW)
        assert dict(controller.audit())["QUIESCE"]["inflight_at_quiesce"] == 1
        release.set()
        controller.fence(to_owner=NEW, evidence=_evidence(), drain_timeout=30)
        assert dict(controller.audit())["FENCE"]["unknown_inflight"] == []
        first, second, started = replies.get(timeout=60)
        assert first == "accepted"
        assert second == "account_owner_fenced"
        assert started == ["cid-1"]  # nothing of the old generation started after QUIESCE
        process.join(30)
        assert process.exitcode == 0
    finally:
        release.set()
        if process.is_alive():
            process.terminate()
            process.join(10)
        if controller is not None:
            controller.close()


def test_old_process_dies_mid_write_and_its_intent_is_carried_unknown(tmp_path):
    process, entered, _release, _replies, path, registry = _spawn(tmp_path)
    controller = None
    try:
        assert entered.wait(90)
        controller = _handoff(path, registry)
        controller.begin(from_owner=OLD, to_owner=NEW)
        process.terminate()
        process.join(30)
        controller.fence(to_owner=NEW, evidence=_evidence(), drain_timeout=0.1)
        assert dict(controller.audit())["FENCE"]["unknown_inflight"] == ["cid-1"]
        controller.restore(to_owner=NEW, ledger_cut="cut-1")
        assert dict(controller.audit())["RESTORE"]["carried_unknown_intents"] == ["cid-1"]
        controller.sync(to_owner=NEW, provider_snapshot_ref="snap-1")
        with pytest.raises(HandoffError, match="HANDOFF_NO_GO_UNKNOWN_INFLIGHT"):
            controller.reconcile(to_owner=NEW, reconciliation_state="BALANCED")
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
        if controller is not None:
            controller.close()
