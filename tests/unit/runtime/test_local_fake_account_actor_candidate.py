from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path

from backtrader_runtime._local_fake_account_actor_candidate.account_actor_port import (
    AccountActorGateError,
    ActorCommandState,
    CtpSubmitIntentV2,
)
from backtrader_runtime._local_fake_account_actor_candidate.fake_actor_client import (
    SubprocessFakeActorPort,
    _BoundedResponseMailbox,
)


class SubprocessActorWireContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="actor-wire-r1-")
        self.port = self._new_port("service.sqlite3")

    def tearDown(self):
        try:
            self.port.close()
        except AccountActorGateError as exc:
            if exc.code != "actor_service_cleanup_uncertain":
                raise
        self.temp.cleanup()

    def _new_port(
        self,
        db_name,
        response_timeout_seconds=2.0,
        request_timeout_seconds=2.0,
        response_queue_max_lines=16,
        response_queue_max_bytes=512 * 1024,
    ):
        return SubprocessFakeActorPort(
            str(Path(self.temp.name) / db_name),
            response_timeout_seconds=response_timeout_seconds,
            request_timeout_seconds=request_timeout_seconds,
            response_queue_max_lines=response_queue_max_lines,
            response_queue_max_bytes=response_queue_max_bytes,
        )

    def _intent(self, context, intent_id):
        return CtpSubmitIntentV2(
            intent_id=intent_id,
            instrument_id="IF2612",
            exchange_id="CFFEX",
            side="BUY",
            offset="OPEN",
            hedge_flag="SPECULATION",
            quantity=1,
            limit_price=Decimal("3500.0"),
            context=context,
        )

    def _assert_all_pipe_handles_closed(self, port):
        process = port._process
        self.assertIsNotNone(process.stdin)
        self.assertIsNotNone(process.stdout)
        self.assertIsNotNone(process.stderr)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)
        self.assertFalse(port._stdout_reader.is_alive())
        self.assertFalse(port._stderr_reader.is_alive())

    def test_stale_epoch_rejects_before_fake_send_then_exact_current_receipt(self):
        self.assertNotEqual(self.port._process.pid, os.getpid())
        boundary = self.port.test_inspect_import_boundary()
        self.assertFalse(boundary["runtime_root_loaded"])
        self.assertFalse(boundary["provider_loaded"])

        stale = self._intent(self.port.test_stale_context, "stale-intent-1")
        with self.assertRaises(AccountActorGateError) as caught:
            self.port.submit_order(stale)
        self.assertEqual(caught.exception.code, "actor_service_stale_epoch")

        inspection = self.port.test_inspect_fake_sink()
        self.assertEqual(inspection["kind"], "test_inspection")
        self.assertEqual(inspection["send_count"], 0)
        self.assertEqual(inspection["sends"], [])

        current = self._intent(self.port.test_current_context, "current-intent-1")
        receipt = self.port.submit_order(current)
        self.assertEqual(receipt.operation, "SUBMIT")
        self.assertEqual(receipt.command_id, current.intent_id)
        self.assertEqual(receipt.context, current.context)
        self.assertEqual(receipt.command_digest, current.command_digest)
        self.assertIs(receipt.state, ActorCommandState.QUEUED)

        details = self.port.test_last_wire_receipt
        self.assertIsNotNone(details)
        self.assertEqual(details.writer_epoch, current.context.actor_epoch)
        self.assertEqual(details.snapshot_version, self.port.test_snapshot_version)
        self.assertEqual(details.dispatch_id, 1)
        self.assertEqual(details.fake_send_id, "fake-send-1")
        self.assertIs(details.provider_acknowledged, False)
        self.assertRegex(details.durable_command_digest, r"^[0-9a-f]{64}$")

        inspection = self.port.test_inspect_fake_sink()
        self.assertEqual(inspection["send_count"], 1)
        self.assertEqual(len(inspection["sends"]), 1)
        sent = inspection["sends"][0]
        self.assertEqual(sent["fake_send_id"], details.fake_send_id)
        self.assertEqual(sent["intent_id"], current.intent_id)
        self.assertEqual(sent["client_command_digest"], current.command_digest)
        self.assertEqual(sent["durable_command_digest"], details.durable_command_digest)
        self.assertEqual(sent["dispatch_id"], details.dispatch_id)
        self.assertEqual(sent["payload"]["instrument_id"], current.instrument_id)
        self.assertEqual(sent["payload"]["limit_price"], "3500.0")

    def test_abrupt_child_exit_reports_unavailable_and_closes_all_pipes(self):
        with self.assertRaises(AccountActorGateError) as caught:
            self.port.test_crash_service()
        self.assertEqual(caught.exception.code, "actor_service_unavailable")
        self.assertEqual(self.port._process.poll(), 7)
        self._assert_all_pipe_handles_closed(self.port)

    def test_stalled_response_times_out_and_terminates_child(self):
        # Keep startup on the normal bound, then shorten only the test response
        # wait so READY initialization stays independent of host load.
        self.port._response_timeout_seconds = 0.2

        started = time.monotonic()
        with self.assertRaises(AccountActorGateError) as caught:
            self.port.test_stall_output()
        elapsed = time.monotonic() - started

        self.assertEqual(caught.exception.code, "actor_service_cleanup_uncertain")
        self.assertLess(elapsed, 2.0)
        self.assertIsNotNone(self.port._process.poll())
        self._assert_all_pipe_handles_closed(self.port)


    def test_large_stderr_burst_is_drained_while_response_is_read(self):
        byte_count = 1024 * 1024
        response = self.port.test_stderr_burst(byte_count)

        self.assertEqual(response["kind"], "test_stderr_burst_complete")
        self.assertEqual(response["byte_count"], byte_count)
        deadline = time.monotonic() + 1.0
        while self.port.test_stderr_bytes_drained < byte_count and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.port.test_stderr_bytes_drained, byte_count)
        self.assertEqual(len(self.port.test_stderr_tail), 8 * 1024)

    def test_response_mailbox_enforces_line_and_byte_bounds(self):
        line_bounded = _BoundedResponseMailbox(max_lines=2, max_bytes=100)
        self.assertTrue(line_bounded.publish_line(b"a"))
        self.assertTrue(line_bounded.publish_line(b"b"))
        self.assertFalse(line_bounded.publish_line(b"c"))
        self.assertLessEqual(len(line_bounded._lines), 2)
        self.assertLessEqual(line_bounded._queued_bytes, 100)
        self.assertEqual(line_bounded.get(0.1), ("overflow", None))

        byte_bounded = _BoundedResponseMailbox(max_lines=8, max_bytes=3)
        self.assertTrue(byte_bounded.publish_line(b"ab"))
        self.assertFalse(byte_bounded.publish_line(b"cd"))
        self.assertLessEqual(len(byte_bounded._lines), 8)
        self.assertLessEqual(byte_bounded._queued_bytes, 3)
        self.assertEqual(byte_bounded.get(0.1), ("overflow", None))

    def test_response_byte_limit_fails_closed_on_child_payload(self):
        self.port.close()
        self.port = self._new_port(
            "response-queue.sqlite3",
            response_queue_max_bytes=4096,
        )

        with self.assertRaises(AccountActorGateError) as caught:
            self.port.test_response_queue_payload(8192)

        self.assertEqual(caught.exception.code, "actor_service_response_queue_overflow")
        self._assert_all_pipe_handles_closed(self.port)

    def test_oversized_request_rejects_before_pipe_write(self):
        with self.assertRaises(AccountActorGateError) as caught:
            self.port._exchange(
                {
                    "schema": "account-actor-wire.v1",
                    "kind": "test_oversized_request",
                    "padding": "x" * (64 * 1024),
                }
            )

        self.assertEqual(caught.exception.code, "actor_service_request_too_large")
        self.assertEqual(self.port.test_inspect_fake_sink()["send_count"], 0)

    def test_blocked_request_write_times_out_and_reports_cleanup_uncertain(self):
        class BlockingStdin:
            def __init__(self, wrapped):
                self._wrapped = wrapped
                self._release = threading.Event()

            @property
            def closed(self):
                return self._wrapped.closed

            def write(self, _data):
                self._release.wait()
                raise BrokenPipeError

            def flush(self):
                return None

            def close(self):
                self._release.set()
                self._wrapped.close()

        self.port._request_timeout_seconds = 0.2
        self.port._process.stdin = BlockingStdin(self.port._process.stdin)
        started = time.monotonic()

        with self.assertRaises(AccountActorGateError) as caught:
            self.port.test_inspect_fake_sink()

        elapsed = time.monotonic() - started
        self.assertEqual(caught.exception.code, "actor_service_cleanup_uncertain")
        self.assertLess(elapsed, 2.0)
        self.assertIsNotNone(self.port._process.poll())
        self._assert_all_pipe_handles_closed(self.port)


class DefaultRuntimeIsolationTests(unittest.TestCase):
    def test_package_import_and_default_registry_do_not_load_candidate(self):
        root = Path(__file__).resolve().parents[3]
        candidate_name = "_local_fake_account_actor_candidate"
        guarded = (
            root / "backtrader_runtime" / "__init__.py",
            root / "backtrader_runtime" / "inventory.py",
            root / "backtrader_runtime" / "registry.py",
            root / "backtrader_runtime" / "cli.py",
            root / "backtrader" / "stores" / "btapistore.py",
        )
        for path in guarded:
            self.assertNotIn(candidate_name, path.read_text(encoding="utf-8"))

        script = (
            "import json, sys; "
            "import backtrader_runtime; "
            "from backtrader_runtime.inventory import iteration41_runtime_registry; "
            "registry = iteration41_runtime_registry(); "
            "print(json.dumps({'ids': [r.runtime_id for r in registry.registrations], "
            "'loaded': any(name.startswith('backtrader_runtime."
            "_local_fake_account_actor_candidate') for name in sys.modules)}))"
        )
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        observation = json.loads(result.stdout.strip())
        self.assertFalse(observation["loaded"])
        self.assertFalse(
            any("local_fake_account_actor" in runtime_id for runtime_id in observation["ids"])
        )


if __name__ == "__main__":
    unittest.main()
