"""Store checks every original Risk selection before direct option merging."""

from collections.abc import Mapping

import pytest

import backtrader.stores.btapistore as store_module
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError


class ReachedConfiguration(Exception):
    """The Store passed its Risk selection check without starting an API."""


def _unreachable_factory(**_kwargs):
    pytest.fail("the Store must not construct an API")


@pytest.mark.parametrize("value", [None, "none", {"service": "risk"}])
@pytest.mark.parametrize("source", ["config", "api_kwargs", "kwargs"])
def test_gateway_risk_in_each_original_direct_source_is_rejected(source, value):
    arguments = {"api_cls": _unreachable_factory}
    if source == "kwargs":
        arguments["gateway"] = {"risk": value}
    else:
        arguments[source] = {"gateway": {"risk": value}}
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(**arguments)
    assert str(error.value) == "risk_requires_gateway"
    assert error.value.code == "risk_requires_gateway"


@pytest.mark.parametrize("source", ["api_kwargs", "kwargs"])
@pytest.mark.parametrize("value", [None, "none", {"service": "risk"}])
def test_unselected_gateway_strategy_risk_is_rejected(source, value):
    arguments = {"api_cls": _unreachable_factory}
    if source == "kwargs":
        arguments["gateway_strategy"] = {"risk": value}
    else:
        arguments[source] = {"gateway_strategy": {"risk": value}}
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(**arguments)
    assert error.value.code == "risk_requires_gateway"


@pytest.mark.parametrize("source", ["config", "api_kwargs", "kwargs"])
@pytest.mark.parametrize("value", [None, "none", {"service": "risk"}])
def test_top_level_risk_remains_rejected(source, value):
    arguments = {"api_cls": _unreachable_factory}
    if source == "kwargs":
        arguments["risk"] = value
    else:
        arguments[source] = {"risk": value}
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(**arguments)
    assert error.value.code == "risk_requires_gateway"


@pytest.mark.parametrize("first, second", [
    ({"gateway": {"risk": None}}, {"gateway": {}}),
    ({"gateway": {}}, {"gateway": {"risk": None}}),
])
def test_each_unmerged_source_is_checked_even_if_the_other_overwrites_it(first, second):
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(config=first, api_kwargs=second, api_cls=_unreachable_factory)
    assert error.value.code == "risk_requires_gateway"
    assert first in ({"gateway": {"risk": None}}, {"gateway": {}})
    assert second in ({"gateway": {"risk": None}}, {"gateway": {}})


@pytest.mark.parametrize("source, section", [
    ("config", None), ("config", "gateway"),
    ("api_kwargs", None), ("api_kwargs", "gateway"),
    ("api_kwargs", "gateway_strategy"), ("kwargs", None),
    ("kwargs", "gateway"), ("kwargs", "gateway_strategy"),
])
def test_gateway_mode_rejects_risk_outside_selected_gateway_strategy(source, section):
    arguments = {"config": {"gateway_strategy": {"risk": "none"}}}
    misplaced = {"risk": None} if section is None else {section: {"risk": None}}
    if source == "config":
        arguments["config"].update(misplaced)
    elif source == "kwargs":
        arguments.update(misplaced)
    else:
        arguments[source] = misplaced
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(**arguments)
    assert error.value.code == "risk_selection_invalid"


class UnreadableMapping(Mapping):
    def __getitem__(self, _key):
        raise RuntimeError("private details must not escape")

    def __iter__(self):
        raise RuntimeError("private details must not escape")

    def __len__(self):
        return 1


@pytest.mark.parametrize("arguments", [
    {"config": UnreadableMapping()},
    {"api_kwargs": {"gateway": UnreadableMapping()}},
    {"gateway_strategy": UnreadableMapping()},
])
def test_unreadable_risk_location_fails_with_finite_error(arguments):
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(api_cls=_unreachable_factory, **arguments)
    assert str(error.value) == "risk_selection_invalid"
    assert error.value.code == "risk_selection_invalid"


class LazyMapping(Mapping):
    """Membership disagrees with the values yielded when copied."""

    def __init__(self, values):
        self.values = values

    def __contains__(self, _key):
        return False

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)

    def __getitem__(self, key):
        return self.values[key]


@pytest.mark.parametrize("source, section", [
    ("config", "gateway"), ("api_kwargs", "gateway"),
    ("api_kwargs", "gateway_strategy"), ("kwargs", "gateway"),
    ("kwargs", "gateway_strategy"),
])
def test_lazy_nested_mapping_is_checked_from_snapshot_before_overwrite(source, section):
    nested = LazyMapping({"risk": None})
    arguments = {"config": {"gateway": {}}, "api_kwargs": {"gateway": {}}}
    if source == "kwargs":
        arguments[section] = nested
    else:
        arguments[source][section] = nested
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(api_cls=_unreachable_factory, **arguments)
    assert error.value.code == "risk_requires_gateway"
    assert nested.values == {"risk": None}


@pytest.mark.parametrize("source", ["config", "api_kwargs"])
def test_lazy_top_level_mapping_is_checked_before_overwrite(source):
    original = LazyMapping({"gateway": {"risk": None}})
    arguments = {"config": {"gateway": {}}, "api_kwargs": {"gateway": {}}}
    arguments[source] = original
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(api_cls=_unreachable_factory, **arguments)
    assert error.value.code == "risk_requires_gateway"
    assert original.values == {"gateway": {"risk": None}}


class CopyFailureMapping(Mapping):
    def __contains__(self, _key):
        return False

    def __iter__(self):
        raise RuntimeError("private details must not escape")

    def __len__(self):
        return 1

    def __getitem__(self, _key):
        raise KeyError(_key)


@pytest.mark.parametrize("arguments", [
    {"config": CopyFailureMapping()},
    {"api_kwargs": CopyFailureMapping()},
    {"config": {"gateway": CopyFailureMapping()}},
    {"api_kwargs": {"gateway_strategy": CopyFailureMapping()}},
    {"gateway": CopyFailureMapping()},
])
def test_copy_failures_have_finite_error_and_never_expose_details(arguments):
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(api_cls=_unreachable_factory, **arguments)
    assert str(error.value) == error.value.code == "risk_selection_invalid"
    assert error.value.__suppress_context__


def test_consumed_configuration_uses_the_same_snapshots(monkeypatch):
    class ChangingSection(LazyMapping):
        def __init__(self):
            super().__init__({"marker": "first"})
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return iter(("marker",) if self.iterations == 1 else ("risk",))

        def __getitem__(self, key):
            return "first" if key == "marker" else None

    class ChangesAfterFirstRead(LazyMapping):
        def __init__(self, values):
            super().__init__(values)
            self.reads = 0

        def __getitem__(self, key):
            self.reads += 1
            if self.reads > 1:
                return {"risk": None}
            return self.values[key]

    section = ChangingSection()
    original = ChangesAfterFirstRead({"gateway": section})
    second = {"gateway": {"marker": "second"}}

    class CapturePolicy:
        def __init__(self, store, **_kwargs):
            self.store = store

        def write_route_names(self, *_args, **_kwargs):
            assert self.store._config == {"gateway": {"marker": "first"}}
            assert self.store._api_kwargs == {"gateway": {"marker": "second"}}
            raise ReachedConfiguration()

    monkeypatch.setattr(store_module, "StoreRouteIdentityPolicy", CapturePolicy)
    with pytest.raises(ReachedConfiguration):
        BtApiStore(config=original, api_kwargs=second, api_cls=_unreachable_factory)
    assert original.reads == 1
    assert original.values == {"gateway": section}
    assert section.values == {"marker": "first"}
    assert section.iterations == 1
    assert second == {"gateway": {"marker": "second"}}


def test_no_risk_reaches_next_store_step_without_constructing_api(monkeypatch):
    def stop_before_lifecycle(*_args, **_kwargs):
        raise ReachedConfiguration()

    monkeypatch.setattr(store_module, "StoreRouteIdentityPolicy", stop_before_lifecycle)
    config = {"gateway": {}, "exchange_kwargs": {"CTP___FUTURE": {}}}
    options = {"gateway": {}, "debug": False}
    with pytest.raises(ReachedConfiguration):
        BtApiStore(config=config, api_kwargs=options, api_cls=_unreachable_factory)
    assert config == {"gateway": {}, "exchange_kwargs": {"CTP___FUTURE": {}}}
    assert options == {"gateway": {}, "debug": False}


@pytest.mark.parametrize("value", [None, "none", {"service": "risk"}])
@pytest.mark.parametrize("lazy", [False, True])
def test_selected_gateway_risk_reaches_gateway_parser(monkeypatch, value, lazy):
    import bt_api_py.gateway_strategy_config as gateway_config
    from backtrader.live_state.gateway_pending import GatewayPendingHost

    selected = LazyMapping({"risk": value}) if lazy else {"risk": value}
    seen = []

    def parse(value):
        seen.append(value)
        raise ReachedConfiguration()

    monkeypatch.setattr(gateway_config, "parse_gateway_strategy_config", parse)
    host = object.__new__(GatewayPendingHost)
    with pytest.raises(ReachedConfiguration):
        BtApiStore(config={"gateway_strategy": selected}, gateway_host=host,
                   gateway_security_profiles={"synthetic": object()})
    assert seen == [{"risk": value}]
    if lazy:
        assert selected.values == {"risk": value}
