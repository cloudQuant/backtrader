from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

if __package__:
    from .account_actor_port import ActorCommandContextV1, CtpSubmitIntentV2
    from .account_actor_server_core import (
        AccountActorIntentV1,
        AccountActorServerCoreV1,
        AccountSnapshotBundleV1,
        ActorServerError,
        FakeSnapshotAuthorityV1,
        SnapshotDomainFactV1,
    )
else:  # Imported by the fake service when it is run directly as a script.
    from account_actor_port import ActorCommandContextV1, CtpSubmitIntentV2
    from account_actor_server_core import (
        AccountActorIntentV1,
        AccountActorServerCoreV1,
        AccountSnapshotBundleV1,
        ActorServerError,
        FakeSnapshotAuthorityV1,
        SnapshotDomainFactV1,
    )

_SCHEMA = "account-actor-wire.v1"
_ACCOUNT_REF = "ctp-account-ref.v1:" + hashlib.sha256(b"wire-r0-fake-account").hexdigest()
_AUTHORITY = FakeSnapshotAuthorityV1(
    authority_id="wire-r0-test-only",
    source_id="wire-r0-test-source",
    key=b"wire-r0-test-only-key-not-a-credential-0123456789",
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _context(epoch, session_id):
    return ActorCommandContextV1(
        account_ref=_ACCOUNT_REF,
        runtime_id="wire-r0-runtime",
        mode="simulation",
        config_digest=hashlib.sha256(b"wire-r0-config").hexdigest(),
        session_id=session_id,
        front_id=10 + epoch,
        native_session_id=20 + epoch,
        session_generation=epoch,
        actor_epoch=epoch,
    )


def _snapshot(version):
    payloads = {
        "funds": {"available": "100000.00", "currency": "CNY"},
        "orders": {"open_order_count": 0},
        "trades": {"trade_count": 0},
        "positions": {"position_count": 0},
    }
    facts = tuple(
        SnapshotDomainFactV1.from_payload(
            account_ref=_ACCOUNT_REF,
            snapshot_version=version,
            source_id="wire-r0-test-source",
            domain=domain,
            payload=payloads[domain],
        )
        for domain in ("funds", "orders", "trades", "positions")
    )
    return AccountSnapshotBundleV1(_ACCOUNT_REF, version, "wire-r0-test-source", facts)


def _read_request(line):
    def no_duplicate_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    value = json.loads(line, object_pairs_hook=no_duplicate_pairs)
    if type(value) is not dict or value.get("schema") != _SCHEMA:
        raise ValueError("wire schema invalid")
    return value


def _submit(core, writer, request, snapshot_version, fake_sink):
    wire_intent = request.get("intent")
    if type(wire_intent) is not dict:
        raise ValueError("typed intent payload required")
    expected_keys = {
        "intent_id",
        "instrument_id",
        "exchange_id",
        "side",
        "offset",
        "hedge_flag",
        "quantity",
        "limit_price",
        "context",
        "command_digest",
    }
    if set(wire_intent) != expected_keys:
        raise ValueError("intent fields invalid")
    context_data = wire_intent["context"]
    if type(context_data) is not dict:
        raise ValueError("context payload invalid")
    context = ActorCommandContextV1(**context_data)
    intent = CtpSubmitIntentV2(
        intent_id=wire_intent["intent_id"],
        instrument_id=wire_intent["instrument_id"],
        exchange_id=wire_intent["exchange_id"],
        side=wire_intent["side"],
        offset=wire_intent["offset"],
        hedge_flag=wire_intent["hedge_flag"],
        quantity=wire_intent["quantity"],
        limit_price=Decimal(wire_intent["limit_price"]),
        context=context,
    )
    intent.__post_init__()
    if wire_intent["command_digest"] != intent.command_digest:
        raise ValueError("intent digest mismatch")

    payload = {
        "instrument_id": intent.instrument_id,
        "exchange_id": intent.exchange_id,
        "side": intent.side,
        "offset": intent.offset,
        "hedge_flag": intent.hedge_flag,
        "quantity": intent.quantity,
        "limit_price": format(intent.limit_price, "f"),
    }
    durable_intent = AccountActorIntentV1.from_payload(
        operation="SUBMIT",
        intent_id=intent.intent_id,
        context=intent.context,
        payload=payload,
    )
    core.reserve_intent(
        writer,
        durable_intent,
        expected_snapshot_version=snapshot_version,
    )
    authorization = core.authorize_dispatch(
        writer,
        operation="SUBMIT",
        intent_id=intent.intent_id,
    )
    claim = core.claim_for_dispatch(writer, authorization)

    # This sink exists only inside the child process and stands in for a native send.
    fake_send_id = f"fake-send-{len(fake_sink) + 1}"
    fake_sink.append(
        {
            "fake_send_id": fake_send_id,
            "intent_id": intent.intent_id,
            "client_command_digest": intent.command_digest,
            "durable_command_digest": claim.command_digest,
            "dispatch_id": claim.dispatch_id,
            "payload": payload,
        }
    )
    return {
        "schema": _SCHEMA,
        "kind": "receipt",
        "receipt": {
            "operation": "SUBMIT",
            "command_id": intent.intent_id,
            "state": "QUEUED",
            "context": context.to_payload(),
            "command_digest": intent.command_digest,
            "writer_epoch": claim.writer_epoch,
            "snapshot_version": claim.snapshot_version,
            "dispatch_id": claim.dispatch_id,
            "durable_command_digest": claim.command_digest,
            "fake_send_id": fake_send_id,
            "provider_acknowledged": False,
        },
    }


def main():
    database_path = str(Path(sys.argv[1]).resolve())
    core = AccountActorServerCoreV1(database_path, snapshot_authority=_AUTHORITY)

    # Simulate a service-owned revoke and takeover before exposing its current session.
    stale_writer = core.claim_writer(_ACCOUNT_REF, "wire-r0-owner-old")
    stale_context = _context(stale_writer.epoch, "wire-r0-session-old")
    core.bind_session(stale_writer, stale_context)
    core.revoke_writer(stale_writer)

    writer = core.claim_writer(_ACCOUNT_REF, "wire-r0-owner-current")
    current_context = _context(writer.epoch, "wire-r0-session-current")
    core.bind_session(writer, current_context)
    snapshot_version = 2
    core.publish_snapshot(writer, _snapshot(snapshot_version))
    fake_sink = []

    ready = {
        "schema": _SCHEMA,
        "kind": "ready",
        "stale_context": stale_context.to_payload(),
        "current_context": current_context.to_payload(),
        "snapshot_version": snapshot_version,
    }
    sys.stdout.write(_canonical(ready) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        try:
            request = _read_request(line)
            if request.get("kind") == "submit":
                response = _submit(core, writer, request, snapshot_version, fake_sink)
            elif request.get("kind") == "test_inspect_fake_sink":
                response = {
                    "schema": _SCHEMA,
                    "kind": "test_inspection",
                    "send_count": len(fake_sink),
                    "sends": fake_sink,
                }
            elif request.get("kind") == "test_import_boundary":
                response = {
                    "schema": _SCHEMA,
                    "kind": "test_import_boundary",
                    "runtime_root_loaded": "backtrader_runtime" in sys.modules,
                    "provider_loaded": any(
                        name.startswith(("bt_api_", "_ctp.")) or name == "_ctp"
                        for name in sys.modules
                    ),
                }
            elif request.get("kind") == "test_abrupt_exit":
                os._exit(7)
            elif request.get("kind") == "test_stall_output":
                time.sleep(10)
                continue
            elif request.get("kind") == "test_stderr_burst":
                byte_count = request.get("byte_count")
                if type(byte_count) is not int or not 65536 <= byte_count <= 4 * 1024 * 1024:
                    response = {
                        "schema": _SCHEMA,
                        "kind": "rejected",
                        "reason": "test_byte_count_invalid",
                    }
                else:
                    block = b"x" * 65536
                    for _ in range(byte_count // len(block)):
                        sys.stderr.buffer.write(block)
                    remainder = byte_count % len(block)
                    if remainder:
                        sys.stderr.buffer.write(b"x" * remainder)
                    sys.stderr.flush()
                    response = {
                        "schema": _SCHEMA,
                        "kind": "test_stderr_burst_complete",
                        "byte_count": byte_count,
                    }
            elif request.get("kind") == "test_response_queue_payload":
                byte_count = request.get("byte_count")
                if type(byte_count) is not int or not 1 <= byte_count <= 48 * 1024:
                    response = {
                        "schema": _SCHEMA,
                        "kind": "rejected",
                        "reason": "test_byte_count_invalid",
                    }
                else:
                    response = {
                        "schema": _SCHEMA,
                        "kind": "test_response_queue_payload",
                        "padding": "x" * byte_count,
                    }
            else:
                response = {
                    "schema": _SCHEMA,
                    "kind": "rejected",
                    "reason": "wire_operation_unsupported",
                }
        except ActorServerError as exc:
            response = {
                "schema": _SCHEMA,
                "kind": "rejected",
                "reason": exc.code,
            }
        except (KeyError, TypeError, ValueError, ArithmeticError):
            response = {
                "schema": _SCHEMA,
                "kind": "rejected",
                "reason": "wire_intent_invalid",
            }
        sys.stdout.write(_canonical(response) + "\n")
        sys.stdout.flush()

    core.close()


if __name__ == "__main__":
    main()
