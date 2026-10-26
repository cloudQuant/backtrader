"""Focused CTP wrapper compatibility tests for SDK startup observers."""

import sys
import types

import pytest

from backtrader.stores.btapistore import BtApiStoreError, _create_ctp_wrapper_class
from backtrader.stores.registered_sim import RegisteredSimStore


def _install_fake_ctp_sdk(monkeypatch, md_client, trader_client):
    package = types.ModuleType("bt_api_ctp")
    package.__path__ = []
    ctp_package = types.ModuleType("bt_api_ctp.ctp")
    ctp_package.__path__ = []
    client_module = types.ModuleType("bt_api_ctp.ctp.client")
    client_module.MdClient = md_client
    client_module.TraderClient = trader_client
    client_module._MdSpi = type("_MdSpi", (), {})
    client_module._TraderSpi = type("_TraderSpi", (), {})
    package.ctp = ctp_package
    ctp_package.client = client_module

    md_api_module = types.ModuleType("bt_api_ctp.ctp.ctp_md_api")
    md_api_module.CThostFtdcMdSpi = type("CThostFtdcMdSpi", (), {})
    structs_module = types.ModuleType("bt_api_ctp.ctp.ctp_structs_order")
    structs_module.CThostFtdcInputOrderActionField = type(
        "CThostFtdcInputOrderActionField", (), {}
    )
    structs_module.CThostFtdcInputOrderField = type("CThostFtdcInputOrderField", (), {})
    trader_api_module = types.ModuleType("bt_api_ctp.ctp.ctp_trader_api")
    trader_api_module.CThostFtdcTraderSpi = type("CThostFtdcTraderSpi", (), {})

    for name, module in (
        ("bt_api_ctp", package),
        ("bt_api_ctp.ctp", ctp_package),
        ("bt_api_ctp.ctp.client", client_module),
        ("bt_api_ctp.ctp.ctp_md_api", md_api_module),
        ("bt_api_ctp.ctp.ctp_structs_order", structs_module),
        ("bt_api_ctp.ctp.ctp_trader_api", trader_api_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)


def _fake_clients(md_start, trader_start):
    instances = {"md": [], "trader": []}

    class FakeMdClient:
        def __init__(self, **_kwargs):
            instances["md"].append(self)
            self.start_calls = []
            self.connection_generation = 1
            self.on_tick = None
            self.on_tick_with_generation = None
            self.on_disconnect = None
            self.on_disconnect_with_generation = None
            self.on_error = None

        start = md_start

        @staticmethod
        def wait_ready(timeout=20):
            del timeout
            return True

        @staticmethod
        def stop():
            return None

    class FakeTraderClient:
        def __init__(self, **_kwargs):
            instances["trader"].append(self)
            self.start_calls = []

        start = trader_start

        @staticmethod
        def wait_ready(timeout=20):
            del timeout
            return True

        @staticmethod
        def stop():
            return None

    return FakeMdClient, FakeTraderClient, instances


def _legacy_start(self, block=False):
    assert block is False
    self.start_calls.append({"block": block})


def _nojoin_start(self, *, block, join_observer):
    self.start_calls.append({"block": block, "join_observer": join_observer})


def _kwargs_only_start(self, **kwargs):
    self.start_calls.append(dict(kwargs))


def _wrapper_kwargs():
    return {
        "md_address": "tcp://127.0.0.1:1",
        "td_address": "tcp://127.0.0.1:2",
        "broker_id": "synthetic-broker",
        "investor_id": "synthetic-user",
        "password": "synthetic-only",
    }


def test_ctp_join_observer_defaults_to_legacy_start_calls(monkeypatch):
    md_cls, trader_cls, instances = _fake_clients(_legacy_start, _legacy_start)
    _install_fake_ctp_sdk(monkeypatch, md_cls, trader_cls)
    wrapper_cls = _create_ctp_wrapper_class()

    wrapper = wrapper_cls(**_wrapper_kwargs())
    assert wrapper.ctp_join_observer is True
    with pytest.raises(AttributeError):
        wrapper.ctp_join_observer = False

    wrapper.connect()

    assert len(instances["md"]) == len(instances["trader"]) == 1
    assert instances["md"][0].start_calls == [{"block": False}]
    assert instances["trader"][0].start_calls == [{"block": False}]
    wrapper.disconnect()


def test_ctp_join_observer_false_is_passed_to_both_sdk_clients(monkeypatch):
    md_cls, trader_cls, instances = _fake_clients(_nojoin_start, _nojoin_start)
    _install_fake_ctp_sdk(monkeypatch, md_cls, trader_cls)
    wrapper_cls = _create_ctp_wrapper_class()

    wrapper = wrapper_cls(**_wrapper_kwargs(), ctp_join_observer=False)
    assert wrapper.ctp_join_observer is False
    wrapper.connect()

    assert instances["md"][0].start_calls == [
        {"block": False, "join_observer": False}
    ]
    assert instances["trader"][0].start_calls == [
        {"block": False, "join_observer": False}
    ]
    wrapper.disconnect()


def test_ctp_join_observer_requires_an_exact_bool(monkeypatch):
    md_cls, trader_cls, instances = _fake_clients(_legacy_start, _legacy_start)
    _install_fake_ctp_sdk(monkeypatch, md_cls, trader_cls)
    wrapper_cls = _create_ctp_wrapper_class()

    with pytest.raises(TypeError, match="ctp_join_observer must be bool"):
        wrapper_cls(**_wrapper_kwargs(), ctp_join_observer=1)

    assert instances == {"md": [], "trader": []}


@pytest.mark.parametrize("unsupported_client", ("md", "trader"))
def test_ctp_nojoin_rejects_unsupported_sdk_before_client_or_auth_events(
    monkeypatch, unsupported_client
):
    md_start = _legacy_start if unsupported_client == "md" else _nojoin_start
    trader_start = _legacy_start if unsupported_client == "trader" else _nojoin_start
    md_cls, trader_cls, instances = _fake_clients(md_start, trader_start)
    _install_fake_ctp_sdk(monkeypatch, md_cls, trader_cls)
    wrapper_cls = _create_ctp_wrapper_class()
    store = RegisteredSimStore(
        api_cls=wrapper_cls,
        config=_wrapper_kwargs(),
        api_kwargs={"ctp_join_observer": False},
        autostart=False,
    )
    runtime_events = []
    monkeypatch.setattr(
        store,
        "emit_runtime_event",
        lambda event, **_kwargs: runtime_events.append(event),
    )

    with pytest.raises(BtApiStoreError, match="explicitly support block and join_observer"):
        store.start()

    assert instances == {"md": [], "trader": []}
    assert "store_connecting" not in runtime_events
    assert "store_auth_request" not in runtime_events


def test_ctp_nojoin_rejects_kwargs_only_start_before_client_or_auth_events(monkeypatch):
    md_cls, trader_cls, instances = _fake_clients(_kwargs_only_start, _kwargs_only_start)
    _install_fake_ctp_sdk(monkeypatch, md_cls, trader_cls)
    wrapper_cls = _create_ctp_wrapper_class()
    store = RegisteredSimStore(
        api_cls=wrapper_cls,
        config=_wrapper_kwargs(),
        api_kwargs={"ctp_join_observer": False},
        autostart=False,
    )
    runtime_events = []
    monkeypatch.setattr(
        store,
        "emit_runtime_event",
        lambda event, **_kwargs: runtime_events.append(event),
    )

    with pytest.raises(BtApiStoreError, match="explicitly support block and join_observer"):
        store.start()

    assert instances == {"md": [], "trader": []}
    assert "store_connecting" not in runtime_events
    assert "store_auth_request" not in runtime_events
