"""Opt-in CTP native shutdown receipts through the production Store wrapper."""

from __future__ import annotations

import pytest

from tests.integration import test_ctp_factor_source_cohort as source_fixture
from tests.unit.test_alpha003_simnow_runner import RUNNER

from backtrader.stores.btapistore import BtApiStoreError
from backtrader.stores.registered_sim import RegisteredSimStore


def _store(monkeypatch, *, join_observer, enable_source=True):
    clients = source_fixture._install_fake_ctp_sdk(monkeypatch)
    kwargs = {
        "provider": "ctp",
        "backend": "direct",
        "preserve_raw_bars": True,
        "broker_id": "synthetic-broker",
        "user_id": "synthetic-user",
        "investor_id": "synthetic-user",
        "password": "synthetic-test-only",
        "md_front": "tcp://127.0.0.1:10001",
        "td_front": "tcp://127.0.0.1:10002",
        "auto_settlement_confirm": False,
        "execution_authorization_key_id": "synthetic-key-id",
        "execution_authorization_secret": "synthetic-secret",
    }
    if join_observer is not None:
        kwargs["ctp_join_observer"] = join_observer
    store = RegisteredSimStore(**kwargs)
    store.start()
    assert store.registered_sim_wait_ready(0) is True
    api = store._api
    api.trader_client.login_read_only("20261021")
    if enable_source:
        assert store.enable_ctp_factor_tick_source() == source_fixture._MD_GENERATION
    return store, clients


def _cleanup_rows(store_evidence):
    return [
        {"resource": "query_refresh", "joined": True},
        {
            "resource": "broker",
            "status": "PASS",
            "store_shutdown_state": store_evidence["shutdown_state"],
        },
        {"resource": "store", "status": "CLOSED_BY_BROKER", **store_evidence},
        {"resource": "journal", "status": "CLOSED"},
        {"resource": "decision_tape", "status": "CLOSED"},
    ]


def test_opted_in_wrapper_projects_complete_receipts_for_both_join_policies(monkeypatch):
    for join_observer in (False, True):
        store, clients = _store(monkeypatch, join_observer=join_observer)
        health = store.stop()

        assert health["shutdown_state"] == "PASS"
        source_health = health["ctp_factor_source_shutdown"]
        assert source_health["required"] is True
        assert source_health["status"] == "PASS"
        assert source_health["expected_md_generation"] == source_fixture._MD_GENERATION
        assert source_health["expected_trader_generation"] == source_fixture._TRADER_GENERATION
        assert source_health["join_required"] is join_observer
        assert source_health["reason_codes"] == ()
        for name, generation in (
            ("md", source_fixture._MD_GENERATION),
            ("trader", source_fixture._TRADER_GENERATION),
        ):
            client = clients[name][0]
            receipt = source_health[f"{name}_receipt"]
            assert client.stop_count == 1
            assert client.stop_wait_count == 1
            assert receipt["connection_generation"] == generation
            assert receipt["join_required"] is join_observer
            assert receipt["native_released"] is True
            assert receipt["thread_alive"] is False
            assert receipt["timed_out"] is False
            assert receipt["complete"] is True

        store_evidence = RUNNER._store_stop_evidence(health)
        assert store_evidence["ctp_factor_source_shutdown"]["status"] == "PASS"
        assert RUNNER._cleanup_complete(_cleanup_rows(store_evidence)) is True


def test_unfinished_release_receipt_keeps_store_and_runner_cleanup_incomplete(monkeypatch):
    store, clients = _store(monkeypatch, join_observer=False)
    clients["md"][0].stop_receipt_override = source_fixture._FakeCtpNativeStopReceipt(
        source_fixture._MD_GENERATION,
        native_released=False,
        thread_alive=True,
        timed_out=True,
    )

    health = store.stop()

    assert clients["md"][0].stop_count == clients["trader"][0].stop_count == 1
    assert clients["md"][0].stop_wait_count == clients["trader"][0].stop_wait_count == 1
    assert health["shutdown_state"] == "INCOMPLETE"
    store_evidence = RUNNER._store_stop_evidence(health)
    assert store_evidence["ctp_factor_source_shutdown"]["status"] == "INCOMPLETE"
    assert RUNNER._cleanup_complete(_cleanup_rows(store_evidence)) is False


def test_native_release_marker_with_pending_owner_receipt_is_not_complete(monkeypatch):
    store, clients = _store(monkeypatch, join_observer=False)
    clients["md"][0].stop_receipt_override = source_fixture._FakeCtpNativeStopReceipt(
        source_fixture._MD_GENERATION,
        native_released=True,
        thread_alive=False,
        timed_out=True,
    )

    health = store.stop()

    md_receipt = health["ctp_factor_source_shutdown"]["md_receipt"]
    assert md_receipt["native_released"] is True
    assert md_receipt["complete"] is False
    assert health["ctp_factor_source_shutdown"]["status"] == "INCOMPLETE"
    assert health["shutdown_state"] == "INCOMPLETE"
    store_evidence = RUNNER._store_stop_evidence(health)
    assert RUNNER._cleanup_complete(_cleanup_rows(store_evidence)) is False


def test_wrong_generation_receipt_is_rejected_and_both_clients_are_observed(monkeypatch):
    store, clients = _store(monkeypatch, join_observer=False)
    clients["trader"][0].stop_receipt_override = source_fixture._FakeCtpNativeStopReceipt(
        source_fixture._TRADER_GENERATION + 1
    )

    health = store.stop()

    assert clients["md"][0].stop_count == clients["trader"][0].stop_count == 1
    assert clients["md"][0].stop_wait_count == clients["trader"][0].stop_wait_count == 1
    assert health["ctp_factor_source_shutdown"]["status"] == "INCOMPLETE"
    assert "trader_generation_mismatch" in health["ctp_factor_source_shutdown"]["reason_codes"]
    assert health["shutdown_state"] == "INCOMPLETE"
    store_evidence = RUNNER._store_stop_evidence(health)
    assert RUNNER._cleanup_complete(_cleanup_rows(store_evidence)) is False


def test_receipt_join_policy_must_match_started_client_policy(monkeypatch):
    store, clients = _store(monkeypatch, join_observer=False)
    clients["trader"][0].stop_receipt_override = source_fixture._FakeCtpNativeStopReceipt(
        source_fixture._TRADER_GENERATION,
        join_required=True,
        join_completed=True,
    )

    health = store.stop()

    summary = health["ctp_factor_source_shutdown"]
    assert summary["join_required"] is False
    assert summary["status"] == "INCOMPLETE"
    assert "trader_join_policy_mismatch" in summary["reason_codes"]
    assert health["shutdown_state"] == "INCOMPLETE"


def test_missing_typed_receipt_fails_closed_without_repeating_stop(monkeypatch):
    store, clients = _store(monkeypatch, join_observer=False)
    clients["md"][0].stop_receipt_override = object()

    health = store.stop()

    assert clients["md"][0].stop_count == clients["trader"][0].stop_count == 1
    assert clients["md"][0].stop_wait_count == clients["trader"][0].stop_wait_count == 1
    assert health["shutdown_state"] == "INCOMPLETE"
    summary = health["ctp_factor_source_shutdown"]
    assert summary["md_receipt"] is None
    assert summary["status"] == "INCOMPLETE"
    assert "md_receipt_missing_or_untyped" in summary["reason_codes"]
    store_evidence = RUNNER._store_stop_evidence(health)
    assert RUNNER._cleanup_complete(_cleanup_rows(store_evidence)) is False


def test_runner_does_not_treat_missing_opted_in_receipt_projection_as_closed():
    store_evidence = RUNNER._store_stop_evidence(
        {"shutdown_state": "PASS"},
        ctp_factor_source_required=True,
    )

    assert store_evidence["ctp_factor_source_shutdown"] == {
        "required": True,
        "status": "UNPROVEN",
    }
    assert RUNNER._cleanup_complete(_cleanup_rows(store_evidence)) is False


def test_opted_in_wrapper_cannot_reconnect_or_reenable_after_shutdown_pass(monkeypatch):
    store, clients = _store(monkeypatch, join_observer=False)
    api = store._api
    health = store.stop()
    original_summary = health["ctp_factor_source_shutdown"]

    assert original_summary["status"] == "PASS"
    with pytest.raises(BtApiStoreError, match="CTP_FACTOR_SOURCE_TERMINAL"):
        api.connect()
    with pytest.raises(BtApiStoreError, match="CTP_FACTOR_SOURCE_TERMINAL"):
        api.enable_ctp_factor_tick_source()

    assert len(clients["md"]) == 1
    assert len(clients["trader"]) == 1
    assert clients["md"][0].stop_count == clients["trader"][0].stop_count == 1
    assert clients["md"][0].stop_wait_count == clients["trader"][0].stop_wait_count == 1
    assert api.get_ctp_factor_source_shutdown_health() == original_summary


@pytest.mark.parametrize("client_name", ("md", "trader"))
def test_same_generation_client_replacement_cannot_satisfy_bound_receipt(
    monkeypatch, client_name
):
    store, clients = _store(monkeypatch, join_observer=False)
    api = store._api
    original = getattr(api, f"{client_name}_client")
    replacement = type(original)()
    if client_name == "trader":
        replacement._connection_generation = original._connection_generation
    assert replacement is not original
    replacement_generation = (
        replacement.connection_generation
        if client_name == "md"
        else replacement._connection_generation
    )
    original_generation = (
        original.connection_generation
        if client_name == "md"
        else original._connection_generation
    )
    assert replacement_generation == original_generation
    setattr(api, f"{client_name}_client", replacement)

    health = store.stop()

    summary = health["ctp_factor_source_shutdown"]
    assert summary["status"] == "INCOMPLETE"
    assert f"{client_name}_client_identity_changed" in summary["reason_codes"]
    assert health["shutdown_state"] == "INCOMPLETE"
    original_row = summary[f"{client_name}_receipt"]
    expected_generation = (
        source_fixture._MD_GENERATION
        if client_name == "md"
        else source_fixture._TRADER_GENERATION
    )
    assert original_row["connection_generation"] == expected_generation
    assert original_row["complete"] is True
    assert original.stop_count == original.stop_wait_count == 1
    assert replacement.stop_count == replacement.stop_wait_count == 0
    assert any(
        retained is replacement for retained in api._ctp_factor_unowned_replacement_refs
    )


def test_default_join_non_opted_in_keeps_legacy_stop_path(monkeypatch):
    store, clients = _store(monkeypatch, join_observer=None, enable_source=False)

    health = store.stop()

    assert health["shutdown_state"] == "PASS"
    assert "ctp_factor_source_shutdown" not in health
    for name in ("md", "trader"):
        client = clients[name][0]
        assert client.start_calls == [(False, True)]
        assert client.stop_count == 1
        assert client.stop_wait_count == 0
