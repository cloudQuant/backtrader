"""Focused contracts for the isolated public sdk_api handle guard."""

from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore


class FakeCtpSdk:
    def __init__(self):
        self.exchange_kwargs = {"CTP___FUTURE": {}}
        self.authority_calls = []
        self.write_calls = []
        self.query_calls = []
        self.connected = False

    def build_ctp_execution_approval_context(self, **kwargs):
        self.authority_calls.append(("context", kwargs))
        return {"context": True}

    def redeem_ctp_execution_approval(self, *args, **kwargs):
        self.authority_calls.append(("redeem", args, kwargs))
        return {"redeemed": True}

    def confirm_ctp_settlement_from_approval(self, *args, **kwargs):
        self.authority_calls.append(("settlement", args, kwargs))
        return {"confirmed": True}

    def reserve_ctp_execution_budget(self, *args, **kwargs):
        self.authority_calls.append(("budget", args, kwargs))
        return {"reserved": True}

    def submit_order(self, *_args, **_kwargs):
        self.write_calls.append("submit")

    def async_make_order(self, *_args, **_kwargs):
        self.write_calls.append("async_submit")

    def cancel_order(self, *_args, **_kwargs):
        self.write_calls.append("cancel")

    def ReqOrderInsert(self, *_args, **_kwargs):
        self.write_calls.append("raw_insert")

    def ReqOrderAction(self, *_args, **_kwargs):
        self.write_calls.append("raw_action")

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def get_balance(self):
        return {"cash": 100.0, "value": 100.0}

    def get_ctp_session_state(self):
        return {}

    def get_instrument_spec(self, *args):
        self.query_calls.append(tuple(args))
        symbol = args[-1]
        return {"symbol": symbol, "multiplier": 10, "price_tick": 0.2}

    def get_symbol_info(self, symbol):
        self.query_calls.append((symbol,))
        return {"symbol": symbol, "multiplier": 10, "price_tick": 0.2}


def test_managed_ctp_sdk_api_is_only_narrow_authority_view():
    api = FakeCtpSdk()
    store = BtApiStore(
        provider="btapi",
        api=api,
        exchange_kwargs={"CTP___FUTURE": {}},
    )

    view = store.sdk_api
    assert view is not None
    assert view is not api
    assert view.build_ctp_execution_approval_context(scope="test") == {"context": True}
    assert view.redeem_ctp_execution_approval("context") == {"redeemed": True}
    assert view.confirm_ctp_settlement_from_approval("approval") == {"confirmed": True}
    assert view.reserve_ctp_execution_budget("evidence", mode="ordinary") == {"reserved": True}
    assert [call[0] for call in api.authority_calls] == [
        "context",
        "redeem",
        "settlement",
        "budget",
    ]
    for name in (
        "submit_order",
        "async_make_order",
        "cancel_order",
        "ReqOrderInsert",
        "ReqOrderAction",
        "exchange_kwargs",
        "_api",
        "_invoke",
        "__dict__",
        "__getattr__",
        "_CtpSdkAuthorityView__api",
    ):
        with pytest.raises(AttributeError):
            getattr(view, name)
    with pytest.raises(AttributeError):
        type(view)._invoke(view, "submit_order")
    with pytest.raises(AttributeError):
        type(view).__getattr__(view, "submit_order")
    assert api.write_calls == []


def test_ctp_gateway_and_forwarding_sdk_handles_are_not_returned():
    api = FakeCtpSdk()
    gateway = BtApiStore(
        provider="ctp_gateway",
        backend="gateway",
        api=api,
        api_kwargs={"exchange_type": "CTP"},
    )
    forwarding = BtApiStore(
        provider="btapi",
        backend="forwarding",
        api=api,
        config={"exchange": "CTP"},
    )
    assert gateway.sdk_api is None
    assert forwarding.sdk_api is None


def test_ctp_direct_unmanaged_and_uncreated_sdk_handles_remain_none():
    assert BtApiStore(provider="ctp", api=FakeCtpSdk()).sdk_api is None
    store = BtApiStore(
        provider="btapi",
        exchange_kwargs={"CTP___FUTURE": {}},
    )
    assert store.sdk_api is None
    assert store._api is None


def test_non_ctp_direct_sdk_api_remains_compatible():
    api = SimpleNamespace(submit_order=lambda payload: payload)
    store = BtApiStore(provider="okx", api=api)
    assert store.sdk_api is api


def test_ctp_store_read_only_symbol_query_keeps_using_owned_api_internally():
    api = FakeCtpSdk()
    store = BtApiStore(provider="ctp", api=api)

    assert store.sdk_api is None
    metadata = store.get_symbol_info("IF2506")

    assert metadata["symbol"] == "IF2506"
    assert metadata["multiplier"] == 10
    assert api.query_calls == [("IF2506",)]
    assert api.connected is True
    assert api.write_calls == []
