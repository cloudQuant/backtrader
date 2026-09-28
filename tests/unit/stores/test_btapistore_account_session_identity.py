from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError

VENUE = "BINANCE___SPOT"
SYMBOL = "BTC-USDT"
_FINGERPRINT_A = "a" * 64
_FINGERPRINT_B = "b" * 64


class IdentityApi:
    def __init__(self):
        self.exchange_kwargs = {VENUE: {"environment": "demo"}}
        self.identity = {
            "provider": "BINANCE",
            "environment": "demo",
            "account_id": f"binance-credential-{_FINGERPRINT_A}",
            "credential_fingerprint": _FINGERPRINT_A,
            "account_authority": "credential_fingerprint",
            "exchange_name": VENUE,
            "strategy_id": "store-identity-test",
            "fencing_epoch": 1,
        }
        self.calls = []
        self.writer_lookups = []

    def get_execution_identity(self, venue):
        assert venue == VENUE
        return deepcopy(self.identity)

    def __getattribute__(self, name):
        if name in {"async_make_order", "async_cancel_order"}:
            object.__getattribute__(self, "writer_lookups").append(name)
        return object.__getattribute__(self, name)

    async def async_make_order(self, venue, request, *, normalized=False):
        self.calls.append(("submit", venue, request.account_id, normalized))
        return {"kind": "order", "status": "submitted"}

    async def async_cancel_order(self, venue, request, *, normalized=False):
        self.calls.append(("cancel", venue, request.account_id, normalized))
        return {"kind": "order", "status": "cancelled"}


def _store(api):
    return BtApiStore(
        provider="btapi",
        api=api,
        backend="direct",
        config={
            "exchange_kwargs": {VENUE: {"environment": "demo"}},
            "symbol_routes": {SYMBOL: VENUE},
            "execution_config": {
                "market_data_only": False,
                "strategy_id": "store-identity-test",
            },
        },
    )


def _command(operation, account_id):
    return {
        "operation": operation,
        "venue": VENUE,
        "request": SimpleNamespace(account_id=account_id),
    }


@pytest.mark.parametrize("operation", ["submit", "cancel"])
@pytest.mark.parametrize("identity_change", ["account", "fencing_epoch"])
def test_async_write_rechecks_account_identity_before_writer_lookup(
    operation, identity_change
):
    api = IdentityApi()
    store = _store(api)
    old_account_id = store._sdk_account_id(VENUE)

    if identity_change == "account":
        api.identity.update(
            account_id=f"binance-credential-{_FINGERPRINT_B}",
            credential_fingerprint=_FINGERPRINT_B,
        )
    else:
        api.identity["fencing_epoch"] = 2

    with pytest.raises(BtApiStoreError, match="execution_identity_changed_within_session"):
        asyncio.run(store._invoke_sdk_command(operation, _command(operation, old_account_id)))

    assert api.writer_lookups == []
    assert api.calls == []


def test_async_write_rejects_request_account_mismatch_before_writer_lookup():
    api = IdentityApi()
    store = _store(api)
    expected_account_id = store._sdk_account_id(VENUE)

    with pytest.raises(BtApiStoreError, match="does not match the SDK ledger"):
        asyncio.run(store._invoke_sdk_command("submit", _command("submit", "other-account")))

    assert api.writer_lookups == []
    assert api.calls == []
    assert expected_account_id != "other-account"


@pytest.mark.parametrize("operation", ["submit", "cancel"])
def test_async_write_keeps_same_session_identity_positive(operation):
    api = IdentityApi()
    store = _store(api)
    account_id = store._sdk_account_id(VENUE)

    result = asyncio.run(store._invoke_sdk_command(operation, _command(operation, account_id)))

    assert result["status"] in {"submitted", "cancelled"}
    assert api.writer_lookups == [
        "async_make_order" if operation == "submit" else "async_cancel_order"
    ]
    assert api.calls == [(operation, VENUE, account_id, True)]


def test_async_write_rejects_missing_request_account_before_writer_lookup():
    api = IdentityApi()
    store = _store(api)
    store._sdk_account_id(VENUE)

    with pytest.raises(BtApiStoreError, match="request account identity is unavailable"):
        asyncio.run(
            store._invoke_sdk_command(
                "cancel", {"operation": "cancel", "venue": VENUE, "request": object()}
            )
        )

    assert api.writer_lookups == []
    assert api.calls == []


def test_async_write_rejects_lost_identity_reader_after_enqueue_binding():
    api = IdentityApi()
    store = _store(api)
    account_id = store._sdk_account_id(VENUE)
    api.get_execution_identity = None

    with pytest.raises(BtApiStoreError, match="execution_identity_unavailable"):
        asyncio.run(store._invoke_sdk_command("submit", _command("submit", account_id)))

    assert api.writer_lookups == []
    assert api.calls == []
