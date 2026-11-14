"""Exercise Store option forwarding without constructing a Store or provider."""

from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore
from bt_api_py.direct_api_assembly import DirectApiAssembly, DirectApiAssemblyError


@pytest.mark.parametrize("origin,section", [
    ("config", "gateway"),
    ("api_kwargs", "gateway"),
    ("api_kwargs", "gateway_strategy"),
])
@pytest.mark.parametrize("value", [None, "none", {"service": "risk"}])
def test_store_forwarded_nested_risk_is_rejected(monkeypatch, origin, section, value):
    def forbidden(*_args, **_kwargs):
        pytest.fail("direct construction or factory must not run")

    monkeypatch.setattr(DirectApiAssembly, "__init__", forbidden)
    selected = {section: {"risk": value}}
    config = selected if origin == "config" else {}
    api_kwargs = selected if origin == "api_kwargs" else {}
    fake = SimpleNamespace(
        _sdk_direct_api_assembly=None,
        _config=config,
        _api_kwargs=api_kwargs,
        _sdk_execution_config_snapshot=dict,
        _sdk_direct_exchange_kwargs={},
        _api_cls=forbidden,
        _api=None,
        _sdk_exchanges={},
        _metadata_probe_service=SimpleNamespace(requires_market_data_only=False),
    )
    with pytest.raises(DirectApiAssemblyError, match="^risk_requires_gateway$"):
        BtApiStore._ensure_sdk_direct_api_assembly(fake)
    assert selected == {section: {"risk": value}}
    assert fake._sdk_direct_api_assembly is None


def test_selected_gateway_ready_path_does_not_construct_direct_assembly(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Gateway path must not construct a direct assembly")

    monkeypatch.setattr(DirectApiAssembly, "from_options", forbidden)
    api = object()
    fake = SimpleNamespace(_gateway_mode=True, _started=True, is_connected=True, _api=api)
    assert BtApiStore._ensure_api_ready(fake) is api
