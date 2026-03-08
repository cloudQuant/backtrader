"""Placeholder coverage for providers not yet implemented via bt_api_py."""

import pytest

from backtrader.stores.btapistore import BtApiProviderNotImplementedError, BtApiStore


@pytest.mark.live
@pytest.mark.parametrize("provider", ["futu", "oanda", "vc"])
def test_placeholder_providers_fail_explicitly(provider):
    """Providers pending bt_api_py support should fail with a clear placeholder error."""
    store = BtApiStore(provider=provider)

    with pytest.raises(BtApiProviderNotImplementedError):
        store.start()


@pytest.mark.live
def test_unified_store_handles_supported_provider(btapi_store):
    """The unified store should still operate for implemented providers."""
    assert btapi_store.is_connected is True
    assert btapi_store.get_cash() == pytest.approx(2000.0)
    assert btapi_store.get_value() == pytest.approx(2150.0)
