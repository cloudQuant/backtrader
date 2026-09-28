from decimal import Decimal
from types import SimpleNamespace

import pytest

from backtrader.stores import btapistore as store_module
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from backtrader.stores.ctp_account_actor_port import (
    ActorCommandContextV1,
    ActorCommandExpectationV2,
    ActorCommandReceiptV2,
    ActorCommandState,
    CtpAccountActorPort,
    CtpCancelIntentV2,
    CtpSubmitIntentV2,
    FakeLocalActorReplayLedger,
    RouteKind,
    classify_store_route,
)


class _AttributeTrap:
    def __init__(self):
        self.reads = []

    def __getattr__(self, name):
        self.reads.append(name)
        raise AssertionError(f"unexpected API attribute read: {name}")


class _SafeInjectedApi:
    exchange_kwargs = {}


class _ProjectionAdapter:
    def __init__(self):
        self.calls = []
        self.legacy_dispatch = None

    def submit_order(self, order, legacy_dispatch):
        self.calls.append(order)
        self.legacy_dispatch = legacy_dispatch
        return {"status": "accepted", "id": "managed.order"}


class _DispatchingAdapter:
    def __init__(self):
        self.calls = 0

    def submit_order(self, order, legacy_dispatch):
        self.calls += 1
        return legacy_dispatch(order)


class _CredentialTrap:
    def __str__(self):
        raise AssertionError("credential was converted before the route gate")

    def __bool__(self):
        raise AssertionError("credential was tested before the route gate")


class _QueuePort(CtpAccountActorPort):
    def __init__(self, *, corrupt=False):
        self.calls = []
        self.corrupt = corrupt

    def submit_order(self, intent):
        self.calls.append(("SUBMIT", intent.command_id))
        expected = ActorCommandExpectationV2.from_intent(intent)
        digest = "0" * 64 if self.corrupt else expected.command_digest
        return ActorCommandReceiptV2(
            "SUBMIT",
            intent.command_id,
            ActorCommandState.QUEUED,
            intent.context,
            digest,
        )

    def cancel_order(self, intent):
        self.calls.append(("CANCEL", intent.command_id))
        expected = ActorCommandExpectationV2.from_intent(intent)
        digest = "0" * 64 if self.corrupt else expected.command_digest
        return ActorCommandReceiptV2(
            "CANCEL",
            intent.command_id,
            ActorCommandState.QUEUED,
            intent.context,
            digest,
        )


def _context():
    # All fields are caller supplied in this offline test; none proves actor authority.
    return ActorCommandContextV1(
        account_ref="offline-account",
        runtime_id="offline-runtime",
        mode="simulation",
        config_digest="a" * 64,
        session_id="caller-chosen-session",
        front_id=17,
        native_session_id=23,
        session_generation=1,
        actor_epoch=999,
    )


def _submit(context, command_id="submit-1"):
    return CtpSubmitIntentV2(
        intent_id=command_id,
        instrument_id="rb2710",
        exchange_id="SHFE",
        side="BUY",
        offset="OPEN",
        hedge_flag="SPECULATION",
        quantity=1,
        limit_price=Decimal("3500.0"),
        context=context,
    )


def _cancel(context, command_id="cancel-1"):
    return CtpCancelIntentV2(
        cancel_intent_id=command_id,
        runtime_order_id="runtime-order-1",
        order_ref="local-ref-1",
        front_id=context.front_id,
        session_id=context.native_session_id,
        exchange_id="SHFE",
        order_sys_id="provider-order-1",
        context=context,
    )


def test_ctp_forwarding_env_rewrite_and_secret_traps_reject_before_any_local_boundary(
    monkeypatch,
):
    api = _AttributeTrap()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("preconstruction gate ran too late")

    monkeypatch.setattr(BtApiStore, "_resolve_provider", forbidden)
    monkeypatch.setattr(BtApiStore, "_apply_env_gateway_overrides", forbidden)
    monkeypatch.setattr(store_module, "_resolve_bt_api_client", forbidden)
    monkeypatch.setenv("BT_STORE_PROVIDER", "ib_web_gateway")
    monkeypatch.setenv("BT_CTP_EXECUTION_AUTHORIZATION_SECRET", "should-not-be-read")
    with pytest.raises(BtApiStoreError, match="route ambiguous"):
        BtApiStore(
            provider="ctp",
            backend="forwarding",
            api=api,
            config={"execution_authorization_secret": _CredentialTrap()},
            autostart=True,
        )
    assert api.reads == []
    assert calls == []


def test_explicit_non_ctp_route_preserves_raw_api_injection_without_route_ambiguity():
    api = _SafeInjectedApi()
    store = BtApiStore(provider="okx", api=api, config={"exchange_type": "OKX"})
    assert store._candidate_route_kind is RouteKind.NON_CTP
    assert store._api is api


def test_unknown_provider_and_ctp_routes_reject_without_inspecting_injected_objects():
    api = _AttributeTrap()
    with pytest.raises(BtApiStoreError, match="store route ambiguous"):
        BtApiStore(provider="custom-provider", api_cls=api, config={})
    assert api.reads == []

    with pytest.raises(BtApiStoreError, match="local ctp client injection forbidden"):
        BtApiStore(
            provider="ctp",
            api=api,
            account_actor_port=_QueuePort(),
            account_actor_context=_context(),
            account_actor_test_ledger=FakeLocalActorReplayLedger(),
        )
    assert api.reads == []


def test_ambiguous_btapi_adapter_only_is_lazy_and_has_no_local_dispatch(monkeypatch):
    api = _AttributeTrap()
    adapter = _ProjectionAdapter()
    calls = []
    monkeypatch.setattr(
        store_module, "_resolve_bt_api_client", lambda *a, **k: calls.append("sdk")
    )
    store = BtApiStore(
        provider="btapi", api=api, managed_execution_adapter=adapter
    )

    assert store._candidate_route_kind is RouteKind.AMBIGUOUS
    assert store._candidate_adapter_only is True
    assert store._api is None
    assert api.reads == []
    assert store.submit_order(SimpleNamespace(ref=31)) == {
        "status": "accepted", "id": "managed.order"
    }
    assert callable(adapter.legacy_dispatch)
    with pytest.raises(BtApiStoreError, match="forbids local legacy dispatch"):
        adapter.legacy_dispatch(SimpleNamespace(ref=31))
    assert api.reads == []
    assert calls == []
    with pytest.raises(BtApiStoreError, match="cannot start"):
        store.start()


def test_ambiguous_adapter_only_dispatch_revalidates_before_any_fallback(monkeypatch):
    api = _AttributeTrap()
    adapter = _DispatchingAdapter()
    store = BtApiStore(
        provider="btapi", api=api, managed_execution_adapter=adapter
    )
    with pytest.raises(BtApiStoreError, match="forbids local legacy dispatch"):
        store.submit_order(SimpleNamespace(ref=32))
    assert adapter.calls == 1
    assert api.reads == []

    adapter.calls = 0
    store._config["exchange_type"] = "CTP"
    with pytest.raises(BtApiStoreError, match="changed or became routable"):
        store.submit_order(SimpleNamespace(ref=33))
    assert adapter.calls == 0
    assert api.reads == []


def test_nested_ctp_routes_reject_before_sdk_or_forwarding_construction(monkeypatch):
    calls = []
    monkeypatch.setattr(
        store_module, "_resolve_bt_api_client", lambda *a, **k: calls.append("sdk")
    )
    monkeypatch.setenv("BT_GATEWAY_EXCHANGE_TYPE", "CTP")
    with pytest.raises(BtApiStoreError):
        BtApiStore(
            provider="btapi",
            backend="forwarding",
            api_kwargs={"exchange_kwargs": {"OKX": {"symbol_routes": {"rb": "CTP"}}}},
        )
    with pytest.raises(BtApiStoreError):
        BtApiStore(
            provider="gateway",
            backend="gateway",
            config={"exchange_type": "IB_WEB"},
        )
    assert calls == []


def test_explicit_non_ctp_route_is_detached_and_internal_route_mutation_fails_closed():
    route = {
        "exchange_kwargs": {
            "OKX": {"exchange_type": "OKX", "api_key": "preserved-test-value"}
        }
    }
    store = BtApiStore(provider="okx", config=route)
    assert store._candidate_route_kind is RouteKind.NON_CTP
    assert store._config["exchange_kwargs"]["OKX"]["api_key"] == "preserved-test-value"
    route["exchange_kwargs"]["OKX"]["exchange_type"] = "CTP"
    store._candidate_require_route(RouteKind.NON_CTP)

    store._config["exchange_kwargs"]["OKX"]["exchange_type"] = "CTP"
    with pytest.raises(BtApiStoreError, match="route changed"):
        store.start()
    with pytest.raises(BtApiStoreError, match="route changed"):
        store._ensure_api_ready()

    route = {"exchange_type": "OKX"}
    backend_store = BtApiStore(provider="okx", config=route)
    backend_store.backend = "forwarding"
    with pytest.raises(BtApiStoreError, match="route changed"):
        backend_store._candidate_require_route(RouteKind.NON_CTP)
    with pytest.raises(BtApiStoreError, match="route changed"):
        backend_store._create_forwarding_client()


def test_descriptor_copies_route_facts_before_caller_mutation():
    config = {"exchange_type": "OKX"}
    from backtrader.stores.btapistore import _candidate_route_descriptor

    route = _candidate_route_descriptor("okx", None, config, {}, None, None)
    assert classify_store_route(route) is RouteKind.NON_CTP
    config["exchange_type"] = "CTP"
    assert classify_store_route(route) is RouteKind.NON_CTP


def test_nested_ctp_evidence_cannot_turn_an_unrelated_or_unknown_provider_into_actor_route():
    port = _QueuePort()
    context = _context()
    with pytest.raises(BtApiStoreError, match="route ambiguous"):
        BtApiStore(
            provider="custom-provider",
            config={"exchange_type": "CTP"},
            account_actor_port=port,
            account_actor_context=context,
            account_actor_test_ledger=FakeLocalActorReplayLedger(),
        )
    with pytest.raises(BtApiStoreError, match="route ambiguous"):
        BtApiStore(
            provider="okx",
            api_kwargs={"symbol_routes": {"rb2710": "CTP"}},
            account_actor_port=port,
            account_actor_context=context,
            account_actor_test_ledger=FakeLocalActorReplayLedger(),
        )
    with pytest.raises(BtApiStoreError, match="route ambiguous"):
        BtApiStore(
            provider="ctp",
            backend="unknown-backend",
            account_actor_port=port,
            account_actor_context=context,
            account_actor_test_ledger=FakeLocalActorReplayLedger(),
        )
    assert port.calls == []


def test_actor_v2_receipt_is_only_local_observation_and_start_has_no_shared_read_feed():
    context = _context()
    port = _QueuePort()
    store = BtApiStore(
        provider="ctp",
        backend="forwarding",
        account_actor_port=port,
        account_actor_context=context,
        account_actor_test_ledger=FakeLocalActorReplayLedger(),
    )
    assert store._is_ctp_session_provider() is True
    submit_receipt = store.submit_order(_submit(context))
    cancel_receipt = store.cancel_order(_cancel(context))
    assert submit_receipt.state is ActorCommandState.QUEUED
    assert cancel_receipt.state is ActorCommandState.QUEUED
    assert port.calls == [("SUBMIT", "submit-1"), ("CANCEL", "cancel-1")]
    with pytest.raises(BtApiStoreError, match="read feed"):
        store.start()
    with pytest.raises(BtApiStoreError, match="typed account actor cancel intent"):
        store.cancel_order_ref("provider-order-1")
    assert store.stop() is None
    with pytest.raises(BtApiStoreError, match="legacy submit"):
        store._submit_order_legacy(object())
    with pytest.raises(BtApiStoreError, match="legacy cancel"):
        store._cancel_order_ref_legacy("provider-order-1")
    with pytest.raises(BtApiStoreError, match="local client construction"):
        store._ensure_api_ready()
    with pytest.raises(BtApiStoreError, match="forwarding construction"):
        store._create_forwarding_client()
    with pytest.raises(BtApiStoreError, match="local SDK command queue"):
        store.enqueue_order(object())
    with pytest.raises(BtApiStoreError, match="local SDK command queue"):
        store.enqueue_cancel("provider-order-1")


def test_actor_receipt_mismatch_and_replay_never_fall_back_to_local_sdk():
    context = _context()
    port = _QueuePort(corrupt=True)
    store = BtApiStore(
        provider="ctp",
        account_actor_port=port,
        account_actor_context=context,
        account_actor_test_ledger=FakeLocalActorReplayLedger(),
    )
    intent = _submit(context)
    with pytest.raises(BtApiStoreError, match="digest mismatch"):
        store.submit_order(intent)
    assert port.calls == [("SUBMIT", "submit-1")]
    with pytest.raises(BtApiStoreError, match="replay"):
        store.submit_order(intent)
    assert port.calls == [("SUBMIT", "submit-1")]


def test_actor_autostart_is_rejected_before_store_initialization_or_local_client(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        BtApiStore, "_resolve_provider", lambda *a, **k: calls.append("resolve")
    )
    with pytest.raises(BtApiStoreError, match="no accepted shared-session read feed"):
        BtApiStore(
            provider="ctp",
            account_actor_port=_QueuePort(),
            account_actor_context=_context(),
            account_actor_test_ledger=FakeLocalActorReplayLedger(),
            autostart=True,
        )
    assert calls == []


def test_bad_or_missing_actor_setup_fails_before_provider_resolution(monkeypatch):
    calls = []
    monkeypatch.setattr(
        BtApiStore, "_resolve_provider", lambda *a, **k: calls.append("resolve")
    )
    with pytest.raises(BtApiStoreError, match="external account actor unavailable"):
        BtApiStore(provider="ctp", autostart=True)
    assert calls == []

    with pytest.raises(BtApiStoreError, match="store provider unsupported"):
        BtApiStore(provider="futu")
    assert calls == []
