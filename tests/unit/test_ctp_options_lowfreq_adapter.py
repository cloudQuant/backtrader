"""Pure mock contracts for the Iteration 23 SimNow adapter."""

from __future__ import annotations

import copy
import importlib

import pytest


class MockSimNowApi:
    iter23_pure_mock = True

    def __init__(self, *, positions=None, orders=None, unknown=None, generations=(1, 1, 1)):
        self.positions = list(positions or [])
        self.orders = list(orders or [])
        self.unknown = list(unknown or [])
        self.generations = iter(generations)

    def _account(self):
        return {
            "account_fingerprint": "acct_mock_23",
            "trading_day": "20260911",
            "generation": next(self.generations),
        }

    def query_account(self):
        return self._account()

    def query_positions(self):
        return self.positions

    def query_orders(self):
        return self.orders

    def query_unknown_intents(self):
        return self.unknown


@pytest.fixture(scope="module")
def runner():
    return importlib.import_module("examples.014_1_ctp_options_lowfreq.run")


def _simnow_config(runner):
    config = copy.deepcopy(runner.load_config())
    config["mode"] = "simnow"
    return config


def test_engineering_smoke_builds_one_read_only_runtime_chain(runner):
    report = runner.run_simnow_engineering_smoke(_simnow_config(runner), api=MockSimNowApi())

    assert report["status"] == "ENGINEERING_SMOKE_PASS"
    assert report["runtime_chain"] == {
        "store": "BtApiStore",
        "store_provider": "btapi",
        "feeds": ["BtApiFeed", "BtApiFeed", "BtApiFeed"],
        "broker": "BtApiBroker",
        "broker_provider": "btapi",
        "cerebro": "Cerebro",
        "strategy": "CtpOptionsLowfreqStrategy",
    }
    assert report["preflight"]["scope"] == "account_wide"
    assert report["reconciliation"]["rounds"] == 2
    assert report["fill_claim_status"] == "NO_NATIVE_CONFIRMATION"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


def test_missing_api_is_blocked_without_constructing_a_client(runner):
    report = runner.run_simnow_engineering_smoke(_simnow_config(runner))
    assert report["status"] == "BLOCKED"
    assert report["reason"] == "SIMNOW_API_INJECTION_REQUIRED"
    assert report["external_request_counts"] == {"network": 0, "order_write": 0}


@pytest.mark.parametrize(
    "field",
    ("positions", "orders", "unknown"),
)
def test_startup_account_scope_blocks_existing_or_unknown_state(runner, field):
    values = {"positions": [], "orders": [], "unknown": []}
    values[field] = [{"symbol": "CZCE.SA701", "status": "UNKNOWN"}]
    report = runner.run_simnow_engineering_smoke(
        _simnow_config(runner), api=MockSimNowApi(**values)
    )
    assert report["status"] == "BLOCKED"
    assert report["reason"] == "STARTUP_ACCOUNT_NOT_FLAT_OR_UNKNOWN"


def test_two_round_reconciliation_rejects_generation_change(runner):
    adapter_module = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.simnow_adapter"
    )
    adapter = adapter_module.SimNowOptionsAdapter(_simnow_config(runner), MockSimNowApi(generations=(1, 1, 2)))
    adapter.startup_preflight()
    with pytest.raises(adapter_module.SimNowBlocked, match="RECONCILIATION_GENERATION_CHANGED"):
        adapter.reconcile()


def test_native_mode_uses_public_store_snapshot_interfaces(runner, monkeypatch):
    store_module = importlib.import_module("backtrader.stores.btapistore")
    calls = []
    bundle = {
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "complete": True,
        "account_fingerprint": "acct_native_mock",
        "trading_day": "20260911",
        "connection_generation": 7,
        "nonzero_positions": [],
        "active_orders": [],
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
    }

    def bundle_snapshot(self, legs, **kwargs):
        calls.append(("bundle", tuple(legs), kwargs["read_only"]))
        return dict(bundle)

    def reconciliation_snapshot(self, **kwargs):
        calls.append(("reconciliation", kwargs))
        return dict(bundle)

    monkeypatch.setattr(store_module.BtApiStore, "get_ctp_bundle_preflight_snapshot", bundle_snapshot)
    monkeypatch.setattr(store_module.BtApiStore, "get_ctp_reconciliation_snapshot", reconciliation_snapshot)
    api = object()
    adapter = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.simnow_adapter"
    ).SimNowOptionsAdapter(_simnow_config(runner), api)

    adapter.startup_preflight()
    result = adapter.reconcile()
    assert result.status == "FLAT_VERIFIED"
    assert calls[0][0] == "bundle"
    assert calls[0][2] is True
    assert [item[0] for item in calls[1:]] == ["reconciliation", "reconciliation"]


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        ({"active_order_count": 1, "flat": False}, "NONFLAT_OR_UNKNOWN"),
        ({"unknown_intent_count": 1, "flat": False}, "NONFLAT_OR_UNKNOWN"),
        ({"read_only_safe": False}, "NOT_READ_ONLY_COMPLETE_OR_FLAT"),
        ({"write_request_free": False}, "NOT_READ_ONLY_COMPLETE_OR_FLAT"),
        ({"unmatched_trade_count": 1, "flat": False}, "NONFLAT_OR_UNKNOWN"),
        ({"evidence_complete": False}, "NOT_READ_ONLY_COMPLETE_OR_FLAT"),
        ({"active_order_count": None}, "SCHEMA_INCOMPLETE"),
    ),
)
def test_native_store_schema_rejects_nonflat_unknown_or_incomplete(
    runner, monkeypatch, change, reason
):
    store_module = importlib.import_module("backtrader.stores.btapistore")
    base = {
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "account_fingerprint": "acct_native_mock",
        "trading_day": "20260911",
        "connection_generation": 7,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "nonzero_positions": [],
        "active_orders": [],
    }
    if "active_order_count" in change and change["active_order_count"] is None:
        base.pop("active_order_count")
    else:
        base.update(change)

    monkeypatch.setattr(
        store_module.BtApiStore,
        "get_ctp_bundle_preflight_snapshot",
        lambda self, legs, **kwargs: dict(base),
    )
    adapter = importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.simnow_adapter"
    ).SimNowOptionsAdapter(_simnow_config(runner), object())
    with pytest.raises(importlib.import_module(
        "examples.014_1_ctp_options_lowfreq.simnow_adapter"
    ).SimNowBlocked, match=reason):
        adapter.startup_preflight()
