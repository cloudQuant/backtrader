"""P0-3 regression tests: GatewayMarketAdapter recovers through RECOVERY_REQUIRED ->
PROVIDER_RESYNC_REQUIRED -> LIVE on MD epoch rotation, and GatewayExecutionStream
paces execution_order_status polling to protect strict-connection message-ID budgets."""
from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

from bt_api_py.execution_routing import ExecutionRoutingOutcome, ExecutionRoutingStatus
from bt_api_py.gateway_market_projection import GatewayMarketProjectionError
from bt_api_py.service_market import MarketReceiveReceipt

from backtrader.brokers._btapi_gateway_stream import (
    GatewayExecutionStreamBrokerMixin,
    _StreamBinding,
)
from backtrader.service.gateway_market_adapter import GatewayMarketAdapter


class _OwnerOpError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _StubProjector:
    """Drives the exact RECOVERY_REQUIRED -> recover() -> PROVIDER_RESYNC_REQUIRED ->
    accept_resync() -> LIVE state machine observed after SimNow MD reconnect."""

    def __init__(self) -> None:
        self.phase = "epoch1_lost"
        self.calls: list[str] = []
        self.last_receipt = None

    def poll(self):
        self.calls.append("poll")
        if self.phase == "epoch1_lost":
            raise _OwnerOpError("RECOVERY_REQUIRED")
        if self.phase == "epoch2_live":
            self.last_receipt = MarketReceiveReceipt(
                "pub", "stream-rb", "epoch-2", 1, "m-2-1", 1000, 1000, os.getpid(), threading.get_ident()
            )
            return SimpleNamespace(epoch="epoch-2", seq=1)
        return None

    def recover(self):
        self.calls.append("recover")
        assert self.phase == "epoch1_lost"
        self.phase = "awaiting_resync"
        raise GatewayMarketProjectionError("PROVIDER_RESYNC_REQUIRED")

    def accept_resync(self):
        self.calls.append("accept_resync")
        assert self.phase == "awaiting_resync"
        self.phase = "epoch2_live"

    def status(self):
        self.calls.append("status")
        if self.phase == "epoch2_live":
            return {
                "healthy": True,
                "recovery_required": False,
                "resync_required": False,
                "authorization_interrupted": None,
                "local_result_gap": False,
            }
        return {
            "healthy": False,
            "recovery_required": True,
            "resync_required": self.phase == "awaiting_resync",
            "authorization_interrupted": None,
            "local_result_gap": False,
        }


def test_gateway_market_adapter_recovers_from_epoch_rotation_to_live():
    adapter = GatewayMarketAdapter.__new__(GatewayMarketAdapter)
    api = object()
    adapter._store = SimpleNamespace(gateway_api=api, _started=True, is_connected=True)
    adapter._api = api
    adapter._projector = _StubProjector()
    adapter._reason = None
    adapter._pending_operation = None
    adapter._backoff = (0.0, 0.0, 0.0)
    adapter._attempt = 0
    adapter._next_retry = 0.0
    adapter._last_event = None
    adapter._last_receipt = None
    adapter._latest_event = None
    adapter._latest_receipt = None

    # 1. Poll hits RECOVERY_REQUIRED on MD epoch rotation
    assert adapter._poll_open() is None
    assert adapter._reason == "RECOVERY_REQUIRED"

    # 2. Retry 1 runs recover() -> PROVIDER_RESYNC_REQUIRED
    assert adapter._poll_open() is None
    assert adapter._reason == "PROVIDER_RESYNC_REQUIRED"

    # 3. Retry 2 runs accept_resync() -> status healthy -> immediately delivers epoch-2 live tick!
    ev = adapter._poll_open()
    assert ev is not None and ev.epoch == "epoch-2"
    assert adapter._reason is None
    assert adapter._projector.calls == ["poll", "recover", "accept_resync", "status", "poll"]


def test_execution_order_status_polling_is_paced_with_backoff():
    calls = []
    feed = [1]

    class _Order:
        Submitted = 1
        Rejected = 7
        Completed = 4
        Canceled = 5
        Expired = 6
        Margin = 8

        def __init__(self):
            self.ref = 1
            self.data = feed
            self.status = self.Submitted
            self.executed = SimpleNamespace(size=0)
            self.info = {}

        def alive(self):
            return True

    order = _Order()
    key = "bt-pace-1"
    route = SimpleNamespace(
        kind="EXECUTION_PARENT",
        request_key=key,
        configuration_id="cfg-1",
        request_id="req-1",
        request_sha256="a" * 64,
        parent_ref="parent-1",
    )

    class _Host:
        _binding = SimpleNamespace(account_scope="acct-1", principal="strat-p")

        def load_execution_checkpoint(self):
            return SimpleNamespace(
                consumer_ref="c-1", epoch="ep-1", stored_sequence=0,
                applied_sequence=0, acknowledged_sequence=0, revision=1,
            )

        def local_order_notifications(self):
            return {}

        def load_execution_route(self, k):
            return route if k == key else None

        def load_intent(self, k):
            return SimpleNamespace(request_key=k)

        def read_execution_events(self, limit=1):
            return []

        def ingest_execution_result(self, result, *, expected_revision):
            return self.load_execution_checkpoint()

    def _status(_route, _intent):
        calls.append(time.monotonic())
        return ExecutionRoutingStatus(
            routed=True,
            outcome=ExecutionRoutingOutcome.EXECUTION_LOCAL_RECEIPT,
            request_id="req-1",
            request_sha256="a" * 64,
            parent_ref="parent-1",
            configuration_id="cfg-1",
            execution_state=None,
        )

    api = SimpleNamespace(
        execution_selected=True,
        execution_configuration_id="cfg-1",
        execution_order_status=_status,
    )
    stream = SimpleNamespace(read_after=lambda *a, **kw: SimpleNamespace(outcome="OBSERVED", page=None))
    binding = _StreamBinding(
        strategy=object(),
        api=api,
        host=_Host(),
        stream=stream,
        policy=SimpleNamespace(route="CTP___FUTURE"),
        instruments={},
        feeds={"f1": feed},
        restored=False,
        limit=10,
        timeout=5.0,
        pid=os.getpid(),
        thread=threading.current_thread(),
    )
    notice = SimpleNamespace(restored=None, fault=None, armed=None, receipt=None, orders={key: order})

    class _Broker(GatewayExecutionStreamBrokerMixin):
        def __init__(self):
            self._gateway_stream_binding = binding
            self.store = SimpleNamespace(_gateway_mode=False, is_connected=True)
            self.notifs = []

        def _is_market_data_only(self):
            return False

        def _gateway_stream_check(self, b, *, connected_required=True):
            return None

        def _gateway_binding(self, s, *, required=True):
            return notice

        def _gateway_host_pass_snapshot(self, h):
            return None

    broker = _Broker()
    # First step queries immediately; rapid back-to-back steps within 1s are paced (not re-queried!)
    for _ in range(5):
        binding.next_idle_read = 0.0
        broker._gateway_stream_next()
    assert len(calls) == 1
    assert key in binding.execution_status_recheck
    assert binding.state == "EXECUTION_RECOVERY_PENDING"


def test_gateway_market_adapter_retires_lease_on_terminated_non_strict_session():
    from bt_api_base.service_protocol import WireIdentity, WireRole
    from bt_api_py.service_runtime_thread import RuntimeSnapshot, ThreadedRuntimeError

    from backtrader.service.gateway_market_adapter import (
        _session_runtime_terminated_after_failure,
    )

    ident = WireIdentity(WireRole.STRATEGY_CLIENT, "strat-p", "strat-1")

    class _DeadApi:
        _gateway_strict_cleanup = False

        def __init__(self, snap):
            self._snap = snap

        def status(self):
            return self._snap

    class _DeadLeaseClient:
        def close(self, *, timeout_seconds=5.0):
            raise ThreadedRuntimeError("NOT_READY")

    dead_snap = RuntimeSnapshot(
        state="failed", thread_alive=False, healthy=False,
        error_code="MAINTENANCE_FAILED", bindings=(), cleanup_failures=0,
        unregister_uncertainties=0, identity=ident, run_id="run-1",
        strict_unregister_ack=False, open_transport_count=0,
    )
    dead_api = _DeadApi(dead_snap)
    assert _session_runtime_terminated_after_failure(dead_api) is True

    # Strictly fail closed if runtime is still alive, strict, or close_failed.
    assert _session_runtime_terminated_after_failure(_DeadApi(RuntimeSnapshot(
        state="failed", thread_alive=True, healthy=False,
        error_code="MAINTENANCE_FAILED", bindings=(), cleanup_failures=0,
        unregister_uncertainties=0, identity=ident, run_id="run-1",
    ))) is False
    assert _session_runtime_terminated_after_failure(_DeadApi(RuntimeSnapshot(
        state="close_failed", thread_alive=False, healthy=False,
        error_code="CLEANUP_FAILED", bindings=(), cleanup_failures=1,
        unregister_uncertainties=0, identity=ident, run_id="run-1",
    ))) is False
    strict_api = _DeadApi(dead_snap)
    strict_api._gateway_strict_cleanup = True
    assert _session_runtime_terminated_after_failure(strict_api) is False

    adapter = GatewayMarketAdapter.__new__(GatewayMarketAdapter)
    claims = {"ticks": adapter}
    adapter._store = SimpleNamespace(
        _gateway_market_feed_claims=claims,
        _started=True,
        is_connected=False,
        gateway_api=dead_api,
        gateway_session_generation=0,
    )
    adapter._claims = claims
    adapter._claim_tombstones = {}
    adapter._claim_lock = threading.Lock()
    adapter._lifecycle_lock = threading.RLock()
    adapter._name = "ticks"
    adapter._api = dead_api
    adapter._lease_mode = True
    adapter._lease_client = _DeadLeaseClient()
    adapter._lease_api = dead_api
    adapter._retired_leases = []
    adapter._lease_attempted = True
    adapter._lease_candidate_api = None
    adapter._lease_acquire_state = "acquired"
    adapter._lease_release_confirmed = False
    adapter._lease_retired_on_dead_session_api = None
    adapter._lease_drain_pending = False
    adapter._closing = False
    adapter._closed = False
    adapter._clock_owned = False
    adapter._clock_started = False
    adapter._timeout_seconds = 3.0
    adapter._session_generation = 0
    adapter._projector = object()
    adapter._projector_client = adapter._lease_client
    adapter._qualifier = None
    adapter._last_event = adapter._last_receipt = None
    adapter._latest_event = adapter._latest_receipt = None
    adapter._pending_operation = None
    adapter._reason = "NOT_READY"
    adapter._attempt = 0
    adapter._next_retry = 0.0

    # Drain succeeds for the dead non-strict session WITHOUT falsely claiming
    # same-session owner-confirmed release.
    assert adapter.prepare_session_reconnect(dead_api, force=True, deadline=time.monotonic() + 5.0) is True
    assert adapter._lease_client is None
    assert adapter._lease_release_confirmed is False
    assert adapter._lease_retired_on_dead_session_api is dead_api
    assert adapter._lease_drain_pending is True

    # Calling prepare_session_reconnect on a LIVE session where close raises must STILL fail closed!
    live_snap = RuntimeSnapshot(
        state="running", thread_alive=True, healthy=True,
        error_code=None, bindings=(), cleanup_failures=0,
        unregister_uncertainties=0, identity=ident, run_id="run-1",
    )
    live_api = _DeadApi(live_snap)
    adapter._lease_client = _DeadLeaseClient()
    adapter._lease_api = live_api
    adapter._api = live_api
    adapter._lease_acquire_state = "acquired"
    adapter._lease_retired_on_dead_session_api = None
    assert adapter.prepare_session_reconnect(live_api, force=True, deadline=time.monotonic() + 5.0) is False
    assert adapter._reason == "GATEWAY_MARKET_LEASE_DRAIN_UNCONFIRMED"
    assert adapter._lease_client is not None

    # Adapter close() on a terminated session succeeds without setting _lease_release_confirmed.
    adapter._api = dead_api
    adapter._lease_api = dead_api
    adapter._lease_client = _DeadLeaseClient()
    adapter._lease_drain_pending = False
    adapter._reason = None
    adapter.close()
    assert adapter._closed is True
    assert adapter._lease_client is None
    assert adapter._lease_release_confirmed is False
    tombstone = adapter._claim_tombstones["ticks"]
    assert tombstone[3] is False


def test_gateway_reconnect_timeout_covers_configured_rpc_timeout_and_skips_dead_tcp(monkeypatch):
    import socket

    from backtrader.service import gateway_config as gc

    class _Cfg:
        def __init__(self, port: int, timeout_ms: int):
            self.client_config = SimpleNamespace(
                clients={"gateway": {"settings": {"options": {"request_timeout_ms": timeout_ms}}}},
                communication={
                    "profiles": {
                        "gw": {"backend": "zmq", "endpoints": {"rpc_connect": f"tcp://127.0.0.1:{port}"}}
                    }
                },
            )

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]

    store = SimpleNamespace(
        _command_shutdown_timeout=2.0,
        _gateway_strategy_config=_Cfg(closed_port, 10000),
    )
    assert gc._gateway_client_request_timeout_seconds(store) == 10.0

    # Non-GatewayBtApi fake skips TCP probe; real GatewayBtApi probes TCP and returns False on closed port.
    assert gc._gateway_rpc_endpoint_listening(store, object()) is True

    from bt_api_py.gateway_api import GatewayBtApi

    fake_gw_api = GatewayBtApi.__new__(GatewayBtApi)
    assert gc._gateway_rpc_endpoint_listening(store, fake_gw_api, timeout=0.05) is False

    # Open loopback listener -> returns True.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        open_port = listener.getsockname()[1]
        store_open = SimpleNamespace(
            _command_shutdown_timeout=2.0,
            _gateway_strategy_config=_Cfg(open_port, 10000),
        )
        assert gc._gateway_rpc_endpoint_listening(store_open, fake_gw_api, timeout=0.2) is True


def test_gateway_stream_next_handles_toctou_unavailable_without_crashing():
    from backtrader.brokers._btapi_gateway_stream import (
        GatewayExecutionStreamBrokerMixin,
        GatewayExecutionStreamError,
    )

    class _Broker(GatewayExecutionStreamBrokerMixin):
        pass

    broker = _Broker()
    binding = SimpleNamespace(state="ACTIVE", next_idle_read=0.0)
    broker._gateway_stream_binding = binding
    broker._gateway_unreachable = lambda reconnect=False: False
    broker._gateway_session_stale = lambda _b: False

    calls = []

    def fake_check(_b, *, connected_required=True):
        calls.append(connected_required)
        if connected_required:
            raise GatewayExecutionStreamError("GATEWAY_STREAM_GATEWAY_UNAVAILABLE")

    broker._gateway_stream_check = fake_check
    broker._gateway_stream_next()

    assert calls == [True, False]
    assert binding.state == "GATEWAY_UNAVAILABLE"
    assert binding.next_idle_read > 0.0
