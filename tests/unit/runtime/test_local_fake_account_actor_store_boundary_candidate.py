import unittest
from dataclasses import replace
from decimal import Decimal

from backtrader_runtime._local_fake_account_actor_candidate.account_actor_port import (
    AccountActorGateError,
    ActorCommandContextV1,
    ActorCommandReceiptV2,
    ActorCommandState,
    CtpAccountActorPort,
    CtpCancelIntentV2,
    CtpSubmitIntentV2,
    FakeLocalActorReplayLedger,
    RouteKind,
    StoreRouteDescriptor,
    UnavailableCtpAccountActorPort,
    classify_store_route,
)
from backtrader_runtime._local_fake_account_actor_candidate.store_boundary_harness import (
    StoreBoundaryHarness,
)


class Counters:
    def __init__(self):
        self.constructed = 0
        self.connected = 0
        self.native_calls = 0
        self.gateway_created = 0


class FakeNativeClient:
    def __init__(self, counters):
        counters.constructed += 1
        self.counters = counters

    def connect(self):
        self.counters.connected += 1

    def ReqOrderInsert(self, *_args):
        self.counters.native_calls += 1
        return 0

    def ReqOrderAction(self, *_args):
        self.counters.native_calls += 1
        return 0


class FakeActorPort(CtpAccountActorPort):
    def __init__(self):
        self.submits = []
        self.cancels = []
        self.receipt_mutator = None

    def _receipt(self, intent):
        receipt = ActorCommandReceiptV2(
            operation=intent.operation,
            command_id=intent.command_id,
            state=ActorCommandState.QUEUED,
            context=intent.context,
            command_digest=intent.command_digest,
        )
        return self.receipt_mutator(receipt) if self.receipt_mutator else receipt

    def submit_order(self, intent):
        self.submits.append(intent)
        return self._receipt(intent)

    def cancel_order(self, intent):
        self.cancels.append(intent)
        return self._receipt(intent)


def actor_context(**overrides):
    values = {
        "account_ref": "ctp-account-ref.v1:account-test",
        "runtime_id": "runtime-test",
        "mode": "simulation",
        "config_digest": "a" * 64,
        "session_id": "session-test",
        "front_id": 7,
        "native_session_id": 11,
        "session_generation": 4,
        "actor_epoch": 3,
    }
    values.update(overrides)
    return ActorCommandContextV1(**values)


def submit_intent(*, context=None, intent_id="submit-1"):
    return CtpSubmitIntentV2(
        intent_id=intent_id,
        instrument_id="IF2601",
        exchange_id="CFFEX",
        side="BUY",
        offset="OPEN",
        hedge_flag="SPECULATION",
        quantity=1,
        limit_price=Decimal("3000.5"),
        context=context or actor_context(),
    )


def cancel_intent(*, context=None, cancel_intent_id="cancel-1", front_id=None, session_id=None):
    current = context or actor_context()
    return CtpCancelIntentV2(
        cancel_intent_id=cancel_intent_id,
        runtime_order_id="runtime-order-1",
        order_ref="123",
        front_id=current.front_id if front_id is None else front_id,
        session_id=current.native_session_id if session_id is None else session_id,
        exchange_id="CFFEX",
        order_sys_id="system-order-1",
        context=current,
    )


def actor_store(actor, *, context=None, route=None, **kwargs):
    kwargs.setdefault("receipt_ledger", FakeLocalActorReplayLedger())
    return StoreBoundaryHarness(
        route or StoreRouteDescriptor(provider="ctp", backend="direct"),
        actor_port=actor,
        actor_context=context or actor_context(),
        **kwargs,
    )


class ActorPortGateTests(unittest.TestCase):
    def test_ctp_direct_legacy_store_rejects_before_api_class_factory(self):
        counters = Counters()

        def factory():
            return FakeNativeClient(counters)

        route = StoreRouteDescriptor(
            provider="ctp",
            backend="direct",
            api_cls=FakeNativeClient,
        )
        with self.assertRaisesRegex(AccountActorGateError, "external account actor unavailable"):
            StoreBoundaryHarness(
                route,
                credential_resolver=lambda: self.fail("credentials must not be resolved"),
                api_factory=factory,
            )
        self.assertEqual(counters.constructed, 0)
        self.assertEqual(counters.connected, 0)
        self.assertEqual(counters.native_calls, 0)

    def test_ctp_gateway_rejects_before_legacy_gateway_import_or_factory(self):
        counters = Counters()

        def gateway_factory():
            counters.gateway_created += 1
            return FakeNativeClient(counters)

        route = StoreRouteDescriptor(
            provider="gateway",
            backend="gateway",
            config={"exchange_type": "CTP"},
        )
        with self.assertRaisesRegex(AccountActorGateError, "external account actor unavailable"):
            StoreBoundaryHarness(
                route,
                credential_resolver=lambda: self.fail("credentials must not be resolved"),
                gateway_factory=gateway_factory,
            )
        self.assertEqual(counters.gateway_created, 0)
        self.assertEqual(counters.constructed, 0)
        self.assertEqual(counters.native_calls, 0)

    def test_ctp_gateway_default_exchange_is_fail_closed(self):
        route = StoreRouteDescriptor(provider="ctp_gateway", backend="gateway")
        self.assertIs(classify_store_route(route), RouteKind.CTP)
        with self.assertRaisesRegex(AccountActorGateError, "external account actor unavailable"):
            StoreBoundaryHarness(
                route,
                credential_resolver=lambda: self.fail("credentials must not be resolved"),
            )
        self.assertIs(classify_store_route(StoreRouteDescriptor(provider="ctp")), RouteKind.CTP)

    def test_gateway_primary_exchange_cannot_mask_ctp_symbol_route(self):
        counters = Counters()
        route = StoreRouteDescriptor(
            provider="gateway",
            backend="gateway",
            config={
                "exchange_type": "OKX",
                "symbol_routes": {"IF2601": "CTP"},
            },
        )
        self.assertIs(classify_store_route(route), RouteKind.CTP)

        def gateway_factory():
            counters.gateway_created += 1
            return FakeNativeClient(counters)

        with self.assertRaisesRegex(AccountActorGateError, "external account actor unavailable"):
            StoreBoundaryHarness(
                route,
                credential_resolver=lambda: self.fail("credentials must not be resolved"),
                gateway_factory=gateway_factory,
            )
        self.assertEqual(counters.gateway_created, 0)
        self.assertEqual(counters.constructed, 0)
        self.assertEqual(counters.native_calls, 0)

    def test_injected_api_is_rejected_before_store_connect_or_native_call(self):
        counters = Counters()
        prebuilt = FakeNativeClient(counters)
        route = StoreRouteDescriptor(provider="ctp", backend="direct", api=prebuilt)
        with self.assertRaisesRegex(AccountActorGateError, "external account actor unavailable"):
            StoreBoundaryHarness(
                route,
                credential_resolver=lambda: self.fail("credentials must not be resolved"),
            )
        self.assertEqual(counters.constructed, 1)  # caller built it before Store entry
        self.assertEqual(counters.connected, 0)
        self.assertEqual(counters.native_calls, 0)

    def test_actor_route_rejects_api_and_api_cls_injection_even_with_actor(self):
        counters = Counters()
        actor = FakeActorPort()
        prebuilt = FakeNativeClient(counters)
        route = StoreRouteDescriptor(provider="ctp", api=prebuilt)
        with self.assertRaisesRegex(AccountActorGateError, "local ctp client injection forbidden"):
            StoreBoundaryHarness(route, actor_port=actor)
        route = StoreRouteDescriptor(provider="ctp", api_cls=FakeNativeClient)
        with self.assertRaisesRegex(AccountActorGateError, "local ctp client injection forbidden"):
            StoreBoundaryHarness(route, actor_port=actor, api_factory=lambda counters=counters: FakeNativeClient(counters))
        self.assertEqual(counters.constructed, 1)
        self.assertEqual(counters.native_calls, 0)
        self.assertEqual(actor.submits, [])

    def test_btapi_ctp_exchange_configuration_rejects_before_custom_class(self):
        counters = Counters()
        route = StoreRouteDescriptor(
            provider="btapi",
            api_kwargs={"exchange_kwargs": {"CTP": {"broker_id": "fake"}}},
            api_cls=FakeNativeClient,
        )
        self.assertIs(classify_store_route(route), RouteKind.CTP)
        with self.assertRaisesRegex(AccountActorGateError, "external account actor unavailable"):
            StoreBoundaryHarness(route, api_factory=lambda counters=counters: FakeNativeClient(counters))
        self.assertEqual(counters.constructed, 0)
        self.assertEqual(counters.native_calls, 0)

    def test_ambiguous_btapi_custom_client_fails_closed_before_factory(self):
        counters = Counters()
        route = StoreRouteDescriptor(provider="btapi", api_cls=FakeNativeClient)
        self.assertIs(classify_store_route(route), RouteKind.AMBIGUOUS)
        with self.assertRaisesRegex(AccountActorGateError, "route ambiguous"):
            StoreBoundaryHarness(
                route,
                credential_resolver=lambda: self.fail("credentials must not be resolved"),
                api_factory=lambda counters=counters: FakeNativeClient(counters),
            )
        self.assertEqual(counters.constructed, 0)
        self.assertEqual(counters.native_calls, 0)

    def test_unknown_provider_and_unknown_gateway_suffix_never_fall_through(self):
        for route in (
            StoreRouteDescriptor(provider="custom_exchange", api_cls=FakeNativeClient),
            StoreRouteDescriptor(provider="custom_exchange"),
            StoreRouteDescriptor(provider="custom_gateway", backend="gateway"),
        ):
            with self.subTest(provider=route.provider):
                self.assertIs(classify_store_route(route), RouteKind.AMBIGUOUS)
                with self.assertRaisesRegex(AccountActorGateError, "route ambiguous"):
                    StoreBoundaryHarness(route, actor_port=FakeActorPort())

    def test_known_placeholder_provider_is_unsupported(self):
        route = StoreRouteDescriptor(provider="futu")
        self.assertIs(classify_store_route(route), RouteKind.UNSUPPORTED)
        with self.assertRaisesRegex(AccountActorGateError, "provider unsupported"):
            StoreBoundaryHarness(route, actor_port=FakeActorPort())

    def test_malformed_backend_and_environment_types_are_ambiguous(self):
        for route in (
            StoreRouteDescriptor(provider="okx", backend=object()),
            StoreRouteDescriptor(provider="okx", environment_provider=object()),
            StoreRouteDescriptor(provider="okx", environment_exchange_type=object()),
        ):
            with self.subTest(provider=route.provider):
                self.assertIs(classify_store_route(route), RouteKind.AMBIGUOUS)

    def test_untrusted_api_properties_are_never_read_by_classifier_or_gate(self):
        class TrapClient:
            @property
            def exchange_kwargs(self):
                raise AssertionError("untrusted API property must not be read")

        route = StoreRouteDescriptor(provider="btapi", api=TrapClient())
        self.assertIs(classify_store_route(route), RouteKind.AMBIGUOUS)
        with self.assertRaisesRegex(AccountActorGateError, "route ambiguous"):
            StoreBoundaryHarness(route, actor_port=FakeActorPort())

        route = StoreRouteDescriptor(provider="gateway", backend="gateway", api_cls=TrapClient)
        self.assertIs(classify_store_route(route), RouteKind.AMBIGUOUS)
        with self.assertRaisesRegex(AccountActorGateError, "route ambiguous"):
            StoreBoundaryHarness(route, actor_port=FakeActorPort())

    def test_exact_code_owned_non_ctp_routes_remain_classifiable(self):
        safe_routes = (
            StoreRouteDescriptor(provider="okx"),
            StoreRouteDescriptor(provider="binance", backend="direct"),
            StoreRouteDescriptor(
                provider="btapi",
                config={
                    "exchange_kwargs": {"OKX": {}, "BINANCE": {}},
                    "symbol_routes": {"BTC-USDT": "OKX___SWAP", "ETH-USDT": "BINANCE___SPOT"},
                },
            ),
            StoreRouteDescriptor(
                provider="gateway",
                backend="gateway",
                config={"exchange_type": "IB_WEB"},
            ),
            StoreRouteDescriptor(
                provider="mt5_gateway",
                backend="gateway",
                config={"exchange_type": "MT5"},
            ),
            StoreRouteDescriptor(
                provider="ib_web_gateway",
                backend="gateway",
                environment_exchange_type="IB_WEB",
            ),
        )
        for route in safe_routes:
            with self.subTest(provider=route.provider, config=route.config):
                self.assertIs(classify_store_route(route), RouteKind.NON_CTP)

    def test_raw_api_and_api_cls_injection_is_ambiguous_without_introspection(self):
        class TrapClient:
            @property
            def exchange_kwargs(self):
                raise AssertionError("API must not be introspected")

        for route in (
            StoreRouteDescriptor(provider="okx", api=TrapClient()),
            StoreRouteDescriptor(provider="okx", api_cls=TrapClient),
            StoreRouteDescriptor(
                provider="gateway",
                backend="gateway",
                config={"exchange_type": "IB_WEB"},
                api=TrapClient(),
            ),
            StoreRouteDescriptor(
                provider="btapi",
                config={"symbol_routes": {"BTC-USDT": "OKX"}},
                api_cls=TrapClient,
            ),
        ):
            with self.subTest(provider=route.provider, has_api=route.api is not None):
                self.assertIs(classify_store_route(route), RouteKind.AMBIGUOUS)
                with self.assertRaisesRegex(AccountActorGateError, "route ambiguous"):
                    StoreBoundaryHarness(route, actor_port=FakeActorPort())

    def test_environment_provider_cannot_downgrade_ctp(self):
        routes = (
            StoreRouteDescriptor(
                provider="ctp",
                backend="direct",
                environment_provider="ib_web_gateway",
                environment_exchange_type="IB_WEB",
            ),
            StoreRouteDescriptor(
                provider="ctp",
                config={"exchange_type": "CTP"},
                environment_provider="gateway",
                environment_exchange_type="MT5",
            ),
            StoreRouteDescriptor(
                provider="ctp_gateway",
                backend="gateway",
                environment_provider="okx",
                environment_exchange_type="OKX",
            ),
        )
        for route in routes:
            with self.subTest(environment_provider=route.environment_provider):
                self.assertIs(classify_store_route(route), RouteKind.CTP)
                counters = Counters()
                with self.assertRaisesRegex(AccountActorGateError, "external account actor unavailable"):
                    StoreBoundaryHarness(
                        route,
                        credential_resolver=lambda: self.fail("credentials must not be resolved"),
                        api_factory=lambda counters=counters: FakeNativeClient(counters),
                        gateway_factory=lambda counters=counters: FakeNativeClient(counters),
                    )
                self.assertEqual(counters.constructed, 0)
                self.assertEqual(counters.native_calls, 0)

    def test_nested_symbol_routes_detect_ctp_and_reject_unknown(self):
        ctp_route = StoreRouteDescriptor(
            provider="btapi",
            config={
                "exchange_kwargs": {"OKX": {}},
                "symbol_routes": {
                    "by_market": {"IF2601": {"exchange_type": "CTP"}},
                    "BTC-USDT": "OKX___SWAP",
                },
            },
        )
        self.assertIs(classify_store_route(ctp_route), RouteKind.CTP)
        with self.assertRaisesRegex(AccountActorGateError, "external account actor unavailable"):
            StoreBoundaryHarness(ctp_route, credential_resolver=lambda: self.fail("credentials"))

        unknown_route = StoreRouteDescriptor(
            provider="btapi",
            config={"symbol_routes": {"BTC-USDT": {"venue": "UNKNOWN_VENUE"}}},
        )
        self.assertIs(classify_store_route(unknown_route), RouteKind.AMBIGUOUS)
        with self.assertRaisesRegex(AccountActorGateError, "route ambiguous"):
            StoreBoundaryHarness(unknown_route, actor_port=FakeActorPort())

        hidden_exchange_ctp = StoreRouteDescriptor(
            provider="btapi",
            config={"exchange_kwargs": {"OKX": {"routing": {"exchange_type": "CTP"}}}},
        )
        self.assertIs(classify_store_route(hidden_exchange_ctp), RouteKind.CTP)

    def test_environment_reselection_of_non_ctp_provider_is_ambiguous(self):
        route = StoreRouteDescriptor(
            provider="okx",
            environment_provider="binance",
        )
        self.assertIs(classify_store_route(route), RouteKind.AMBIGUOUS)
        with self.assertRaisesRegex(AccountActorGateError, "route ambiguous"):
            StoreBoundaryHarness(route, actor_port=FakeActorPort())

    def test_actor_only_typed_submit_and_cancel_have_no_local_native_client(self):
        actor = FakeActorPort()
        route = StoreRouteDescriptor(provider="ctp", backend="direct")
        store = actor_store(actor, route=route)
        submit_result = store.submit_order(submit_intent())
        cancel_result = store.cancel_order(cancel_intent())
        self.assertEqual(submit_result.state, ActorCommandState.QUEUED)
        self.assertEqual(cancel_result.state, ActorCommandState.QUEUED)
        self.assertEqual(len(actor.submits), 1)
        self.assertEqual(len(actor.cancels), 1)
        self.assertIsNone(store.api)
        self.assertEqual(store.legacy_calls, 0)

    def test_actor_route_rejects_legacy_private_fallback(self):
        actor = FakeActorPort()
        store = actor_store(actor, route=StoreRouteDescriptor(provider="ctp", backend="direct"))
        with self.assertRaisesRegex(AccountActorGateError, "ctp legacy dispatch forbidden"):
            store._submit_order_legacy(submit_intent())
        with self.assertRaisesRegex(AccountActorGateError, "ctp legacy dispatch forbidden"):
            store._cancel_order_legacy(cancel_intent())
        self.assertEqual(store.legacy_calls, 0)

    def test_actor_route_requires_exact_typed_intents_and_no_dict_fallback(self):
        actor = FakeActorPort()
        store = actor_store(actor, route=StoreRouteDescriptor(provider="ctp"))
        with self.assertRaisesRegex(AccountActorGateError, "typed submit intent required"):
            store.submit_order({"instrument_id": "IF2601"})
        with self.assertRaisesRegex(AccountActorGateError, "typed cancel intent required"):
            store.cancel_order({"order_ref": "123"})
        self.assertEqual(actor.submits, [])
        self.assertEqual(actor.cancels, [])

    def test_bad_actor_receipt_never_falls_back_to_native(self):
        class BadActor(FakeActorPort):
            def submit_order(self, intent):
                self.submits.append(intent)
                return True

        actor = BadActor()
        store = actor_store(actor, route=StoreRouteDescriptor(provider="ctp"))
        with self.assertRaisesRegex(AccountActorGateError, "actor receipt type invalid"):
            store.submit_order(submit_intent())
        self.assertIsNone(store.api)
        self.assertEqual(store.legacy_calls, 0)

    def test_ctp_actor_requires_explicit_fake_replay_ledger(self):
        actor = FakeActorPort()
        with self.assertRaisesRegex(AccountActorGateError, "fake replay ledger required"):
            StoreBoundaryHarness(
                StoreRouteDescriptor(provider="ctp"),
                actor_port=actor,
                actor_context=actor_context(),
                credential_resolver=lambda: self.fail("credentials must not be resolved"),
            )
        self.assertEqual(actor.submits, [])


class TypedIntentValidationTests(unittest.TestCase):
    def test_bool_quantity_is_not_native_integer_quantity(self):
        with self.assertRaisesRegex(ValueError, "positive exact integer"):
            CtpSubmitIntentV2(
                intent_id="i",
                instrument_id="x",
                exchange_id="e",
                side="BUY",
                offset="OPEN",
                hedge_flag="SPECULATION",
                quantity=True,
                limit_price=Decimal(1),
                context=actor_context(),
            )

    def test_bool_front_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive exact integer"):
            CtpCancelIntentV2(
                cancel_intent_id="c",
                runtime_order_id="r",
                order_ref="o",
                front_id=True,
                session_id=1,
                exchange_id="e",
                order_sys_id="s",
                context=actor_context(),
            )

    def test_unavailable_default_does_not_claim_authority(self):
        unavailable = UnavailableCtpAccountActorPort()
        with self.assertRaisesRegex(AccountActorGateError, "external account actor unavailable"):
            unavailable.submit_order(submit_intent())


class ActorReceiptBindingTests(unittest.TestCase):
    def test_intent_digest_binds_context_and_all_logical_fields(self):
        baseline = submit_intent()
        self.assertEqual(len(baseline.command_digest), 64)
        self.assertNotEqual(
            baseline.command_digest,
            submit_intent(context=actor_context(actor_epoch=baseline.context.actor_epoch + 1)).command_digest,
        )
        self.assertNotEqual(
            baseline.command_digest,
            submit_intent(intent_id="submit-other").command_digest,
        )

    def test_stale_epoch_wrong_account_or_wrong_session_intent_reject_before_actor(self):
        expected = actor_context()
        adversarial_contexts = (
            actor_context(actor_epoch=expected.actor_epoch + 1),
            actor_context(account_ref="ctp-account-ref.v1:other"),
            actor_context(session_id="different-session"),
            actor_context(front_id=expected.front_id + 1),
            actor_context(native_session_id=expected.native_session_id + 1),
            actor_context(session_generation=expected.session_generation + 1),
            actor_context(runtime_id="other-runtime"),
            actor_context(mode="live"),
            actor_context(config_digest="b" * 64),
        )
        for wrong_context in adversarial_contexts:
            with self.subTest(context=wrong_context):
                actor = FakeActorPort()
                counters = Counters()
                store = actor_store(
                    actor,
                    context=expected,
                    api_factory=lambda counters=counters: FakeNativeClient(counters),
                    gateway_factory=lambda counters=counters: FakeNativeClient(counters),
                )
                with self.assertRaisesRegex(AccountActorGateError, "intent context mismatch"):
                    store.submit_order(submit_intent(context=wrong_context))
                self.assertEqual(actor.submits, [])
                self.assertEqual(actor.cancels, [])
                self.assertIsNone(store.api)
                self.assertEqual(store.legacy_calls, 0)
                self.assertEqual(counters.constructed, 0)
                self.assertEqual(counters.native_calls, 0)

        for wrong_context in (
            actor_context(front_id=expected.front_id + 1),
            actor_context(native_session_id=expected.native_session_id + 1),
        ):
            actor = FakeActorPort()
            counters = Counters()
            store = actor_store(
                actor,
                context=expected,
                api_factory=lambda counters=counters: FakeNativeClient(counters),
                gateway_factory=lambda counters=counters: FakeNativeClient(counters),
            )
            with self.assertRaisesRegex(AccountActorGateError, "intent context mismatch"):
                store.cancel_order(cancel_intent(context=wrong_context))
            self.assertEqual(actor.cancels, [])
            self.assertEqual(store.legacy_calls, 0)
            self.assertEqual(counters.constructed, 0)
            self.assertEqual(counters.native_calls, 0)

    def test_cancel_native_front_and_session_must_match_context(self):
        with self.assertRaisesRegex(ValueError, "match the expected native front/session"):
            cancel_intent(session_id=999)
        with self.assertRaisesRegex(ValueError, "match the expected native front/session"):
            cancel_intent(front_id=999)

    def test_duplicate_intent_is_claimed_once_before_actor_call(self):
        actor = FakeActorPort()
        ledger = FakeLocalActorReplayLedger()
        counters = Counters()
        first = actor_store(
            actor,
            receipt_ledger=ledger,
            api_factory=lambda counters=counters: FakeNativeClient(counters),
        )
        second = actor_store(
            actor,
            receipt_ledger=ledger,
            api_factory=lambda counters=counters: FakeNativeClient(counters),
        )
        first.submit_order(submit_intent())
        with self.assertRaisesRegex(AccountActorGateError, "actor intent replay"):
            second.submit_order(replace(submit_intent(), quantity=2))
        self.assertEqual(len(actor.submits), 1)
        self.assertEqual(counters.constructed, 0)
        self.assertEqual(counters.native_calls, 0)
        self.assertEqual(first.legacy_calls + second.legacy_calls, 0)

    def test_receipt_wrong_command_is_rejected_without_local_fallback(self):
        actor = FakeActorPort()
        actor.receipt_mutator = lambda receipt: replace(receipt, command_id="forged-command")
        counters = Counters()
        store = actor_store(
            actor,
            api_factory=lambda counters=counters: FakeNativeClient(counters),
            gateway_factory=lambda counters=counters: FakeNativeClient(counters),
        )
        with self.assertRaisesRegex(AccountActorGateError, "receipt command mismatch"):
            store.submit_order(submit_intent())
        self.assertEqual(len(actor.submits), 1)
        self.assertEqual(counters.constructed, 0)
        self.assertEqual(counters.native_calls, 0)
        self.assertEqual(store.legacy_calls, 0)

    def test_receipt_wrong_operation_is_rejected_without_local_fallback(self):
        actor = FakeActorPort()
        actor.receipt_mutator = lambda receipt: replace(receipt, operation="CANCEL")
        counters = Counters()
        store = actor_store(
            actor,
            api_factory=lambda counters=counters: FakeNativeClient(counters),
            gateway_factory=lambda counters=counters: FakeNativeClient(counters),
        )
        with self.assertRaisesRegex(AccountActorGateError, "receipt operation mismatch"):
            store.submit_order(submit_intent())
        self.assertEqual(len(actor.submits), 1)
        self.assertEqual(counters.constructed, 0)
        self.assertEqual(counters.native_calls, 0)
        self.assertEqual(store.legacy_calls, 0)

    def test_receipt_rejects_stale_epoch_wrong_account_and_wrong_session(self):
        context = actor_context()
        mutations = (
            {"actor_epoch": context.actor_epoch + 1},
            {"account_ref": "ctp-account-ref.v1:other"},
            {"session_id": "other-session"},
            {"front_id": context.front_id + 1},
            {"native_session_id": context.native_session_id + 1},
            {"session_generation": context.session_generation + 1},
            {"runtime_id": "other-runtime"},
            {"mode": "live"},
            {"config_digest": "b" * 64},
        )
        for mutation in mutations:
            actor = FakeActorPort()
            actor.receipt_mutator = lambda receipt, mutation=mutation: replace(
                receipt, context=actor_context(**mutation)
            )
            counters = Counters()
            store = actor_store(
                actor,
                context=context,
                api_factory=lambda counters=counters: FakeNativeClient(counters),
                gateway_factory=lambda counters=counters: FakeNativeClient(counters),
            )
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(AccountActorGateError, "receipt context mismatch"):
                    store.submit_order(submit_intent(context=context))
                self.assertEqual(len(actor.submits), 1)
                self.assertIsNone(store.api)
                self.assertEqual(store.legacy_calls, 0)
                self.assertEqual(counters.constructed, 0)
                self.assertEqual(counters.native_calls, 0)

    def test_receipt_wrong_digest_and_untyped_receipt_are_rejected(self):
        for mutator, expected_error in (
            (
                lambda receipt: replace(receipt, command_digest="f" * 64),
                "receipt digest mismatch",
            ),
            (lambda _receipt: True, "receipt type invalid"),
        ):
            actor = FakeActorPort()
            actor.receipt_mutator = mutator
            counters = Counters()
            store = actor_store(
                actor,
                api_factory=lambda counters=counters: FakeNativeClient(counters),
                gateway_factory=lambda counters=counters: FakeNativeClient(counters),
            )
            with self.subTest(expected_error=expected_error):
                with self.assertRaisesRegex(AccountActorGateError, expected_error):
                    store.submit_order(submit_intent())
                self.assertEqual(len(actor.submits), 1)
                self.assertEqual(counters.constructed, 0)
                self.assertEqual(counters.native_calls, 0)
                self.assertEqual(store.legacy_calls, 0)

    def test_receipt_failure_consumes_fake_local_replay_slot(self):
        actor = FakeActorPort()
        actor.receipt_mutator = lambda receipt: replace(receipt, command_id="wrong")
        ledger = FakeLocalActorReplayLedger()
        store = actor_store(actor, receipt_ledger=ledger)
        with self.assertRaisesRegex(AccountActorGateError, "receipt command mismatch"):
            store.submit_order(submit_intent())
        actor.receipt_mutator = None
        with self.assertRaisesRegex(AccountActorGateError, "actor intent replay"):
            store.submit_order(submit_intent())
        self.assertEqual(len(actor.submits), 1)
        self.assertEqual(store.legacy_calls, 0)


if __name__ == "__main__":
    unittest.main()
