"""Store-owned contract metadata cache and probe-boundary helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")

import bt_api_py.bounded_metadata_probe as sdk_metadata_probe
import bt_api_py.instrument_metadata_aliases as sdk_metadata_aliases

from backtrader.stores import btapistore as store_module
from backtrader.stores._contract_metadata import (
    StoreContractMetadataCache,
    bounded_metadata_probe_shutdown_proven,
    configure_bounded_metadata_probe_sdk_market_data_only,
    verify_bounded_metadata_probe_sdk_market_data_only,
)
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError


def test_contract_metadata_cache_reads_live_mapping_and_dynamic_aliases():
    mapping = {
        "ES": {"nested": {"value": 1}},
        "ES.CONT": {"nested": {"value": 2}},
    }
    current_mapping = [mapping]
    alias_by_name = {"lookup": "ES"}
    alias_calls = []

    def aliases_for(name):
        alias_calls.append(name)
        return [alias_by_name[name]]

    cache = StoreContractMetadataCache(
        mapping_getter=lambda: current_mapping[0],
    )

    def lookup(name):
        aliases = aliases_for(name)
        metadata_for_lookup = current_mapping[0]
        alias_fn = aliases_for
        return cache.lookup(
            name,
            metadata=metadata_for_lookup,
            aliases=aliases,
            alias_fn=alias_fn,
            find_alias_match=sdk_metadata_aliases.find_alias_match,
        )

    found, first = lookup("lookup")
    assert found is True
    assert first == {"nested": {"value": 1}}
    assert first is not mapping["ES"]
    assert first["nested"] is mapping["ES"]["nested"]
    assert mapping["lookup"] == {"nested": {"value": 1}}

    alias_by_name["lookup"] = "ES.CONT"
    found, second = lookup("lookup")
    assert found is True
    assert second == {"nested": {"value": 2}}
    assert alias_calls == ["lookup", "lookup"]

    replacement = {"ES": {"nested": {"value": 3}}}
    current_mapping[0] = replacement
    alias_by_name["lookup"] = "ES"
    found, third = lookup("lookup")
    assert found is True
    assert third == {"nested": {"value": 3}}
    assert replacement["lookup"] == {"nested": {"value": 3}}


def test_contract_metadata_cache_preserves_shallow_snapshot_and_deep_store_copy():
    metadata = {"ES": {"nested": {"value": 1}}}
    cache = StoreContractMetadataCache(
        mapping_getter=lambda: metadata,
    )

    snapshot = cache.snapshot_all()
    assert snapshot == metadata
    assert snapshot is not metadata
    assert snapshot["ES"] is not metadata["ES"]
    assert snapshot["ES"]["nested"] is metadata["ES"]["nested"]

    normalized = {"nested": {"value": 2}}
    cache.store_normalized("ES", normalized)
    assert metadata["ES"] == normalized
    assert metadata["ES"] is not normalized
    assert metadata["ES"]["nested"] is not normalized["nested"]


def test_store_metadata_cache_observes_public_mapping_mutation_and_replacement():
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        contract_metadata={"ES": {"quantity_unit": "contracts"}},
        autostart=False,
    )
    store._sdk_mode = False

    original_mapping = store.contract_metadata
    assert store.get_contract_metadata("ES") == {"quantity_unit": "contracts"}
    assert store.contract_metadata is original_mapping

    store.contract_metadata["ES"]["quantity_unit"] = "lots"
    assert store.get_contract_metadata("ES")["quantity_unit"] == "lots"

    store.contract_metadata = {"ES": {"quantity_unit": "units"}}
    assert store.get_contract_metadata("ES")["quantity_unit"] == "units"
    snapshot = store.get_contract_metadata()
    assert snapshot == {"ES": {"quantity_unit": "units"}}
    assert snapshot is not store.contract_metadata
    assert snapshot["ES"] is not store.contract_metadata["ES"]


def test_store_cache_uses_alias_policy_replaced_after_construction(monkeypatch):
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        contract_metadata={"configured": {"quantity_unit": "contracts"}},
        autostart=False,
    )
    store._sdk_mode = False
    alias_calls = []

    def aliases_for(symbol):
        alias_calls.append(symbol)
        return ["configured"]

    monkeypatch.setattr(store_module, "_contract_metadata_aliases", aliases_for)

    assert store.get_contract_metadata("ES") == {"quantity_unit": "contracts"}
    assert alias_calls


def test_store_rechecks_public_mapping_after_reentrant_alias_matcher(monkeypatch):
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        contract_metadata={"ES": {"quantity_unit": "contracts"}},
        autostart=False,
    )
    store._sdk_mode = False
    original_mapping = store.contract_metadata
    replacement_mapping = {}
    monkeypatch.setattr(
        store_module,
        "_contract_metadata_aliases",
        lambda _symbol: ["ES"],
    )

    def replace_mapping_while_matching(mapping, aliases, *, alias_fn, require_truthy):
        assert mapping is original_mapping
        assert aliases == ["ES"]
        assert callable(alias_fn)
        assert require_truthy is True
        store.contract_metadata = replacement_mapping
        return True, mapping["ES"]

    monkeypatch.setattr(
        sdk_metadata_aliases,
        "find_alias_match",
        replace_mapping_while_matching,
    )

    result = store.get_contract_metadata("ES.CONT")

    assert result == {"quantity_unit": "contracts"}
    assert replacement_mapping == {
        "ES.CONT": {"quantity_unit": "contracts"}
    }
    assert original_mapping == {"ES": {"quantity_unit": "contracts"}}


def test_store_captures_alias_callback_before_reentrant_matcher(monkeypatch):
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        contract_metadata={"ES": {"quantity_unit": "contracts"}},
        autostart=False,
    )
    store._sdk_mode = False
    alias_calls = []

    def original_aliases(symbol):
        alias_calls.append(("original", symbol))
        return ["ES"]

    def replacement_aliases(symbol):
        alias_calls.append(("replacement", symbol))
        return ["replacement"]

    monkeypatch.setattr(store_module, "_contract_metadata_aliases", original_aliases)

    def replace_alias_policy_while_matching(mapping, aliases, *, alias_fn, require_truthy):
        assert mapping is store.contract_metadata
        assert aliases == ["ES"]
        assert alias_fn is original_aliases
        assert require_truthy is True
        monkeypatch.setattr(store_module, "_contract_metadata_aliases", replacement_aliases)
        assert alias_fn("during-match") == ["ES"]
        return True, mapping["ES"]

    monkeypatch.setattr(
        sdk_metadata_aliases,
        "find_alias_match",
        replace_alias_policy_while_matching,
    )

    result = store.get_contract_metadata("ES.CONT")

    assert result == {"quantity_unit": "contracts"}
    assert alias_calls == [("original", "ES.CONT"), ("original", "during-match")]
    assert store_module._contract_metadata_aliases is replacement_aliases


def test_store_instrument_spec_preserves_sdk_call_and_detaches_cache_and_result(
    monkeypatch,
):
    source = {"nested": {"values": [1]}}
    calls = []
    api = SimpleNamespace(
        get_instrument_spec=lambda exchange, symbol: (
            calls.append((exchange, symbol)) or source
        )
    )
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        autostart=False,
    )
    store._sdk_mode = True
    store._service_read_only = False
    store._ensure_api_ready = lambda: api
    store._sdk_exchange = lambda _symbol: "CTP___FUTURE"
    monkeypatch.setattr(store_module, "_contract_mapping", lambda value, _name: value)
    monkeypatch.setattr(
        sdk_metadata_aliases,
        "legacy_instrument_spec_fields",
        lambda _metadata: None,
    )

    result = store.get_instrument_spec("ES")

    assert calls == [("CTP___FUTURE", "ES")]
    assert store.contract_metadata["ES"] == {"nested": {"values": [1]}}
    assert store.contract_metadata["ES"] is not source
    assert store.contract_metadata["ES"]["nested"] is not source["nested"]
    assert result == store.contract_metadata["ES"]
    assert result is not store.contract_metadata["ES"]
    assert result["nested"] is not store.contract_metadata["ES"]["nested"]


def test_metadata_probe_shutdown_predicate_keeps_full_conservation_contract():
    healthy = {
        "shutdown_state": "PASS",
        "queue_depth": 0,
        "inflight": False,
        "worker_alive": False,
        "close_thread_alive": False,
        "broker_update_conservation": True,
        "last_error_code": None,
    }
    assert bounded_metadata_probe_shutdown_proven(healthy)
    assert not bounded_metadata_probe_shutdown_proven(
        {**healthy, "broker_update_conservation": False}
    )
    assert not bounded_metadata_probe_shutdown_proven(
        {**healthy, "queue_depth": 1}
    )


def test_metadata_probe_configuration_keeps_error_projection_and_verify_order():
    calls = []
    store = SimpleNamespace(
        _sdk_direct_api_assembly=SimpleNamespace(
            reapply_execution_config=lambda: calls.append("reapply")
        ),
        _verify_bounded_metadata_probe_sdk_market_data_only=lambda: calls.append(
            "verify"
        ),
    )

    configure_bounded_metadata_probe_sdk_market_data_only(
        store,
        error_type=BtApiStoreError,
        safe_log=lambda *_args: None,
    )
    assert calls == ["reapply", "verify"]

    sanitized = []
    logs = []
    store._sdk_direct_api_assembly = SimpleNamespace(
        reapply_execution_config=lambda: (_ for _ in ()).throw(ValueError("private"))
    )
    store.sanitize_exception = sanitized.append
    with pytest.raises(BtApiStoreError) as excinfo:
        configure_bounded_metadata_probe_sdk_market_data_only(
            store,
            error_type=BtApiStoreError,
            safe_log=lambda *args: logs.append(args),
        )
    assert str(excinfo.value) == (
        "bounded read-only metadata probe could not configure SDK market-data-only mode"
    )
    assert sanitized and isinstance(sanitized[0], ValueError)
    assert logs == [("error", "btapistore:4070 exception before re-raise (Exception)")]
    assert excinfo.value.__cause__ is None


def test_metadata_probe_summary_verification_uses_sdk_contract(monkeypatch):
    summary = {"market_data_only": True}
    observed = []
    api = SimpleNamespace(get_execution_summary=lambda: summary)
    store = SimpleNamespace(_api=api, sanitize_exception=lambda _exc: None)
    monkeypatch.setattr(
        sdk_metadata_probe,
        "is_market_data_only_execution_summary",
        lambda value: observed.append(value) or value is summary,
    )

    verify_bounded_metadata_probe_sdk_market_data_only(
        store,
        error_type=BtApiStoreError,
        missing_dependency_error_type=RuntimeError,
        safe_log=lambda *_args: None,
    )
    assert observed == [summary]

    store._api = SimpleNamespace(get_execution_summary=dict)
    with pytest.raises(BtApiStoreError) as excinfo:
        verify_bounded_metadata_probe_sdk_market_data_only(
            store,
            error_type=BtApiStoreError,
            missing_dependency_error_type=RuntimeError,
            safe_log=lambda *_args: None,
        )
    assert str(excinfo.value) == (
        "bounded read-only metadata probe cannot verify SDK market-data-only mode"
    )
