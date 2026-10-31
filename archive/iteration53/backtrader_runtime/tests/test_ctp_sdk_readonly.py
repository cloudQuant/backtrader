"""Offline contract tests for the SDK-backed, zero-trading-write CTP factory."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from backtrader_runtime.ctp_preflight import CtpReadOnlySessionRequest
from backtrader_runtime.ctp_sdk_readonly import (
    CtpSdkReadOnlyError,
    CtpSdkReadOnlyCloseEvidence,
    CtpSdkReadOnlyScope,
    CtpSdkReadOnlySessionFactory,
)

ACCOUNT_FP = hashlib.sha256(b"9999:demo").hexdigest()
# Reserved documentation-only addresses: the adapter must use the exact
# sealed pair, not infer a SimNow set or silently substitute a known endpoint.
TD_FRONT = "tcp://192.0.2.17:41201"
MD_FRONT = "tcp://192.0.2.18:41202"
_WRITE_KEYS = ("settlement_confirm", "order_insert", "order_action")
_QUERY_NAMES = (
    "account",
    "positions",
    "orders",
    "trades",
    "instruments",
    "margin_rate",
    "commission_rate",
)


class _Credentials:
    def __init__(self, *, user_id: str = "demo") -> None:
        self.values = {
            "broker_id": "9999",
            "user_id": user_id,
            "password": "hidden-password",
            "app_id": "reviewed-app",
            "auth_code": "hidden-auth-code",
        }
        self.calls = []

    def require_credential(self, name: str) -> str:
        self.calls.append(name)
        return self.values[name]


class _FakeClient:
    instances = []
    fail_start = False
    join_behavior = "complete"
    bound_front_override = None

    def __init__(
        self,
        front,
        broker_id,
        user_id,
        password,
        *,
        app_id,
        auth_code,
        auto_settlement_confirm,
    ) -> None:
        assert front == TD_FRONT
        assert (broker_id, user_id) == ("9999", "demo")
        assert password == "hidden-password"
        assert app_id == "reviewed-app"
        assert auth_code == "hidden-auth-code"
        assert auto_settlement_confirm is False
        self.started = False
        self.stopped = 0
        self._thread = None
        self._join_active = False
        self._native_init_started = False
        self.front = front
        self.calls = []
        self.counts = dict.fromkeys(_WRITE_KEYS, 0)
        self.instances.append(self)

    def start(self, *, block: bool) -> None:
        assert block is False
        if self.fail_start:
            raise RuntimeError("hidden-password must never escape")
        self.started = True
        if self.join_behavior in ("pending", "complete_on_stop"):
            self.join_release = threading.Event()
            self._join_active = True
            self._native_init_started = True

            def join() -> None:
                self.join_release.wait()
                self._join_active = False
                self._native_init_started = False

            self._thread = threading.Thread(target=join, daemon=True)
            self._thread.start()

    def wait_ready(self, *, timeout: float) -> bool:
        assert 0 < timeout <= 15
        return True

    def stop(self) -> None:
        self.stopped += 1
        if self.join_behavior == "complete_on_stop":
            self.join_release.set()

    def get_session_state(self):
        return {"auto_settlement_confirm": False}

    def get_query_session_scope(self):
        return SimpleNamespace(
            read_only_ready=True,
            broker_id="9999",
            investor_id="demo",
            trading_day="20260923",
            connection_generation=7,
        )

    def get_front_binding_state(self):
        bound_front = self.bound_front_override or self.front
        return {
            "configured_front": self.front,
            "registered_front": self.front,
            "connection_confirmed_front": bound_front,
            "connected": True,
            "native_api_current": True,
            "bound_identity_current": True,
            "connection_generation": 7,
        }

    def get_request_counts(self):
        return dict(self.counts)

    def _query(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return name

    def query_account_result(self, **kwargs):
        return self._query("account", **kwargs)

    def query_positions_result(self, **kwargs):
        return self._query("positions", **kwargs)

    def query_orders_result(self, **kwargs):
        return self._query("orders", **kwargs)

    def query_trades_result(self, **kwargs):
        return self._query("trades", **kwargs)

    def query_instruments_result(self, **kwargs):
        return self._query("instruments", **kwargs)

    def query_instrument_margin_rate_result(self, instrument_id, **kwargs):
        return self._query("margin_rate", instrument_id=instrument_id, **kwargs)

    def query_instrument_commission_rate_result(self, instrument_id, **kwargs):
        return self._query("commission_rate", instrument_id=instrument_id, **kwargs)


class _FakeBuilder:
    def __init__(self, client, *, instrument_id, exchange_id, hedge_flag) -> None:
        assert isinstance(client, _FakeClient)
        assert (instrument_id, exchange_id, hedge_flag) == ("IF2612", "CFFEX", "1")
        self.names = []

    def add(self, result):
        self.names.append(result)

    def finish(self):
        assert tuple(self.names) == _QUERY_NAMES
        query_digests = tuple(
            (name, hashlib.sha256(name.encode("ascii")).hexdigest()) for name in self.names
        )
        certificate_sha256 = hashlib.sha256(b"fake-native-certificate").hexdigest()
        public = {
            "schema": "ctp_native_query_certificate.v5",
            "complete": True,
            "atomic_snapshot": False,
            "execution_authorized": False,
            "query_digest": certificate_sha256,
            "certificate_sha256": certificate_sha256,
            "queries": [
                {
                    "request_type": name,
                    "records_sha256": digest,
                    "rate_exchange_scope": (
                        "unverified"
                        if name == "margin_rate"
                        else "exact"
                        if name == "commission_rate"
                        else None
                    ),
                }
                for name, digest in query_digests
            ],
        }
        return SimpleNamespace(
            query_digests=query_digests,
            certificate_sha256=certificate_sha256,
            as_public_dict=lambda: public,
        )


class _FakeStopReceipt:
    def __init__(
        self,
        *,
        connection_generation=7,
        join_required=True,
        join_completed=True,
        native_released=True,
        thread_alive=False,
        timed_out=False,
        client_stop_returned=True,
        complete=None,
    ) -> None:
        self.connection_generation = connection_generation
        self.join_required = join_required
        self.join_completed = join_completed
        self.native_released = native_released
        self.thread_alive = thread_alive
        self.timed_out = timed_out
        self.client_stop_returned = client_stop_returned
        self._complete = (
            native_released
            and (not join_required or join_completed)
            and thread_alive is False
            and not timed_out
            and client_stop_returned is True
            if complete is None
            else complete
        )

    @property
    def complete(self):
        return self._complete


class _StopReceiptClient(_FakeClient):
    stop_receipt = _FakeStopReceipt()
    stop_failure = False
    stop_and_wait_calls = []

    def stop_and_wait(self, *, timeout):
        self.stop_and_wait_calls.append(timeout)
        self.stop()
        if self.stop_failure:
            raise RuntimeError("hidden-password must never escape")
        return self.stop_receipt


def _scope() -> CtpSdkReadOnlyScope:
    return CtpSdkReadOnlyScope(
        environment="simnow",
        sdk_profile="config_front_pair",
        td_front=TD_FRONT,
        md_front=MD_FRONT,
        account_fingerprint_sha256=ACCOUNT_FP,
        instrument_id="IF2612",
        exchange_id="CFFEX",
        hedge_flag="1",
    )


def _request(**changes) -> CtpReadOnlySessionRequest:
    values = {
        "provider": "ctp",
        "environment": "simnow",
        "account_fingerprint_sha256": ACCOUNT_FP,
        "valid_until": time.time() + 120,
    }
    values.update(changes)
    return CtpReadOnlySessionRequest(**values)


def _components():
    return _FakeClient, _FakeBuilder


def _receipt_components(client_type=_StopReceiptClient, receipt_type=_FakeStopReceipt):
    return client_type, _FakeBuilder, receipt_type


def _factory(credentials=None, components=_components):
    return CtpSdkReadOnlySessionFactory(
        _scope(), credentials or _Credentials(), sdk_components_loader=components
    )


def test_native_factory_reads_seven_queries_and_never_calls_a_trading_write() -> None:
    _FakeClient.instances.clear()
    assert ACCOUNT_FP not in repr(_scope())
    factory = _factory()
    session = factory.open_read_only(_request())
    client = _FakeClient.instances[-1]
    try:
        identity = session.read_identity()
        snapshot = session.read_query_snapshot()
        assert identity.account_fingerprint_sha256 == ACCOUNT_FP
        assert snapshot.identity == identity
        assert (
            snapshot.native_certificate_sha256
            == hashlib.sha256(b"fake-native-certificate").hexdigest()
        )
        assert snapshot.rate_exchange_scopes == (
            ("commission_rates", "exact"),
            ("margin_rates", "unverified"),
        )
        assert dict(snapshot.query_digests).keys() == {
            "account",
            "positions",
            "orders",
            "trades",
            "instruments",
            "margin_rates",
            "commission_rates",
        }
        assert [name for name, _ in client.calls] == list(_QUERY_NAMES)
        assert client.calls[4][1]["instrument_id"] == "IF2612"
        assert client.calls[5][1]["hedge_flag"] == "1"
        assert client.counts == dict.fromkeys(_WRITE_KEYS, 0)
        assert not hasattr(session, "submit_order")
        assert not hasattr(session, "cancel_order")
        assert not hasattr(session, "confirm_settlement")
    finally:
        session.close_read_only()
    assert client.stopped == 1


@pytest.mark.parametrize("bad_scope", (None, "unknown", 1))
def test_native_factory_rejects_missing_or_invalid_rate_exchange_scope(bad_scope) -> None:
    class _MalformedBuilder(_FakeBuilder):
        def finish(self):
            certificate = super().finish()
            public = certificate.as_public_dict()
            for row in public["queries"]:
                if row["request_type"] == "margin_rate":
                    row["rate_exchange_scope"] = bad_scope
            return SimpleNamespace(
                query_digests=certificate.query_digests,
                certificate_sha256=certificate.certificate_sha256,
                as_public_dict=lambda: public,
            )

    _FakeClient.instances.clear()
    session = _factory(components=lambda: (_FakeClient, _MalformedBuilder)).open_read_only(
        _request()
    )
    try:
        with pytest.raises(CtpSdkReadOnlyError) as caught:
            session.read_query_snapshot()
        assert caught.value.reason == "native_rate_exchange_scope_invalid"
    finally:
        session.close_read_only()


def test_native_factory_rejects_certificate_without_scope_metadata() -> None:
    class _NoScopeBuilder(_FakeBuilder):
        def finish(self):
            certificate = super().finish()
            public = certificate.as_public_dict()
            for row in public["queries"]:
                if row["request_type"] == "commission_rate":
                    row.pop("rate_exchange_scope")
            return SimpleNamespace(
                query_digests=certificate.query_digests,
                certificate_sha256=certificate.certificate_sha256,
                as_public_dict=lambda: public,
            )

    session = _factory(components=lambda: (_FakeClient, _NoScopeBuilder)).open_read_only(_request())
    try:
        with pytest.raises(CtpSdkReadOnlyError) as caught:
            session.read_query_snapshot()
        assert caught.value.reason == "native_rate_exchange_scope_invalid"
    finally:
        session.close_read_only()


def test_close_waits_for_native_join_to_finish_within_the_bounded_grace() -> None:
    _FakeClient.instances.clear()
    _FakeClient.join_behavior = "complete_on_stop"
    session = _factory().open_read_only(_request())
    client = _FakeClient.instances[-1]
    try:
        session.read_query_snapshot()
        session.close_read_only()
        assert client.stopped == 1
        assert client._thread is not None and not client._thread.is_alive()
        assert client._join_active is False
        assert client._native_init_started is False
    finally:
        _FakeClient.join_behavior = "complete"


def test_close_rejects_unknown_or_pending_native_join_and_still_stops_client() -> None:
    _FakeClient.instances.clear()
    _FakeClient.join_behavior = "pending"
    session = _factory().open_read_only(_request())
    client = _FakeClient.instances[-1]
    try:
        with pytest.raises(CtpSdkReadOnlyError) as caught:
            session.close_read_only()
        assert caught.value.reason == "session_close_incomplete"
        assert client.stopped == 1
        assert client._thread is not None and client._thread.is_alive()
        client.join_release.set()
        client._thread.join(1.0)
    finally:
        _FakeClient.join_behavior = "complete"


def test_close_rejects_pending_join_captured_before_sdk_clears_client_state() -> None:
    """Keep the native Join witness across SDK stop's logical state reset."""

    class _ClientWhoseStopClearsState(_FakeClient):
        def stop(self) -> None:
            super().stop()
            self._thread = None
            self._join_active = False
            self._native_init_started = False

    _FakeClient.instances.clear()
    _FakeClient.join_behavior = "pending"
    session = _factory(
        components=lambda: (_ClientWhoseStopClearsState, _FakeBuilder)
    ).open_read_only(_request())
    client = _FakeClient.instances[-1]
    pending_thread = client._thread
    assert pending_thread is not None
    try:
        with pytest.raises(CtpSdkReadOnlyError) as caught:
            session.close_read_only()
        assert caught.value.reason == "session_close_incomplete"
        assert client.stopped == 1
        assert client._thread is None
        assert client._join_active is False
        assert client._native_init_started is False
        assert pending_thread.is_alive()

        # A failed close cannot later be reported as complete from the SDK's
        # cleared bookkeeping flags alone.
        with pytest.raises(CtpSdkReadOnlyError) as caught:
            session.close_read_only()
        assert caught.value.reason == "session_close_incomplete"
    finally:
        client.join_release.set()
        pending_thread.join(1.0)
        _FakeClient.join_behavior = "complete"


def test_public_stop_receipt_accepts_exact_positive_shutdown_evidence() -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = False
    _StopReceiptClient.stop_receipt = _FakeStopReceipt()
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())
    client = _FakeClient.instances[-1]

    session.close_read_only()

    assert _StopReceiptClient.stop_and_wait_calls == [1.0]
    assert client.stopped == 1


def test_public_stop_receipt_timeout_keeps_session_close_incomplete() -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = False
    _StopReceiptClient.stop_receipt = _FakeStopReceipt(
        join_completed=False,
        native_released=False,
        thread_alive=True,
        timed_out=True,
    )
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())
    client = _FakeClient.instances[-1]

    with pytest.raises(CtpSdkReadOnlyError) as caught:
        session.close_read_only()

    assert caught.value.reason == "session_close_incomplete"
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]
    assert client.stopped == 1
    with pytest.raises(CtpSdkReadOnlyError) as caught:
        session.close_read_only()
    assert caught.value.reason == "session_close_incomplete"
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]


def test_public_stop_receipt_rejects_forged_receipt_type() -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = False
    _StopReceiptClient.stop_receipt = SimpleNamespace(
        connection_generation=7,
        join_required=True,
        join_completed=True,
        native_released=True,
        thread_alive=False,
        timed_out=False,
        complete=True,
    )
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())
    client = _FakeClient.instances[-1]

    with pytest.raises(CtpSdkReadOnlyError) as caught:
        session.close_read_only()

    assert caught.value.reason == "session_close_receipt_untrusted"
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]
    assert client.stopped == 1


def test_public_stop_receipt_rejects_inconsistent_complete_claim() -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = False
    _StopReceiptClient.stop_receipt = _FakeStopReceipt(
        native_released=True,
        thread_alive=True,
        complete=True,
    )
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())

    with pytest.raises(CtpSdkReadOnlyError) as caught:
        session.close_read_only()

    assert caught.value.reason == "session_close_receipt_invalid"
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]


def test_public_stop_receipt_must_match_opened_connection_generation() -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = False
    _StopReceiptClient.stop_receipt = _FakeStopReceipt(connection_generation=8)
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())

    with pytest.raises(CtpSdkReadOnlyError) as caught:
        session.close_read_only()

    assert caught.value.reason == "session_close_receipt_invalid"
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]


def test_close_evidence_projects_a_complete_exact_stop_receipt_once() -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = False
    _StopReceiptClient.stop_receipt = _FakeStopReceipt()
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())
    client = _FakeClient.instances[-1]

    evidence = session.close_read_only_with_evidence()

    assert type(evidence) is CtpSdkReadOnlyCloseEvidence
    assert evidence.status == "complete"
    assert evidence.verified_complete is True
    assert evidence.native_join_pending is False
    assert evidence.native_released is True
    assert evidence.join_required is True
    assert evidence.join_completed is True
    assert evidence.thread_alive is False
    assert evidence.timed_out is False
    assert evidence.client_stop_returned is True
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]
    assert client.stopped == 1

    assert session.close_read_only_with_evidence() is evidence
    session.close_read_only()
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]


def test_close_evidence_marks_only_explicit_incomplete_join_as_pending() -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = False
    _StopReceiptClient.stop_receipt = _FakeStopReceipt(
        join_completed=False,
        native_released=False,
        thread_alive=True,
        timed_out=True,
    )
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())

    evidence = session.close_read_only_with_evidence()

    assert evidence.status == "native_join_pending"
    assert evidence.native_join_pending is True
    assert evidence.verified_complete is False
    assert evidence.join_required is True
    assert evidence.join_completed is False
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]
    assert session.close_read_only_with_evidence() is evidence
    with pytest.raises(CtpSdkReadOnlyError) as caught:
        session.close_read_only()
    assert caught.value.reason == "session_close_incomplete"
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]


@pytest.mark.parametrize(
    "receipt_mutator",
    (
        lambda receipt: setattr(receipt, "native_released", False),
        lambda receipt: setattr(receipt, "client_stop_returned", False),
        lambda receipt: delattr(receipt, "client_stop_returned"),
    ),
)
def test_close_evidence_keeps_incomplete_or_missing_receipt_facts_unknown(
    receipt_mutator,
) -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = False
    receipt = _FakeStopReceipt()
    receipt_mutator(receipt)
    _StopReceiptClient.stop_receipt = receipt
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())

    evidence = session.close_read_only_with_evidence()

    assert evidence.status == "unknown"
    assert evidence.native_join_pending is False
    assert evidence.verified_complete is False
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]


def test_close_evidence_does_not_infer_join_pending_from_stop_exception() -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = True
    _StopReceiptClient.stop_receipt = _FakeStopReceipt(
        join_completed=False,
        native_released=False,
        thread_alive=True,
        timed_out=True,
    )
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())
    client = _FakeClient.instances[-1]

    evidence = session.close_read_only_with_evidence()

    assert evidence.status == "unknown"
    assert evidence.native_join_pending is False
    assert evidence.verified_complete is False
    assert _StopReceiptClient.stop_and_wait_calls == [1.0]
    assert client.stopped == 1


def test_close_evidence_keeps_legacy_python_thread_fallback_unverified() -> None:
    _FakeClient.instances.clear()
    _FakeClient.join_behavior = "complete"
    session = _factory().open_read_only(_request())
    client = _FakeClient.instances[-1]

    evidence = session.close_read_only_with_evidence()

    assert evidence.status == "unknown"
    assert evidence.native_join_pending is False
    assert evidence.verified_complete is False
    assert client.stopped == 1


def test_public_stop_and_wait_failure_is_redacted_and_never_retried() -> None:
    _FakeClient.instances.clear()
    _StopReceiptClient.stop_and_wait_calls = []
    _StopReceiptClient.stop_failure = True
    _StopReceiptClient.stop_receipt = _FakeStopReceipt()
    session = _factory(components=lambda: _receipt_components()).open_read_only(_request())
    client = _FakeClient.instances[-1]

    try:
        with pytest.raises(CtpSdkReadOnlyError) as caught:
            session.close_read_only()
        assert caught.value.reason == "session_close_failed"
        assert "hidden-password" not in str(caught.value)
        assert _StopReceiptClient.stop_and_wait_calls == [1.0]
        assert client.stopped == 1
    finally:
        _StopReceiptClient.stop_failure = False


def test_open_failure_preserves_primary_reason_and_reports_cleanup_failure() -> None:
    class _ClientFailingReadinessAndStop(_FakeClient):
        def wait_ready(self, *, timeout: float) -> bool:
            assert 0 < timeout <= 15
            return False

        def stop(self) -> None:
            self.stopped += 1
            raise RuntimeError("hidden-password must never escape")

    _FakeClient.instances.clear()
    with pytest.raises(CtpSdkReadOnlyError) as caught:
        _factory(components=lambda: (_ClientFailingReadinessAndStop, _FakeBuilder)).open_read_only(
            _request()
        )

    assert caught.value.reason == "session_not_read_only_ready"
    assert caught.value.cleanup_reason == "session_close_failed"
    assert "hidden-password" not in str(caught.value)
    assert _FakeClient.instances[-1].stopped == 1


def test_invalid_environment_or_credential_identity_never_loads_sdk() -> None:
    loads = []

    def reject_load():
        loads.append(True)
        raise AssertionError("SDK loader must not run")

    credentials = _Credentials()
    factory = _factory(credentials, reject_load)
    with pytest.raises(CtpSdkReadOnlyError) as caught:
        factory.open_read_only(_request(environment="simnow_set1"))
    assert caught.value.reason == "environment_mismatch"
    assert credentials.calls == []

    bad_credentials = _Credentials(user_id="other")
    factory = _factory(bad_credentials, reject_load)
    with pytest.raises(CtpSdkReadOnlyError) as caught:
        factory.open_read_only(_request())
    assert caught.value.reason == "credential_account_mismatch"
    assert bad_credentials.calls == ["broker_id", "user_id"]
    assert loads == []


def test_expired_request_rejects_before_secrets_or_sdk() -> None:
    credentials = _Credentials()
    factory = _factory(credentials)
    with pytest.raises(CtpSdkReadOnlyError) as caught:
        factory.open_read_only(_request(valid_until=time.time() - 1))
    assert caught.value.reason == "session_deadline_expired"
    assert credentials.calls == []


def test_sdk_start_failure_stops_native_client_and_redacts_error() -> None:
    _FakeClient.instances.clear()
    _FakeClient.fail_start = True
    try:
        with pytest.raises(CtpSdkReadOnlyError) as caught:
            _factory().open_read_only(_request())
        assert caught.value.reason == "session_open_failed"
        assert "hidden-password" not in str(caught.value)
        assert _FakeClient.instances[-1].stopped == 1
    finally:
        _FakeClient.fail_start = False


def test_native_write_counter_change_aborts_query_snapshot() -> None:
    _FakeClient.instances.clear()
    session = _factory().open_read_only(_request())
    client = _FakeClient.instances[-1]
    client.counts["order_action"] = 1
    try:
        with pytest.raises(CtpSdkReadOnlyError) as caught:
            session.read_query_snapshot()
        assert caught.value.reason == "native_write_detected"
        assert client.calls == []
    finally:
        session.close_read_only()


def test_scope_requires_neutral_config_pair_labels_and_canonical_tcp_fronts() -> None:
    with pytest.raises(ValueError, match="sealed SimNow config binding"):
        CtpSdkReadOnlyScope(
            environment="simnow_set2",
            sdk_profile="set2_7x24",
            td_front=TD_FRONT,
            md_front=MD_FRONT,
            account_fingerprint_sha256=ACCOUNT_FP,
            instrument_id="IF2612",
            exchange_id="CFFEX",
            hedge_flag="1",
        )
    with pytest.raises(ValueError, match="invalid configured front"):
        CtpSdkReadOnlyScope(
            environment="simnow",
            sdk_profile="config_front_pair",
            td_front="tcp://example.test:41201/path",
            md_front=MD_FRONT,
            account_fingerprint_sha256=ACCOUNT_FP,
            instrument_id="IF2612",
            exchange_id="CFFEX",
            hedge_flag="1",
        )


def test_factory_snapshots_code_owned_scope_before_a_mutation() -> None:
    scope = _scope()
    factory = CtpSdkReadOnlySessionFactory(scope, _Credentials(), sdk_components_loader=_components)
    object.__setattr__(scope, "sdk_profile", "other_profile")
    object.__setattr__(scope, "environment", "production")

    session = factory.open_read_only(_request())
    try:
        assert session.read_identity().environment == "simnow"
    finally:
        session.close_read_only()


def test_selected_unlisted_front_pair_is_passed_exactly_and_bound_to_td_session() -> None:
    _FakeClient.instances.clear()
    session = _factory().open_read_only(_request())
    client = _FakeClient.instances[-1]
    try:
        assert client.front == TD_FRONT
        assert session.read_identity().environment == "simnow"
    finally:
        session.close_read_only()


def test_authenticated_td_session_rejects_a_different_connected_front() -> None:
    _FakeClient.instances.clear()
    _FakeClient.bound_front_override = "tcp://192.0.2.99:41203"
    try:
        with pytest.raises(CtpSdkReadOnlyError) as caught:
            _factory().open_read_only(_request())
        assert caught.value.reason == "session_front_binding_mismatch"
        assert _FakeClient.instances[-1].stopped == 1
    finally:
        _FakeClient.bound_front_override = None


def test_adapter_import_does_not_load_sdk_or_provider_modules() -> None:
    script = """
import sys
import backtrader_runtime.ctp_sdk_readonly
assert not any(name == item or name.startswith(item + '.') for item in ('bt_api', 'bt_api_py', 'bt_api_ctp') for name in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
