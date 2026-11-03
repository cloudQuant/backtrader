"""Regression tests for detached read-only views inside tick snapshots."""

from dataclasses import dataclass
from types import MappingProxyType, SimpleNamespace

import pytest

from backtrader.utils.tick_snapshot import snapshot_tick


def test_nested_proxy_is_detached_through_builtin_containers():
    backing = {"levels": [1]}
    proxy = MappingProxyType(backing)
    snapshot = snapshot_tick({"metadata": {"inner": [proxy, (proxy,)]}})
    copied = snapshot["metadata"]["inner"][0]
    assert isinstance(copied, MappingProxyType)
    assert copied is snapshot["metadata"]["inner"][1][0]
    backing["levels"].append(2)
    assert copied["levels"] == [1]
    copied["levels"].append(3)
    assert backing["levels"] == [1, 2]


def test_proxy_and_mutable_container_cycles_are_preserved():
    backing = {}
    proxy = MappingProxyType(backing)
    backing["self"] = proxy
    child = []
    pair = (child,)
    child.append(pair)
    original = SimpleNamespace(proxy=proxy, pair=pair)
    result = snapshot_tick(original)
    assert result.proxy["self"] is result.proxy
    assert result.pair[0][0] is result.pair
    backing["late"] = 1
    assert "late" not in result.proxy


def test_unhandled_object_copy_errors_still_propagate():
    class CannotCopy:
        def __deepcopy__(self, memo):
            raise ValueError("cannot copy")

    with pytest.raises(ValueError, match="cannot copy"):
        snapshot_tick({"data": {"other": CannotCopy()}})


def test_frozen_contract_does_not_share_external_proxy_backing():
    @dataclass(frozen=True)
    class Contract:
        state: tuple

    Contract.__module__ = "bt_api_base._test_contract"
    source = {"levels": [1]}
    proxy = MappingProxyType(source)
    original = Contract((proxy, {"alias": proxy}))
    result = snapshot_tick({"payload": original})["payload"]
    assert result is not original
    assert result.state[0] is result.state[1]["alias"]
    source["levels"].append(2)
    assert result.state[0]["levels"] == [1]


def test_frozen_contract_proxy_cycle_is_detached():
    @dataclass(frozen=True)
    class Contract:
        state: object

    Contract.__module__ = "bt_api_base._test_contract"
    source = {}
    original = Contract(MappingProxyType(source))
    source["owner"] = original
    result = snapshot_tick({"payload": original})["payload"]
    assert result is not original
    assert result.state["owner"] is result
    source["late"] = 1
    assert "late" not in result.state


def test_real_market_provider_event_with_nested_proxy_is_detached():
    MarketProviderEvent = pytest.importorskip("bt_api_base.market_protocol").MarketProviderEvent

    source = {"levels": [1]}
    original = MarketProviderEvent(
        "generation", "2026-11-03T00:00:00Z", {"book": MappingProxyType(source)}
    )
    result = snapshot_tick({"payload": original})["payload"]
    source["levels"].append(2)
    assert result is not original
    assert result.data["book"]["levels"] == [1]


def test_top_level_market_provider_event_with_proxy_is_detached():
    MarketProviderEvent = pytest.importorskip("bt_api_base.market_protocol").MarketProviderEvent

    source = {"levels": [1]}
    original = MarketProviderEvent(
        "generation", "2026-11-03T00:00:00Z", {"book": MappingProxyType(source)}
    )
    result = snapshot_tick(original)
    assert result is not original
    source["levels"].append(2)
    assert result.data["book"]["levels"] == [1]
