import hashlib
import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace

from account_actor_port import (
    AccountActorGateError,
    ActorCommandExpectationV2,
    ActorCommandReceiptV2,
    ActorCommandState,
    FakeLocalActorReplayLedger,
    StoreRouteDescriptor,
    validate_actor_receipt,
)
from store_boundary_harness import StoreBoundaryHarness
from test_store_boundary_harness import (
    Counters,
    FakeActorPort,
    actor_context,
    actor_store,
    submit_intent,
)


class IndependentActorPortProbe(unittest.TestCase):
    def test_stale_epoch_and_wrong_account_reject_before_actor(self):
        expected = actor_context()
        for altered in (
            actor_context(actor_epoch=expected.actor_epoch - 1),
            actor_context(account_ref="ctp-account-ref.v1:other"),
        ):
            actor = FakeActorPort()
            counters = Counters()
            store = actor_store(
                actor,
                context=expected,
                api_factory=lambda: counters.constructed + 1,
                gateway_factory=lambda: counters.constructed + 1,
            )
            with self.subTest(context=altered):
                with self.assertRaises(AccountActorGateError) as caught:
                    store.submit_order(submit_intent(context=altered))
                self.assertEqual(caught.exception.code, "actor_intent_context_mismatch")
                self.assertEqual(actor.submits, [])
                self.assertEqual(actor.cancels, [])
                self.assertIsNone(store.api)
                self.assertEqual(store.legacy_calls, 0)
                self.assertEqual(counters.constructed, 0)

    def test_wrong_action_receipt_rejects_without_native_fallback(self):
        actor = FakeActorPort()
        actor.receipt_mutator = lambda receipt: replace(receipt, operation="CANCEL")
        counters = Counters()
        store = actor_store(
            actor,
            api_factory=lambda: counters.constructed + 1,
            gateway_factory=lambda: counters.constructed + 1,
        )
        with self.assertRaises(AccountActorGateError) as caught:
            store.submit_order(submit_intent())
        self.assertEqual(caught.exception.code, "actor_receipt_operation_mismatch")
        self.assertEqual(len(actor.submits), 1)
        self.assertEqual(counters.constructed, 0)
        self.assertEqual(counters.native_calls, 0)
        self.assertEqual(store.legacy_calls, 0)

    def test_same_process_duplicate_intent_claims_once_before_actor(self):
        actor = FakeActorPort()
        ledger = FakeLocalActorReplayLedger()
        first = actor_store(actor, receipt_ledger=ledger)
        second = actor_store(actor, receipt_ledger=ledger)
        original = submit_intent(intent_id="qa-replay")
        first.submit_order(original)
        with self.assertRaises(AccountActorGateError) as caught:
            second.submit_order(replace(original, quantity=2))
        self.assertEqual(caught.exception.code, "actor_intent_replay")
        self.assertEqual(len(actor.submits), 1)
        self.assertEqual(first.legacy_calls + second.legacy_calls, 0)

    def test_fresh_process_ledger_accepts_previously_claimed_intent(self):
        intent = submit_intent(intent_id="cross-process-replay")
        FakeLocalActorReplayLedger().claim_once(intent)
        child = r'''
import sys
sys.path.insert(0, sys.argv[1])
from account_actor_port import ActorCommandContextV1, CtpSubmitIntentV2, FakeLocalActorReplayLedger
from decimal import Decimal
context = ActorCommandContextV1(
    account_ref="ctp-account-ref.v1:account-test",
    runtime_id="runtime-test",
    mode="simulation",
    config_digest="a" * 64,
    session_id="session-test",
    front_id=7,
    native_session_id=11,
    session_generation=4,
    actor_epoch=3,
)
intent = CtpSubmitIntentV2(
    intent_id="cross-process-replay",
    instrument_id="IF2601",
    exchange_id="CFFEX",
    side="BUY",
    offset="OPEN",
    hedge_flag="SPECULATION",
    quantity=1,
    limit_price=Decimal("3000.5"),
    context=context,
)
FakeLocalActorReplayLedger().claim_once(intent)
print("fresh_process_claim=accepted")
'''
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [sys.executable, "-B", "-c", child, root],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fresh_process_claim=accepted", result.stdout)
        # This is a measured limitation of the intentionally in-memory fake,
        # not evidence of durable actor replay protection.
        self.assertEqual(len(intent.command_digest), 64)

    def test_unkeyed_sha_digest_tamper_is_locally_detected_but_recomputable(self):
        intent = submit_intent(intent_id="digest-probe")
        expectation = ActorCommandExpectationV2.from_intent(intent)
        good = ActorCommandReceiptV2(
            operation=intent.operation,
            command_id=intent.command_id,
            state=ActorCommandState.QUEUED,
            context=intent.context,
            command_digest=intent.command_digest,
        )
        with self.assertRaises(AccountActorGateError) as caught:
            validate_actor_receipt(replace(good, command_digest="0" * 64), expected=expectation)
        self.assertEqual(caught.exception.code, "actor_receipt_digest_mismatch")

        payload = {
            "schema": "ctp-account-actor-command.v2",
            "operation": intent.operation,
            "command_id": intent.command_id,
            "context": intent.context.to_payload(),
            "intent": {
                "instrument_id": intent.instrument_id,
                "exchange_id": intent.exchange_id,
                "side": intent.side,
                "offset": intent.offset,
                "hedge_flag": intent.hedge_flag,
                "quantity": intent.quantity,
                "limit_price": format(intent.limit_price, "f"),
            },
        }
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), intent.command_digest)
        changed = replace(intent, quantity=2)
        self.assertNotEqual(changed.command_digest, intent.command_digest)
        # Anyone able to alter the logical payload can compute its replacement.
        # This is an equality checksum, not a keyed authentication tag.

    def test_injected_object_is_rejected_before_property_read(self):
        class TrapClient:
            reads = 0

            @property
            def exchange_kwargs(self):
                type(self).reads += 1
                raise AssertionError("injected property must not be evaluated")

        route = StoreRouteDescriptor(provider="btapi", api=TrapClient())
        with self.assertRaises(AccountActorGateError) as caught:
            StoreBoundaryHarness(route, actor_port=FakeActorPort())
        self.assertEqual(caught.exception.code, "store_route_ambiguous")
        self.assertEqual(TrapClient.reads, 0)

    def test_mutated_route_descriptor_is_not_reclassified_after_construction(self):
        route = StoreRouteDescriptor(provider="okx", config={"exchange_type": "OKX"})
        store = StoreBoundaryHarness(route)
        self.assertEqual(store.route_kind.value, "non_ctp")
        # The descriptor exposes the same mutable dictionary after the initial
        # classification. A later CTP mutation does not update the frozen kind.
        route.config["exchange_type"] = "CTP"
        self.assertEqual(store.submit_order(object()), "legacy_non_ctp")
        self.assertEqual(store.legacy_calls, 1)
        self.assertEqual(store.route_kind.value, "non_ctp")


if __name__ == "__main__":
    unittest.main(verbosity=2)
