"""Focused invariants for version-2 managed-paper recovery consumption."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest

from backtrader.stores.service_execution_recovery import (
    ServiceExecutionRecoveryError,
    ServiceExecutionRecoveryJournal,
    ServiceExecutionRecoveryNamespace,
)
from backtrader.stores.service_execution_adapter import ServiceExecutionAdapter
from backtrader.order import Order as BtOrder


_ACCOUNT = "account-v2"
_STRATEGY = "strategy-v2"
_RUN = "run-v2"
_ACCOUNT_KEY = "canonical-account-v2"
_SCOPE_KEY = "durable-scope-v2"
_GENERATION = "0123456789abcdef0123456789abcdef"
_DIRECTORY = "directory-v2"
_INTENT = "intent-v2"
_TOKEN = "single-consumer-token-v2"


def _namespace() -> ServiceExecutionRecoveryNamespace:
    return ServiceExecutionRecoveryNamespace(_ACCOUNT, _STRATEGY, _RUN)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload() -> dict[str, Any]:
    return {
        "intent_id": _INTENT,
        "signal_id": "signal-v2",
        "instrument": "BTC-USDT",
        "side": "BUY",
        "position_effect": "OPEN",
        "order_type": "MARKET",
        "quantity": "1.0",
        "price": None,
        "time_in_force": "FOK",
        "reduce_only": False,
        "metadata_version": "metadata-v1",
        "deadline_ns": None,
        "tags": {"framework_order_ref": "stable-order-v2"},
    }


def _execution_context() -> dict[str, Any]:
    return {
        "feed": {
            "data_name": "BTC-USD-feed",
            "instrument": "BTC-USDT",
            "feed_class": "backtrader.feeds.synthetic.PandasData",
            "feed_name": "paper-feed",
            "dataname": None,
            "timeframe": 4,
            "compression": 1,
            "timezone": None,
        },
        "decision": {"bar_index": 3, "datetime_hex": float(1.0).hex()},
        "comminfo": {
            "class_module": "backtrader.comminfo",
            "class_name": "CommInfoBase",
            "params": {
                "commission": "0.0",
                "mult": "1.0",
                "margin": None,
                "commtype": 0,
                "stocklike": True,
                "percabs": True,
                "interest": "0.0",
                "interest_long": False,
                "leverage": "1.0",
                "automargin": False,
            },
        },
        "quote_binding": {
            "source_ref": "paper-quotes-v1",
            "generation": "quote-generation-v1",
            "cursor": 1,
            "instrument": "BTC-USDT",
            "as_of_ns": 1_700_000_000_000_000_000,
            "data_name": "BTC-USD-feed",
            "bar_index": 3,
            "datetime_hex": float(1.0).hex(),
        },
    }


def _event_context() -> dict[str, Any]:
    context = _execution_context()
    return {
        "data_name": context["feed"]["data_name"],
        "instrument": context["feed"]["instrument"],
        "bar_index": context["decision"]["bar_index"],
        "datetime_hex": context["decision"]["datetime_hex"],
        "comminfo": context["comminfo"],
        "commission_currency": "USDT",
        "quote_source_ref": "paper-quotes-v1",
        "quote_generation": "quote-generation-v1",
        "quote_cursor": 1,
        "quote_instrument": "BTC-USDT",
        "quote_as_of_ns": context["quote_binding"]["as_of_ns"],
    }


def _snapshot() -> dict[str, Any]:
    return {
        "view": "RECOVERY_SNAPSHOT",
        "version": 1,
        "coverage": {
            "account_key": _ACCOUNT_KEY,
            "owner_kind": "STRATEGY",
            "owner_ref": _STRATEGY,
            "scope_directory_revision": _DIRECTORY,
            "journal_generation": _GENERATION,
            "first_sequence": None,
            "last_sequence": None,
            "high_water_sequence": 0,
            "complete": True,
            "source": "EXECUTION_SQLITE_JOURNAL",
            "freshness": "DURABLE_CUT_NOT_PROVIDER_LIVE",
            "scope_semantics": "DURABLE_STRATEGY_SCOPE_NO_RUN_ISOLATION",
        },
        "orders": [],
    }


def _owner_book() -> dict[str, Any]:
    return {
        "account_key": _ACCOUNT_KEY,
        "account_ref": _ACCOUNT,
        "strategy_ref": _STRATEGY,
        "scope_directory_revision": _DIRECTORY,
        "journal_generation": _GENERATION,
        "baseline_execution_cursor": 0,
        "current_execution_cursor": 0,
        "positions": {},
        "cash_by_currency": {"USDT": "1000.0"},
        "position_costs": {},
        "financial_available": True,
        "cost_basis_complete": True,
    }


def _idle_page(version: int) -> dict[str, Any]:
    return {
        "view": "EVENTS_AFTER",
        "version": version,
        "coverage": {
            "account_key": _ACCOUNT_KEY,
            "owner_kind": "STRATEGY",
            "owner_ref": _STRATEGY,
            "scope_directory_revision": _DIRECTORY,
            "journal_generation": _GENERATION,
            "first_sequence": None,
            "last_sequence": None,
            "high_water_sequence": 0,
            "source": "EXECUTION_SQLITE_JOURNAL",
            "freshness": "DURABLE_CUT_NOT_PROVIDER_LIVE",
            "after_sequence": 0,
            "scanned_through": 0,
            "has_more": False,
            "complete": True,
            "scope_semantics": "DURABLE_STRATEGY_SCOPE_NO_RUN_ISOLATION",
        },
        "events": [],
    }


def _paper_fill(*, event_sequence: int = 2) -> dict[str, Any]:
    return {
        "schema": "managed_paper_fill.v2",
        "time_source": "MANAGED_PAPER_MATCH",
        "fill_id": f"paper:{_GENERATION}:{'b' * 32}",
        "match_time_ns": 1_800_000_000_000_000_000,
        "quantity": "1.0",
        "price": "100.0",
        "commission": "0.01",
        "commission_currency": "USDT",
        "commission_model_id": "quote_notional_rate",
        "commission_model_version": "1",
        "event_id": "b" * 32,
        "event_sequence": event_sequence,
        "journal_generation": _GENERATION,
        "scope_key": _SCOPE_KEY,
        "intent_id": _INTENT,
        "intent_fingerprint": _sha("server-intent-v2"),
        "account_ref": _ACCOUNT,
        "strategy_ref": _STRATEGY,
        "quote_source_ref": "paper-quotes-v1",
        "quote_generation": "quote-generation-v1",
        "quote_cursor": 1,
        "quote_instrument": "BTC-USDT",
        "receipt_sha256": "d" * 64,
    }


def _page(submit_fingerprint: str) -> dict[str, Any]:
    recorded_event = {
        "scope_key": _SCOPE_KEY,
        "intent_id": _INTENT,
        "intent_fingerprint": _sha("server-intent-v2"),
        "submit_fingerprint": submit_fingerprint,
        "event_id": "a" * 32,
        "sequence": 1,
        "journal_generation": _GENERATION,
        "event_type": "intent_recorded",
        "state": "PENDING_ADMISSION",
        "event_sha256": "e" * 64,
        "details": {},
    }
    event = {
        "scope_key": _SCOPE_KEY,
        "intent_id": _INTENT,
        "intent_fingerprint": _sha("server-intent-v2"),
        "submit_fingerprint": submit_fingerprint,
        "event_id": "b" * 32,
        "sequence": 2,
        "journal_generation": _GENERATION,
        "event_type": "provider_observation",
        "state": "FILLED",
        "event_sha256": "c" * 64,
        "details": {
            "provider_order_id": "paper-order-v2",
            "filled_quantity": "1.0",
            "average_price": "100.0",
            "cumulative_commission": "0.01",
            "cumulative_commission_currency": "USDT",
            "reason_code": None,
            "source": "provider",
            "paper_fill_v2": _paper_fill(event_sequence=2),
        },
    }
    return {
        "view": "EVENTS_AFTER",
        "version": 2,
        "coverage": {
            "account_key": _ACCOUNT_KEY,
            "owner_kind": "STRATEGY",
            "owner_ref": _STRATEGY,
            "scope_directory_revision": _DIRECTORY,
            "journal_generation": _GENERATION,
            "first_sequence": 1,
            "last_sequence": 2,
            "high_water_sequence": 2,
            "source": "EXECUTION_SQLITE_JOURNAL",
            "freshness": "DURABLE_CUT_NOT_PROVIDER_LIVE",
            "after_sequence": 0,
            "scanned_through": 2,
            "has_more": False,
            "complete": True,
            "scope_semantics": "DURABLE_STRATEGY_SCOPE_NO_RUN_ISOLATION",
        },
        "events": [recorded_event, event],
    }


def _prepared_v2_journal(path) -> tuple[ServiceExecutionRecoveryJournal, str]:
    journal = ServiceExecutionRecoveryJournal(path)
    namespace = _namespace()
    journal.bind_event_version(namespace, 2)
    journal.acquire_consumer_lease(namespace, _TOKEN)
    journal.install_recovery_baseline(
        namespace, _snapshot(), _owner_book(), owner_token=_TOKEN
    )
    journal.install_strategy_genesis(
        namespace,
        {
            "baseline_cursor": 0,
            "journal_generation": _GENERATION,
            "scope_directory_revision": _DIRECTORY,
            "trade_ledger_empty": True,
        },
        owner_token=_TOKEN,
    )
    fingerprint = journal.prepare_intent(
        namespace,
        intent_id=_INTENT,
        submit_payload=_payload(),
        recovery_binding={"data_name": "BTC-USD-feed", "tradeid": 0},
        execution_context=_execution_context(),
        owner_token=_TOKEN,
    )
    return journal, fingerprint


def test_v2_protocol_can_be_pinned_before_first_authenticated_baseline(tmp_path) -> None:
    journal = ServiceExecutionRecoveryJournal(tmp_path / "v2-first-run.sqlite3")
    journal.bind_event_version(_namespace(), 2)

    assert journal.event_version(_namespace()) == 2
    assert journal.recovery_baseline(_namespace()) is None
    journal.close()


@pytest.mark.parametrize("version", [1, 2])
def test_adapter_preserves_v1_request_shape_and_explicitly_requests_v2(
    tmp_path, version: int
) -> None:
    class QueryClient:
        def __init__(self):
            self.page_requests = []

        def submit(self, **_kwargs):
            raise AssertionError("idle recovery must not submit")

        def cancel(self, **_kwargs):
            raise AssertionError("idle recovery must not cancel")

        def query_recovery_snapshot(self):
            return _snapshot()

        def query_recovery_events_after(self, **kwargs):
            self.page_requests.append(dict(kwargs))
            return _idle_page(version)

    namespace = _namespace()
    journal = ServiceExecutionRecoveryJournal(tmp_path / f"adapter-v{version}.sqlite3")
    client = QueryClient()
    if version == 1:
        adapter = ServiceExecutionAdapter(client, recovery_journal=journal)
        adapter.bind_recovery_namespace(namespace)
        adapter.initialize_recovery()
    else:
        adapter = ServiceExecutionAdapter(
            client,
            recovery_journal=journal,
            require_recovery_baseline=True,
            recovery_event_version=2,
        )
        adapter.bind_recovery_namespace(namespace)
        adapter.acquire_recovery_consumer_lease(_TOKEN)
        adapter.initialize_recovery(owner_book_reader=_owner_book)

    assert len(client.page_requests) == 1
    if version == 1:
        assert "version" not in client.page_requests[0]
        assert journal.recovery_baseline(namespace) is None
    else:
        assert client.page_requests[0]["version"] == 2
        assert journal.recovery_baseline(namespace) is not None
        adapter.release_recovery_consumer_lease(_TOKEN)
    journal.close()


def _adapter_order(exectype: int) -> SimpleNamespace:
    return SimpleNamespace(
        info={
            "managed_intent_id": "adapter-intent-v2",
            "managed_signal_id": "adapter-signal-v2",
            "managed_instrument": "BTC-USDT",
            "managed_position_effect": "OPEN",
            "managed_metadata_version": "metadata-v1",
        },
        exectype=exectype,
        created=SimpleNamespace(size=1.0, price=100.0),
        data=SimpleNamespace(_name="BTC-USD-feed"),
        owner=SimpleNamespace(
            p=SimpleNamespace(account_ref=_ACCOUNT, strategy_ref=_STRATEGY)
        ),
        tradeid=0,
        isbuy=lambda: True,
    )


class _SubmitClient:
    def __init__(self):
        self.submit_calls = []

    def submit(self, **kwargs):
        self.submit_calls.append(dict(kwargs))
        return SimpleNamespace(state="ACKED")

    def cancel(self, **_kwargs):
        raise AssertionError("submission must not cancel")

    def query_recovery_snapshot(self):
        return _snapshot()

    def query_recovery_events_after(self, **_kwargs):
        return _idle_page(2)


def test_adapter_v2_submits_market_fok_and_rejects_limit_before_manifest(tmp_path) -> None:
    client = _SubmitClient()
    journal = ServiceExecutionRecoveryJournal(tmp_path / "adapter-v2-market-fok.sqlite3")
    adapter = ServiceExecutionAdapter(
        client,
        recovery_journal=journal,
        require_recovery_baseline=True,
        recovery_event_version=2,
    )
    namespace = _namespace()
    adapter.bind_recovery_namespace(namespace)
    adapter.acquire_recovery_consumer_lease(_TOKEN)
    adapter.initialize_recovery(owner_book_reader=_owner_book)
    adapter.ensure_strategy_genesis(trade_ledger_empty=True)
    adapter.configure_recovery_intent_context_resolver(lambda _order: _execution_context())

    accepted = adapter.submit_order(_adapter_order(BtOrder.Market), legacy_dispatch=None)
    assert accepted["service_execution_recovery_required"] is True
    assert len(client.submit_calls) == 1
    assert client.submit_calls[0]["order_type"] == "MARKET"
    assert client.submit_calls[0]["price"] is None
    assert client.submit_calls[0]["time_in_force"] == "FOK"
    manifest = journal.intent_manifest(namespace, "adapter-intent-v2")
    assert manifest is not None
    assert manifest["submit_payload"]["order_type"] == "MARKET"
    assert manifest["submit_payload"]["time_in_force"] == "FOK"

    rejected_order = _adapter_order(BtOrder.Limit)
    rejected_order.info["managed_intent_id"] = "adapter-limit-v2"
    rejected_order.info["managed_signal_id"] = "adapter-limit-signal-v2"
    rejected = adapter.submit_order(rejected_order, legacy_dispatch=None)
    assert rejected["status"] == "rejected"
    assert rejected["error_code"] == "service_execution_recovery_v2_requires_market_order"
    assert len(client.submit_calls) == 1
    assert journal.intent_manifest(namespace, "adapter-limit-v2") is None

    adapter.release_recovery_consumer_lease(_TOKEN)
    journal.close()


def test_adapter_without_recovery_keeps_market_gtc_behavior() -> None:
    client = _SubmitClient()
    adapter = ServiceExecutionAdapter(client)

    projection = adapter.submit_order(_adapter_order(BtOrder.Market), legacy_dispatch=None)

    assert projection["status"] == "accepted"
    assert len(client.submit_calls) == 1
    assert client.submit_calls[0]["order_type"] == "MARKET"
    assert client.submit_calls[0]["time_in_force"] == "GTC"


def test_v2_fill_page_persists_validated_feed_context_before_cursor_advance(tmp_path) -> None:
    journal, fingerprint = _prepared_v2_journal(tmp_path / "v2-fill.sqlite3")
    namespace = _namespace()

    def resolve_context(received_namespace, event, manifest, execution_context):
        assert received_namespace == namespace
        assert event["sequence"] == 2
        assert event["details"]["paper_fill_v2"]["fill_id"] == _paper_fill()["fill_id"]
        assert manifest["submit_fingerprint"] == fingerprint
        assert execution_context == _execution_context()
        return _event_context()

    assert journal.apply_events_page(
        namespace,
        _page(fingerprint),
        event_context_resolver=resolve_context,
        owner_token=_TOKEN,
    ) is True
    assert journal.cursor(namespace)["event_cursor"] == 2
    receipts = journal.claim_pending_callbacks(namespace, owner_token=_TOKEN)
    assert len(receipts) == 1
    assert receipts[0].sequence == 2
    projection = journal.recovery_fill_projection(namespace, receipts[0].receipt_id)
    assert projection is not None
    assert projection["status"] == "READY_TO_PROJECT"
    assert projection["fill"] == _paper_fill()
    assert projection["event_context"] == _event_context()
    assert projection["intent_context"] == _execution_context()
    assert projection["trade_state"] is None
    baseline = journal.recovery_baseline(namespace)
    assert baseline is not None
    assert journal._trade_projection_events_complete(namespace, baseline) is True
    journal.close()


def test_v2_fill_without_context_mapper_is_durable_but_explicitly_unavailable(tmp_path) -> None:
    journal, fingerprint = _prepared_v2_journal(tmp_path / "v2-unavailable.sqlite3")
    namespace = _namespace()

    with pytest.raises(
        ServiceExecutionRecoveryError,
        match="RECOVERY_CONSUMER_LEASE_LOST",
    ):
        journal.apply_events_page(namespace, _page(fingerprint), owner_token="other-token")
    assert journal.cursor(namespace)["event_cursor"] == 0
    assert journal.claim_pending_callbacks(namespace, owner_token=_TOKEN) == ()

    assert journal.apply_events_page(
        namespace, _page(fingerprint), owner_token=_TOKEN
    ) is True
    receipt = journal.claim_pending_callbacks(namespace, owner_token=_TOKEN)[0]
    projection = journal.recovery_fill_projection(namespace, receipt.receipt_id)
    assert journal.cursor(namespace)["event_cursor"] == 2
    assert projection is not None
    assert projection["status"] == "REPLAY_UNAVAILABLE"
    assert projection["reason"] == "recovery_event_context_resolver_unavailable"
    baseline = journal.recovery_baseline(namespace)
    assert baseline is not None
    assert journal._trade_projection_events_complete(namespace, baseline) is False
    journal.close()


def test_v2_fill_with_unsupported_fee_model_is_not_trade_projectable(tmp_path) -> None:
    journal, fingerprint = _prepared_v2_journal(tmp_path / "v2-fee-model.sqlite3")
    namespace = _namespace()
    page = _page(fingerprint)
    page["events"][1]["details"]["paper_fill_v2"]["commission_model_id"] = (
        "caller-selected-rate"
    )

    with pytest.raises(
        ServiceExecutionRecoveryError,
        match="UNSUPPORTED_RECOVERY_PAPER_FEE_MODEL",
    ):
        journal.apply_events_page(
            namespace,
            page,
            event_context_resolver=lambda *_args: _event_context(),
            owner_token=_TOKEN,
        )
    assert journal.cursor(namespace)["event_cursor"] == 0
    assert journal.ordered_event_history(namespace) == ()
    assert journal.claim_pending_callbacks(namespace, owner_token=_TOKEN) == ()
    journal.close()


def test_v2_context_mismatch_rolls_back_page_and_pending_callback(tmp_path) -> None:
    journal, fingerprint = _prepared_v2_journal(tmp_path / "v2-context-mismatch.sqlite3")
    namespace = _namespace()

    def wrong_quote_context(*_args):
        context = _event_context()
        context["quote_cursor"] += 1
        return context

    with pytest.raises(
        ServiceExecutionRecoveryError,
        match="RECOVERY_EVENT_CONTEXT_MISMATCH",
    ):
        journal.apply_events_page(
            namespace,
            _page(fingerprint),
            event_context_resolver=wrong_quote_context,
            owner_token=_TOKEN,
        )

    assert journal.cursor(namespace)["event_cursor"] == 0
    assert journal.ordered_event_history(namespace) == ()
    assert journal.claim_pending_callbacks(namespace, owner_token=_TOKEN) == ()
    journal.close()


def test_v2_paper_match_before_captured_quote_time_rolls_back_page(tmp_path) -> None:
    journal, fingerprint = _prepared_v2_journal(tmp_path / "v2-quote-time.sqlite3")
    namespace = _namespace()
    page = _page(fingerprint)
    page["events"][1]["details"]["paper_fill_v2"]["match_time_ns"] = 1_600_000_000_000_000_000

    with pytest.raises(
        ServiceExecutionRecoveryError,
        match="RECOVERY_EVENT_CONTEXT_MISMATCH",
    ):
        journal.apply_events_page(
            namespace,
            page,
            event_context_resolver=lambda *_args: _event_context(),
            owner_token=_TOKEN,
        )

    assert journal.cursor(namespace)["event_cursor"] == 0
    assert journal.ordered_event_history(namespace) == ()
    assert journal.claim_pending_callbacks(namespace, owner_token=_TOKEN) == ()
    journal.close()


def test_v2_intent_requires_ledger_empty_genesis_before_manifest(tmp_path) -> None:
    journal = ServiceExecutionRecoveryJournal(tmp_path / "v2-genesis-required.sqlite3")
    namespace = _namespace()
    journal.bind_event_version(namespace, 2)
    journal.acquire_consumer_lease(namespace, _TOKEN)
    journal.install_recovery_baseline(
        namespace, _snapshot(), _owner_book(), owner_token=_TOKEN
    )

    with pytest.raises(
        ServiceExecutionRecoveryError,
        match="RECOVERY_STRATEGY_GENESIS_REQUIRED",
    ):
        journal.prepare_intent(
            namespace,
            intent_id=_INTENT,
            submit_payload=_payload(),
            recovery_binding={"data_name": "BTC-USD-feed", "tradeid": 0},
            execution_context=_execution_context(),
            owner_token=_TOKEN,
        )

    assert journal.intent_manifest(namespace, _INTENT) is None
    journal.close()


def test_v2_existing_intent_reuses_immutable_context_and_rejects_mutation(tmp_path) -> None:
    path = tmp_path / "v2-context.sqlite3"
    journal, _ = _prepared_v2_journal(path)
    context = journal.intent_execution_context(_namespace(), _INTENT)
    assert context == _execution_context()
    journal.close()

    reopened = ServiceExecutionRecoveryJournal(path)
    assert reopened.intent_execution_context(_namespace(), _INTENT) == _execution_context()
    changed = _execution_context()
    changed["decision"]["bar_index"] = 4
    changed["quote_binding"]["bar_index"] = 4
    with pytest.raises(
        ServiceExecutionRecoveryError,
        match="INTENT_RECOVERY_CONTEXT_CONFLICT",
    ):
        reopened.prepare_intent(
            _namespace(),
            intent_id=_INTENT,
            submit_payload=_payload(),
            recovery_binding={"data_name": "BTC-USD-feed", "tradeid": 0},
            execution_context=changed,
            owner_token=_TOKEN,
        )
    reopened.close()
