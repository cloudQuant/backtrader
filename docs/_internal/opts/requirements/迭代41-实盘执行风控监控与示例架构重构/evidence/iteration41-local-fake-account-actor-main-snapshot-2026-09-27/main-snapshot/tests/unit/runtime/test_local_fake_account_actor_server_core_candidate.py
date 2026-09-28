from __future__ import annotations

import hashlib
import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from backtrader_runtime._local_fake_account_actor_candidate.account_actor_port import (
    ActorCommandContextV1,
)
from backtrader_runtime._local_fake_account_actor_candidate.account_actor_server_core import (
    AccountActorIntentV1,
    AccountActorServerCoreV1,
    AccountSnapshotBundleV1,
    ActorServerError,
    FakeSnapshotAuthorityV1,
    SnapshotDomainFactV1,
)

ACCOUNT_A = "ctp-account-ref.v1:" + hashlib.sha256(b"account-a-test-only").hexdigest()
ACCOUNT_B = "ctp-account-ref.v1:" + hashlib.sha256(b"account-b-test-only").hexdigest()
SOURCE_ID = "fake-source-1"
AUTHORITY_ID = "fake-authority-1"
TEST_KEY = b"test-only-not-a-deployed-secret-key-0123456789"


def _context(account_ref=ACCOUNT_A, *, epoch=1, session_id="session-1"):
    return ActorCommandContextV1(
        account_ref=account_ref,
        runtime_id="runtime-test",
        mode="simulation",
        config_digest=hashlib.sha256(b"test-config").hexdigest(),
        session_id=session_id,
        front_id=11,
        native_session_id=22,
        session_generation=3,
        actor_epoch=epoch,
    )


def _authority():
    return FakeSnapshotAuthorityV1(
        authority_id=AUTHORITY_ID,
        source_id=SOURCE_ID,
        key=TEST_KEY,
    )


def _bundle(account_ref=ACCOUNT_A, *, version=1, source_id=SOURCE_ID):
    payloads = {
        "funds": {"available": "100000.00", "currency": "CNY"},
        "orders": {"open_order_count": 0},
        "trades": {"trade_count": 0},
        "positions": {"position_count": 0},
    }
    facts = tuple(
        SnapshotDomainFactV1.from_payload(
            account_ref=account_ref,
            snapshot_version=version,
            source_id=source_id,
            domain=domain,
            payload=payloads[domain],
        )
        for domain in ("funds", "orders", "trades", "positions")
    )
    return AccountSnapshotBundleV1(account_ref, version, source_id, facts)


def _intent(
    *,
    account_ref=ACCOUNT_A,
    epoch=1,
    intent_id="intent-1",
    quantity=2,
    session_id="session-1",
):
    return AccountActorIntentV1.from_payload(
        operation="SUBMIT",
        intent_id=intent_id,
        context=_context(account_ref, epoch=epoch, session_id=session_id),
        payload={
            "instrument": "IF2612",
            "side": "BUY",
            "offset": "OPEN",
            "quantity": quantity,
            "limit_price": "3500.0",
        },
    )


def _claim_process(database_path, account_ref, barrier, connection, owner_id):
    core = AccountActorServerCoreV1(database_path)
    barrier.wait(timeout=10)
    try:
        handle = core.claim_writer(account_ref, owner_id)
        connection.send(("claimed", handle.epoch))
    except ActorServerError as exc:
        connection.send(("rejected", exc.code))
    finally:
        core.close()
        connection.close()


def _crash_after_claim_process(database_path, connection):
    core = AccountActorServerCoreV1(database_path)
    handle = core.claim_writer(ACCOUNT_A, "crashed-owner")
    connection.send(("claimed", handle.epoch))
    connection.close()
    os._exit(0)


def _reserve_process(database_path, writer, barrier, connection):
    core = AccountActorServerCoreV1(database_path, snapshot_authority=_authority())
    barrier.wait(timeout=10)
    try:
        command = core.reserve_intent(writer, _intent(), expected_snapshot_version=1)
        connection.send(("reserved", command.state, command.command_digest))
    except ActorServerError as exc:
        connection.send(("rejected", exc.code))
    finally:
        core.close()
        connection.close()


def _claim_dispatch_process(database_path, writer, authorization, connection):
    core = AccountActorServerCoreV1(
        database_path,
        snapshot_authority=_authority(),
    )
    try:
        core.claim_for_dispatch(writer, authorization)
        connection.send(("claimed", core.read_dispatch_state(
            ACCOUNT_A, authorization.operation, authorization.intent_id
        )))
    except ActorServerError as exc:
        connection.send(("rejected", exc.code, core.count_dispatch_rows(ACCOUNT_A),
                         core.read_dispatch_state(
                             ACCOUNT_A, authorization.operation, authorization.intent_id
                         )))
    finally:
        core.close()
        connection.close()


def _claim_and_crash_process(database_path, writer, authorization, connection):
    core = AccountActorServerCoreV1(
        database_path,
        snapshot_authority=_authority(),
    )
    claim = core.claim_for_dispatch(writer, authorization)
    connection.send(("claimed", claim.state))
    connection.close()
    os._exit(0)


class AccountActorServerCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="g6-actor-core-")
        self.database_path = str(Path(self.temp.name) / "actor.sqlite3")
        self.core = AccountActorServerCoreV1(
            self.database_path,
            snapshot_authority=_authority(),
        )
        self.writer = self.core.claim_writer(ACCOUNT_A, "writer-a")
        self.core.bind_session(self.writer, _context(epoch=self.writer.epoch))
        self.core.publish_snapshot(self.writer, _bundle())

    def tearDown(self):
        self.core.close()
        self.temp.cleanup()

    def test_snapshot_requires_exact_four_same_account_version_source_domains(self):
        incomplete = AccountSnapshotBundleV1.__new__(AccountSnapshotBundleV1)
        object.__setattr__(incomplete, "account_ref", ACCOUNT_A)
        object.__setattr__(incomplete, "snapshot_version", 2)
        object.__setattr__(incomplete, "source_id", SOURCE_ID)
        object.__setattr__(incomplete, "facts", _bundle(version=2).facts[:3])
        with self.assertRaisesRegex(ActorServerError, "snapshot bundle invalid"):
            self.core.publish_snapshot(self.writer, incomplete)
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 0)
        with self.assertRaisesRegex(ValueError, "version mismatch"):
            wrong_version_fact = replace(
                _bundle(version=2).facts[0], snapshot_version=3
            )
            AccountSnapshotBundleV1(
                ACCOUNT_A,
                2,
                SOURCE_ID,
                (wrong_version_fact,) + _bundle(version=2).facts[1:],
            )
        with self.assertRaisesRegex(ValueError, "source mismatch"):
            wrong_source_fact = replace(
                _bundle(version=2).facts[0], source_id="other-source"
            )
            AccountSnapshotBundleV1(
                ACCOUNT_A,
                2,
                SOURCE_ID,
                (wrong_source_fact,) + _bundle(version=2).facts[1:],
            )

    def test_missing_source_authority_blocks_snapshot_reservation_and_dispatch(self):
        core = AccountActorServerCoreV1(
            str(Path(self.temp.name) / "no-authority.sqlite3")
        )
        writer = core.claim_writer(ACCOUNT_A, "writer-no-source")
        with self.assertRaisesRegex(
            ActorServerError, "snapshot source authority unavailable"
        ):
            core.publish_snapshot(writer, _bundle())
        with self.assertRaisesRegex(
            ActorServerError, "snapshot source authority unavailable"
        ):
            core.authorize_dispatch(writer, operation="SUBMIT", intent_id="absent")
        self.assertEqual(core.count_dispatch_rows(ACCOUNT_A), 0)
        core.close()

    def test_missing_authority_at_final_gate_emits_no_outbox_row(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        reopened_without_authority = AccountActorServerCoreV1(self.database_path)
        with self.assertRaisesRegex(
            ActorServerError, "snapshot source authority unavailable"
        ):
            reopened_without_authority.authorize_dispatch(
                self.writer,
                operation="SUBMIT",
                intent_id="intent-1",
            )
        self.assertEqual(reopened_without_authority.count_dispatch_rows(ACCOUNT_A), 0)
        reopened_without_authority.close()

    def test_wrong_source_authority_and_wrong_account_cannot_publish(self):
        foreign_authority = FakeSnapshotAuthorityV1(
            authority_id=AUTHORITY_ID,
            source_id="different-source",
            key=TEST_KEY,
        )
        foreign_core = AccountActorServerCoreV1(
            str(Path(self.temp.name) / "wrong-source.sqlite3"),
            snapshot_authority=foreign_authority,
        )
        writer = foreign_core.claim_writer(ACCOUNT_A, "writer-a")
        with self.assertRaisesRegex(ActorServerError, "snapshot source untrusted"):
            foreign_core.publish_snapshot(writer, _bundle())
        with self.assertRaisesRegex(ActorServerError, "snapshot account mismatch"):
            self.core.publish_snapshot(self.writer, _bundle(account_ref=ACCOUNT_B))
        self.assertEqual(foreign_core.count_dispatch_rows(ACCOUNT_A), 0)
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 0)
        foreign_core.close()

    def test_wrong_account_and_wrong_epoch_intents_are_rejected_before_reservation(
        self,
    ):
        with self.assertRaisesRegex(ActorServerError, "intent account mismatch"):
            self.core.reserve_intent(
                self.writer,
                _intent(account_ref=ACCOUNT_B),
                expected_snapshot_version=1,
            )
        with self.assertRaisesRegex(ActorServerError, "intent actor epoch mismatch"):
            self.core.reserve_intent(
                self.writer,
                _intent(epoch=self.writer.epoch + 1),
                expected_snapshot_version=1,
            )
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 0)

    def test_session_binding_is_exact_and_immutable_within_writer_epoch(self):
        expected = _context(epoch=self.writer.epoch)
        self.core.bind_session(self.writer, expected)
        with self.assertRaisesRegex(ActorServerError, "session context already bound"):
            self.core.bind_session(
                self.writer,
                _context(epoch=self.writer.epoch, session_id="replacement-session"),
            )
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        authorized = self.core.authorize_dispatch(
            self.writer,
            operation="SUBMIT",
            intent_id="intent-1",
        )
        self.assertEqual(authorized.state, "AUTHORIZED_LOCAL_OUTBOX")
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 1)

    def test_durable_intent_deduplication_survives_reopen_and_body_conflict_rejects(
        self,
    ):
        intent = _intent()
        first = self.core.reserve_intent(
            self.writer, intent, expected_snapshot_version=1
        )
        self.core.close()
        reopened = AccountActorServerCoreV1(
            self.database_path,
            snapshot_authority=_authority(),
        )
        duplicate = reopened.reserve_intent(
            self.writer, intent, expected_snapshot_version=1
        )
        self.assertEqual(duplicate, first)
        with self.assertRaisesRegex(ActorServerError, "intent replay conflict"):
            reopened.reserve_intent(
                self.writer,
                _intent(quantity=3),
                expected_snapshot_version=1,
            )
        self.assertEqual(reopened.count_dispatch_rows(ACCOUNT_A), 0)
        reopened.close()

    def test_durable_deduplication_key_includes_operation(self):
        submit = _intent(intent_id="shared-id")
        cancel = replace(submit, operation="CANCEL")
        self.core.reserve_intent(self.writer, submit, expected_snapshot_version=1)
        self.core.reserve_intent(self.writer, cancel, expected_snapshot_version=1)
        submit_receipt = self.core.authorize_dispatch(
            self.writer,
            operation="SUBMIT",
            intent_id="shared-id",
        )
        cancel_receipt = self.core.authorize_dispatch(
            self.writer,
            operation="CANCEL",
            intent_id="shared-id",
        )
        self.assertNotEqual(submit_receipt.dispatch_id, cancel_receipt.dispatch_id)
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 2)

    def test_finalize_after_reopen_is_idempotent_and_writes_one_outbox_row(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        self.core.close()
        reopened = AccountActorServerCoreV1(
            self.database_path,
            snapshot_authority=_authority(),
        )
        first = reopened.authorize_dispatch(
            self.writer,
            operation="SUBMIT",
            intent_id="intent-1",
        )
        second = reopened.authorize_dispatch(
            self.writer,
            operation="SUBMIT",
            intent_id="intent-1",
        )
        self.assertEqual(first, second)
        self.assertEqual(reopened.count_dispatch_rows(ACCOUNT_A), 1)
        reopened.close()

    def test_new_snapshot_revokes_old_authorization_and_final_gate_rejects_it(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        old_authorization = self.core.authorize_dispatch(
            self.writer, operation="SUBMIT", intent_id="intent-1"
        )
        self.assertEqual(self.core.read_dispatch_state(ACCOUNT_A, "SUBMIT", "intent-1"),
                         "AVAILABLE")

        self.core.publish_snapshot(self.writer, _bundle(version=2))
        self.assertEqual(self.core.read_dispatch_state(ACCOUNT_A, "SUBMIT", "intent-1"),
                         "REVOKED")
        with self.assertRaisesRegex(ActorServerError, "dispatch authorization stale"):
            self.core.authorize_dispatch(
                self.writer, operation="SUBMIT", intent_id="intent-1"
            )
        with self.assertRaisesRegex(ActorServerError, "dispatch authorization not available"):
            self.core.claim_for_dispatch(self.writer, old_authorization)

        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 1)
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT state,expected_snapshot_version FROM actor_commands"
                " WHERE account_ref=? AND operation='SUBMIT' AND intent_id='intent-1'",
                (ACCOUNT_A,),
            ).fetchone()
        self.assertEqual(row, ("BLOCKED", 1))

    def test_authorized_replay_rechecks_current_snapshot_even_without_revocation_marker(
        self,
    ):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        self.core.authorize_dispatch(
            self.writer, operation="SUBMIT", intent_id="intent-1"
        )
        self.core.publish_snapshot(self.writer, _bundle(version=2))
        # Simulate a stale lifecycle marker left by an old/partial consumer.
        # The final authorization path must independently verify the pointer.
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "UPDATE actor_dispatch_lifecycle SET state='AVAILABLE'"
                " WHERE dispatch_id=1"
            )
            connection.execute(
                "UPDATE actor_commands SET state='AUTHORIZED'"
                " WHERE account_ref=? AND operation='SUBMIT' AND intent_id='intent-1'",
                (ACCOUNT_A,),
            )
            connection.commit()

        with self.assertRaisesRegex(ActorServerError, "dispatch authorization stale"):
            self.core.authorize_dispatch(
                self.writer, operation="SUBMIT", intent_id="intent-1"
            )
        self.assertEqual(self.core.read_dispatch_state(ACCOUNT_A, "SUBMIT", "intent-1"),
                         "REVOKED")
        with closing(sqlite3.connect(self.database_path)) as connection:
            state = connection.execute(
                "SELECT state FROM actor_commands WHERE account_ref=? AND operation='SUBMIT'"
                " AND intent_id='intent-1'",
                (ACCOUNT_A,),
            ).fetchone()[0]
        self.assertEqual(state, "BLOCKED")
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 1)

    def test_stale_authorization_is_rejected_after_cross_process_reopen(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        old_authorization = self.core.authorize_dispatch(
            self.writer, operation="SUBMIT", intent_id="intent-1"
        )
        self.core.publish_snapshot(self.writer, _bundle(version=2))
        self.core.close()

        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        process = context.Process(
            target=_claim_dispatch_process,
            args=(self.database_path, self.writer, old_authorization, child),
        )
        process.start()
        child.close()
        self.assertTrue(parent.poll(15))
        result = parent.recv()
        process.join(15)
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(
            result,
            ("rejected", "dispatch_authorization_not_available", 1, "REVOKED"),
        )
        parent.close()

        reopened = AccountActorServerCoreV1(
            self.database_path, snapshot_authority=_authority()
        )
        with self.assertRaisesRegex(ActorServerError, "dispatch authorization stale"):
            reopened.authorize_dispatch(
                self.writer, operation="SUBMIT", intent_id="intent-1"
            )
        with self.assertRaisesRegex(ActorServerError, "intent replay conflict"):
            reopened.reserve_intent(
                self.writer, _intent(), expected_snapshot_version=2
            )
        self.assertEqual(reopened.count_dispatch_rows(ACCOUNT_A), 1)
        self.assertEqual(
            reopened.read_dispatch_state(ACCOUNT_A, "SUBMIT", "intent-1"),
            "REVOKED",
        )
        reopened.close()

    def test_final_claim_is_single_use_and_freezes_snapshot_and_writer(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        authorization = self.core.authorize_dispatch(
            self.writer, operation="SUBMIT", intent_id="intent-1"
        )
        claim = self.core.claim_for_dispatch(self.writer, authorization)
        self.assertEqual(claim.state, "CLAIMED_LOCAL_ONLY")
        self.assertEqual(self.core.read_dispatch_state(ACCOUNT_A, "SUBMIT", "intent-1"),
                         "CLAIMED")
        with self.assertRaisesRegex(ActorServerError, "dispatch authorization not available"):
            self.core.claim_for_dispatch(self.writer, authorization)
        with self.assertRaisesRegex(ActorServerError, "dispatch claim in flight"):
            self.core.publish_snapshot(self.writer, _bundle(version=2))
        with self.assertRaisesRegex(ActorServerError, "dispatch claim in flight"):
            self.core.revoke_writer(self.writer)
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 1)
        self.assertEqual(self.core.read_dispatch_state(ACCOUNT_A, "SUBMIT", "intent-1"),
                         "CLAIMED")

    def test_claimed_dispatch_remains_fenced_after_process_crash_and_reopen(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        authorization = self.core.authorize_dispatch(
            self.writer, operation="SUBMIT", intent_id="intent-1"
        )
        self.core.close()

        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        process = context.Process(
            target=_claim_and_crash_process,
            args=(self.database_path, self.writer, authorization, child),
        )
        process.start()
        child.close()
        self.assertTrue(parent.poll(15))
        self.assertEqual(parent.recv(), ("claimed", "CLAIMED_LOCAL_ONLY"))
        process.join(15)
        self.assertEqual(process.exitcode, 0)
        parent.close()

        reopened = AccountActorServerCoreV1(
            self.database_path, snapshot_authority=_authority()
        )
        self.assertEqual(
            reopened.read_dispatch_state(ACCOUNT_A, "SUBMIT", "intent-1"),
            "CLAIMED",
        )
        with self.assertRaisesRegex(ActorServerError, "dispatch authorization not available"):
            reopened.claim_for_dispatch(self.writer, authorization)
        with self.assertRaisesRegex(ActorServerError, "dispatch claim in flight"):
            reopened.publish_snapshot(self.writer, _bundle(version=2))
        with self.assertRaisesRegex(ActorServerError, "dispatch claim in flight"):
            reopened.revoke_writer(self.writer)
        self.assertEqual(reopened.count_dispatch_rows(ACCOUNT_A), 1)
        reopened.close()

    def test_v1_authorized_outbox_migrates_to_revoked_audit_only(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        old_authorization = self.core.authorize_dispatch(
            self.writer, operation="SUBMIT", intent_id="intent-1"
        )
        self.core.close()
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("DROP TABLE actor_dispatch_lifecycle")
            connection.execute("PRAGMA user_version=1")
            connection.commit()

        reopened = AccountActorServerCoreV1(
            self.database_path, snapshot_authority=_authority()
        )
        with closing(sqlite3.connect(self.database_path)) as connection:
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            command_state = connection.execute(
                "SELECT state FROM actor_commands WHERE account_ref=? AND operation='SUBMIT'"
                " AND intent_id='intent-1'",
                (ACCOUNT_A,),
            ).fetchone()[0]
        self.assertEqual(schema_version, 2)
        self.assertEqual(command_state, "BLOCKED")
        self.assertEqual(
            reopened.read_dispatch_state(ACCOUNT_A, "SUBMIT", "intent-1"),
            "REVOKED",
        )
        with self.assertRaisesRegex(ActorServerError, "dispatch authorization not available"):
            reopened.claim_for_dispatch(self.writer, old_authorization)
        with self.assertRaisesRegex(ActorServerError, "dispatch authorization stale"):
            reopened.authorize_dispatch(
                self.writer, operation="SUBMIT", intent_id="intent-1"
            )
        self.assertEqual(reopened.count_dispatch_rows(ACCOUNT_A), 1)
        reopened.close()

    def test_new_snapshot_between_reservation_and_final_gate_blocks_dispatch(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        self.core.publish_snapshot(self.writer, _bundle(version=2))
        with self.assertRaisesRegex(ActorServerError, "snapshot not current"):
            self.core.authorize_dispatch(
                self.writer,
                operation="SUBMIT",
                intent_id="intent-1",
            )
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 0)

    def test_changed_domain_bytes_fail_source_proof_at_final_dispatch_gate(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "UPDATE actor_snapshot_domains SET payload_json=?"
                " WHERE account_ref=? AND snapshot_version=1 AND domain='funds'",
                ('{"available":"999999.00","currency":"CNY"}', ACCOUNT_A),
            )
            connection.commit()
        with self.assertRaisesRegex(
            ActorServerError, "snapshot digest readback mismatch"
        ):
            self.core.authorize_dispatch(
                self.writer,
                operation="SUBMIT",
                intent_id="intent-1",
            )
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 0)

    def test_malformed_existing_schema_rejects_without_repair(self):
        other_path = str(Path(self.temp.name) / "schema-shape.sqlite3")
        fresh = AccountActorServerCoreV1(other_path)
        fresh.close()
        with closing(sqlite3.connect(other_path)) as connection:
            connection.execute("DROP TABLE actor_account_writers")
            connection.execute(
                "CREATE TABLE actor_account_writers("
                "account_ref TEXT, epoch INTEGER, owner_id TEXT, token_sha256 TEXT, state TEXT)"
            )
            connection.commit()
        with self.assertRaisesRegex(ActorServerError, "database schema shape invalid"):
            AccountActorServerCoreV1(other_path)
        with closing(sqlite3.connect(other_path)) as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='actor_account_writers'"
            ).fetchone()[0]
        self.assertEqual(row[0], 2)
        self.assertIn("epoch INTEGER", sql)
        self.assertNotIn("PRIMARY KEY", sql)

    def test_revoked_epoch_cannot_dispatch_and_reclaim_increments_generation(self):
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        self.core.revoke_writer(self.writer)
        new_writer = self.core.claim_writer(ACCOUNT_A, "writer-b")
        self.assertEqual(new_writer.epoch, self.writer.epoch + 1)
        self.core.bind_session(
            new_writer, _context(epoch=new_writer.epoch, session_id="session-2")
        )
        with self.assertRaisesRegex(
            ActorServerError, "writer epoch inactive|writer epoch mismatch"
        ):
            self.core.authorize_dispatch(
                self.writer,
                operation="SUBMIT",
                intent_id="intent-1",
            )
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 0)
        with self.assertRaisesRegex(ActorServerError, "command writer epoch mismatch"):
            self.core.authorize_dispatch(
                new_writer,
                operation="SUBMIT",
                intent_id="intent-1",
            )
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 0)

    def test_snapshot_context_session_and_generation_are_digest_bound(self):
        wrong_session = _intent(session_id="different-session")
        self.core.reserve_intent(self.writer, _intent(), expected_snapshot_version=1)
        with self.assertRaisesRegex(
            ActorServerError, "intent session binding mismatch"
        ):
            self.core.reserve_intent(
                self.writer, wrong_session, expected_snapshot_version=1
            )
        self.assertEqual(self.core.count_dispatch_rows(ACCOUNT_A), 0)

    def test_two_processes_racing_for_one_account_epoch_have_one_winner(self):
        race_path = str(Path(self.temp.name) / "claim-race.sqlite3")
        empty_core = AccountActorServerCoreV1(race_path)
        empty_core.close()
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        endpoints = [context.Pipe(duplex=False) for _ in range(2)]
        processes = [
            context.Process(
                target=_claim_process,
                args=(
                    race_path,
                    ACCOUNT_B,
                    barrier,
                    endpoints[index][1],
                    f"writer-{index}",
                ),
            )
            for index in range(2)
        ]
        for process in processes:
            process.start()
        for _, child in endpoints:
            child.close()
        results = [parent.recv() for parent, _ in endpoints]
        for process in processes:
            process.join(15)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sum(result[0] == "claimed" for result in results), 1)
        self.assertEqual(sum(result[0] == "rejected" for result in results), 1)
        winner = next(result for result in results if result[0] == "claimed")
        race_core = AccountActorServerCoreV1(race_path)
        self.assertEqual(race_core.read_writer_epoch(ACCOUNT_B)[0], winner[1])
        race_core.close()

    def test_process_death_leaves_writer_claim_durable_and_unreclaimable(self):
        other_path = str(Path(self.temp.name) / "crash.sqlite3")
        core = AccountActorServerCoreV1(other_path)
        core.close()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        process = context.Process(
            target=_crash_after_claim_process,
            args=(other_path, child),
        )
        process.start()
        child.close()
        result = parent.recv()
        process.join(15)
        parent.close()
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(result, ("claimed", 1))
        reopened = AccountActorServerCoreV1(other_path)
        self.assertEqual(
            reopened.read_writer_epoch(ACCOUNT_A), (1, "crashed-owner", "ACTIVE")
        )
        with self.assertRaisesRegex(ActorServerError, "account writer already claimed"):
            reopened.claim_writer(ACCOUNT_A, "new-process")
        self.assertEqual(reopened.count_dispatch_rows(ACCOUNT_A), 0)
        reopened.close()


if __name__ == "__main__":
    unittest.main()
