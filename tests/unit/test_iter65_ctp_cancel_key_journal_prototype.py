"""Offline CTP cancel-key/Gateway journal composition, with synthetic identity.

The login callback and original order journal marker below are test fixtures,
not evidence of an authenticated account, an actual native send, a venue
order, authorization, or production behavior.  No dispatcher or native
cancel is called.  DISPATCHING is only the journal's local marker.
"""
import socket
import sys
from pathlib import Path

import pytest
from types import SimpleNamespace

from bt_api_base.direct_write_protocol import NativeOrderIdentity
from bt_api_ctp.ctp import client as ctp_client
from bt_api_ctp.direct_write_provider import CtpDirectWriteProvider
from bt_api_ctp.feeds.live_ctp_feed import CtpRequestDataFuture
from bt_api_gateway.direct_cancel_journal import GatewayDirectCancelJournal
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_dispatch import _identity
from bt_api_gateway.session_guard import LocalAccountSessionGuard


def _blocked(*_args, **_kwargs):
    raise AssertionError("connection, native request, or submission is forbidden")


class _BlockedNative:
    def __getattr__(self, _name):
        return _blocked


def test_real_ctp_preparations_enter_gateway_journal_independently(tmp_path, monkeypatch):
    # This synthetic session has no access to a native API or network.
    sdk_tree = Path(__file__).resolve().parents[3] / "bt_api_py"
    if not sdk_tree.is_dir():
        pytest.skip("the sibling bt_api_py source tree is unavailable")
    for cls in (ctp_client.TraderClient, CtpDirectWriteProvider, GatewayDirectCancelJournal):
        assert Path(sys.modules[cls.__module__].__file__).resolve().is_relative_to(sdk_tree)
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(ctp_client.TraderClient, "start", _blocked)
    monkeypatch.setattr(CtpRequestDataFuture, "connect", _blocked)
    monkeypatch.setattr(CtpRequestDataFuture, "_ensure_connected", _blocked)
    monkeypatch.setattr(CtpRequestDataFuture, "_ensure_read_only_connection_safe", _blocked)
    monkeypatch.setattr(CtpRequestDataFuture, "ensure_read_only_connected", _blocked)
    monkeypatch.setattr(CtpDirectWriteProvider, "submit_prepared_cancel", _blocked)
    front = "tcp://127.0.0.1:1"
    broker, user = "synthetic-broker", "synthetic-user"
    feed = CtpRequestDataFuture(broker_id=broker, user_id=user, password="synthetic",
                                td_front=front, md_front=front,
                                auto_settlement_confirm=False)
    trader = ctp_client.TraderClient(front, broker, user, "synthetic")
    native = _BlockedNative()
    trader._api = native
    trader._session_native_api = native
    trader._session_native_front = front
    trader._connected = True
    trader._authentication_state = "authenticated"
    trader._login_state = "logging_in"
    trader._connection_generation = 7
    trader._login_request_id = 1
    trader._login_connection_generation = 7
    spi = ctp_client._TraderSpi(trader, native_api=native)
    trader._spi = spi
    # Inject a synthetic callback locally; it is not a real login.
    spi.OnRspUserLogin(SimpleNamespace(BrokerID=broker, UserID=user, FrontID=1,
        SessionID=2, TradingDay="20261109", MaxOrderRef="7"),
        SimpleNamespace(ErrorID=0), 1, True)
    trader._settlement_state = "confirmed"
    trader._settlement_readback_verified = True
    trader._settlement_account_fingerprint = trader._account_fingerprint
    trader._settlement_trading_day = trader._trading_day
    trader._settlement_connection_generation = 7
    trader._ready = True
    trader._has_current_settlement_readback_locked = lambda: True
    feed._trader = trader
    provider = CtpDirectWriteProvider(feed, background_settlement_readback=False,
                                     allow_implicit_connect=False)
    target = NativeOrderIdentity("CTP___FUTURE", "000000000101", {
        "trading_day": "20261109", "exchange_id": "CZCE", "order_ref": "000000000101",
        "front_id": 3, "session_id": 9}, 6)
    first = provider.prepare_cancel_order(target, "SA2701")
    second = provider.prepare_cancel_order(target, "SA2701")
    assert first.target_identity == second.target_identity == target
    assert first.request_fields["RequestID"] != second.request_fields["RequestID"]
    assert first.request_keys != second.request_keys
    assert first.reservation_id != second.reservation_id

    guard_dir = tmp_path / "guard"
    guard_dir.mkdir()
    guard = LocalAccountSessionGuard(guard_dir, "synthetic-account", "synthetic-owner")
    generation = guard.acquire()
    try:
        journal = GatewayDirectCommandJournal.create(tmp_path / "gateway.sqlite", "synthetic-account",
                                                       generation=generation)
        order = journal.reserve("synthetic-strategy", "synthetic-order", "synthetic-principal",
                                {"symbol": "SA2701", "side": "buy", "quantity": "1"})
        # Seed a local synthetic dispatch marker only; no place was sent.
        order = journal.begin_dispatch("synthetic-strategy", order.request_key, order.reservation_id,
            order.digest, "synthetic-principal", order.version, _identity(target, "CTP___FUTURE"),
            ("synthetic-order-key",)).record
        assert order.status == "DISPATCHING"
        cancel = GatewayDirectCancelJournal(journal)
        starts = []
        for operation, prepared in (("cancel-1", first), ("cancel-2", second)):
            row = cancel.request("synthetic-strategy", operation, "synthetic-principal",
                order.request_key, order.reservation_id, order.digest,
                target_identity=target, symbol="SA2701")
            started = cancel.begin_dispatch("synthetic-strategy", operation, "synthetic-principal",
                                            row.version, prepared)
            assert started.newly_started
            assert started.record.status == "DISPATCHING"
            assert cancel.get("synthetic-strategy", operation, "synthetic-principal") == started.record
            assert not cancel.begin_dispatch("synthetic-strategy", operation, "synthetic-principal",
                                             row.version, prepared).newly_started
            starts.append(started.record)
        assert starts[0].attempt_id != starts[1].attempt_id
        assert starts[0].prepared_digest == first.digest()
        assert starts[1].prepared_digest == second.digest()
        assert journal.get("synthetic-strategy", "synthetic-order", "synthetic-principal").status == "DISPATCHING"
    finally:
        guard.release()
