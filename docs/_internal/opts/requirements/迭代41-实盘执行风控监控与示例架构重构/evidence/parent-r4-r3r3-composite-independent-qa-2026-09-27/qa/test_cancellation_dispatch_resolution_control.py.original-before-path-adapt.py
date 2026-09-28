"""Fake-only composition tests for the two-latch cancellation release path."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_EXECUTION_SRC = Path(r"D:\temp\iteration41_v20_r3_cancel_terminal_candidate_20260927\src")
_RISK_SRC = Path(r"D:\temp\iteration41_risk_cancel_resolution_20260927\src")
_BASE_SRC = Path(r"D:\temp\bt_api_i9_store_broker_src_20260926\bt_api_base\src")
_MONITOR_SRC = Path(r"D:\temp\bt_api_i9_store_broker_src_20260926\bt_api_monitor\src")
for _source in (_ROOT, _EXECUTION_SRC, _RISK_SRC, _BASE_SRC, _MONITOR_SRC):
    sys.path.insert(0, str(_source))

import bt_api_execution as execution  # noqa: E402
import bt_api_monitor as monitor  # noqa: E402
import bt_api_risk as risk  # noqa: E402

from bt_api_py.runtime_plugins.cancellation_control import (  # noqa: E402
    CancellationReconciliationEvidence,
    ManagedCancellationReconciliationControlPort,
    ReleaseCancellationFreezeCommand,
)
from bt_api_py.runtime_plugins.catalog import (  # noqa: E402
    LoadedCapabilities,
    RuntimePluginError,
)
from bt_api_py.runtime_plugins import cancellation_control as cancellation_control_module  # noqa: E402
from bt_api_py.runtime_plugins.contracts import (  # noqa: E402
    CAPABILITY_EXECUTION,
    CAPABILITY_MONITOR,
    CAPABILITY_RISK,
    RuntimeCapabilityContract,
)
from bt_api_py.runtime_plugins.managed import compose_managed_execution  # noqa: E402
from bt_api_py.runtime_plugins.reconcile_control import AuthorizationDecision  # noqa: E402

assert (
    Path(execution.__file__).resolve()
    == (_EXECUTION_SRC / "bt_api_execution" / "__init__.py").resolve()
)
assert Path(risk.__file__).resolve() == (_RISK_SRC / "bt_api_risk" / "__init__.py").resolve()
assert (
    Path(monitor.__file__).resolve() == (_MONITOR_SRC / "bt_api_monitor" / "__init__.py").resolve()
)
assert (
    Path(sys.modules["bt_api_py.runtime_plugins.fake_dispatch_authority"].__file__).resolve()
    == (_ROOT / "bt_api_py" / "runtime_plugins" / "fake_dispatch_authority.py").resolve()
)

_STRATEGY = "example.013_3.sa_midfreq_simnow"
_PROVIDER = "iteration41_managed_replay_fake_provider"
_ACCOUNT = "iteration41_managed_replay_fake_account"
_POLICY = "iteration41.managed_replay.l2"


class _RiskCancelAdmission:
    """Map one execution cancel onto the exact risk claim the issuer expects."""

    def __init__(self, gate: Any, scope: Any, execution_scope: Any) -> None:
        self._gate = gate
        self._scope = scope
        self._execution_scope = execution_scope
        self._intents: dict[str, Any] = {}

    def _intent(self, cancel: Any) -> Any:
        return risk.RiskIntent(
            intent_id=f"cancel-admission:{self._execution_scope.key}:{cancel.cancel_id}",
            scope=self._scope,
            action=risk.IntentAction.CANCEL,
            notional=Decimal("0"),
            payload_fingerprint=cancel.fingerprint,
        )

    def reserve(self, cancel: Any) -> Any:
        intent = self._intent(cancel)
        permit = self._gate.reserve(intent)
        self._intents[permit.permit_id] = intent
        return permit

    def validate(self, permit_id: str, cancel: Any) -> Any:
        return self._gate.validate_permit(permit_id, self._intents[permit_id])

    def claim_before_dispatch(self, permit_id: str, cancel: Any) -> Any:
        self._gate.claim_for_dispatch(permit_id, self._intents[permit_id])
        return execution.CancelDispatchClaimReceiptV1(
            permit_reference=permit_id,
            scope_key=cancel.scope.key,
            cancel_id=cancel.cancel_id,
            intent_fingerprint=cancel.fingerprint,
        )

    def settle(self, permit_id: str) -> Any:
        return self._gate.settle(permit_id)

    def release(self, permit_id: str, reason: str) -> None:
        self._gate.release(permit_id, reason)


class _Fixture:
    def __init__(self, root: Path) -> None:
        contract = RuntimeCapabilityContract(
            strategy_id=_STRATEGY,
            mode="simulation",
            preset="replay",
            environment="offline",
            order_route="managed_execution",
            required_capabilities=(CAPABILITY_EXECUTION, CAPABILITY_RISK, CAPABILITY_MONITOR),
            effective_digest="b" * 64,
        )
        capabilities = LoadedCapabilities(
            contract=contract,
            modules={
                CAPABILITY_EXECUTION: execution,
                CAPABILITY_RISK: risk,
                CAPABILITY_MONITOR: monitor,
            },
        )
        self.runtime = compose_managed_execution(
            capabilities,
            state_directory=root / "state",
            provider=_PROVIDER,
            environment="offline",
            account_ref=_ACCOUNT,
            strategy_id=_STRATEGY,
            writer_id="fake-cancel-control-test-writer",
            policy_id=_POLICY,
            max_increase_notional=Decimal("10000"),
            max_increase_count=20,
        )
        order = execution.OrderIntent.limit(
            intent_id="cancel-control-target",
            scope=self.runtime.scope,
            signal_id="fixture-signal",
            instrument="IF2609",
            side=execution.Side.BUY,
            quantity=Decimal("2"),
            price=Decimal("6"),
            metadata_version="fixture-metadata-v1",
            tags={"instrument_metadata_digest": "a" * 64},
        )
        self.order_record = self.runtime.submit(
            order,
            lambda current: execution.ProviderObservation.accepted(
                current.intent_id, "fake-provider-order-17"
            ),
        )
        self.cancel = execution.CancelIntent(
            cancel_id="cancel-control-1",
            scope=self.runtime.scope,
            target_intent_id=order.intent_id,
            provider_order_id=self.order_record.provider_order_id,
            metadata_version="fixture-metadata-v1",
        )
        self.cancel_facade = execution.ManagedCancellationFacade(
            self.runtime.execution_store,
            self.runtime.scope,
            acquire_writer_lease=self.runtime.facade.acquire_writer_lease,
            admission_gate=_RiskCancelAdmission(
                self.runtime.risk_gate, self.runtime.risk_scope, self.runtime.scope
            ),
        )

        def uncertain(_cancel: Any) -> Any:
            raise RuntimeError("synthetic ambiguous fake cancellation")

        unknown_record = self.cancel_facade.cancel(self.cancel, uncertain)
        assert unknown_record.state is execution.ExecutionState.UNKNOWN
        self.unknown_cause = (
            "cancel-outcome-unknown:" + self.runtime.scope.key + ":" + self.cancel.cancel_id
        )
        self.progress_cause = (
            "cancel-release-in-progress:" + self.runtime.scope.key + ":" + self.cancel.cancel_id
        )
        self.runtime.risk_gate.freeze(
            self.runtime.risk_scope, self.unknown_cause, self.unknown_cause
        )
        self.now = time.time()
        self.control = self.new_control(root / "control")
        self.evidence = CancellationReconciliationEvidence(
            evidence_id="cancel-control-evidence-1",
            cancel_id=self.cancel.cancel_id,
            target_intent_id=self.cancel.target_intent_id,
            provider_order_id=self.cancel.provider_order_id,
            observation=execution.CancelObservation.cancelled(
                self.cancel.cancel_id,
                self.cancel.target_intent_id,
                self.cancel.provider_order_id,
            ),
            source_receipt_digest="c" * 64,
            observed_at=self.now,
        )
        self.control.reconcile(self.evidence)
        self.command = ReleaseCancellationFreezeCommand(
            command_id="cancel-control-release-1",
            scope=self.runtime.scope.key,
            cancel_id=self.cancel.cancel_id,
            evidence_id=self.evidence.evidence_id,
            evidence_fingerprint=self.evidence.fingerprint,
            issuer_id="offline-operator",
            reason_code="reviewed_cancel_terminal",
            issued_at=self.now,
            expires_at=self.now + 3600,
        )

    def new_control(self, state: Path) -> ManagedCancellationReconciliationControlPort:
        return ManagedCancellationReconciliationControlPort(
            self.runtime,
            self.cancel_facade,
            state_directory=state,
            authorize=lambda request: AuthorizationDecision(
                True, request.command.issuer_id, "d" * 64, "approved"
            ),
            clock=lambda: self.now,
        )

    def close(self) -> None:
        self.control.close()
        self.runtime.close()

    def active(self) -> set[str]:
        return set(self.runtime.risk_gate.active_freeze_reasons(self.runtime.risk_scope))

    def new_open_risk_intent(self, intent_id: str) -> Any:
        return risk.RiskIntent(
            intent_id=intent_id,
            scope=self.runtime.risk_scope,
            action=risk.IntentAction.INCREASE,
            notional=Decimal("1"),
            payload_fingerprint="e" * 64,
        )


def _release(fixture: _Fixture) -> Any:
    return fixture.control.release_cancel_freeze(fixture.command)


def test_typed_cancel_proof_resolves_dispatch_then_unknown_with_final_barrier(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path)
    try:
        authority = fixture.runtime.fake_dispatch_authority
        create = authority.create_cancel_dispatch_resolution_proof
        issued: list[Any] = []

        def capture(cancel_id: str, gate: Any) -> Any:
            proof = create(cancel_id, gate)
            issued.append(proof)
            return proof

        authority.create_cancel_dispatch_resolution_proof = capture
        reached_monitor = threading.Event()
        admission_result: list[str] = []
        original_append = fixture.runtime.outbox.append

        def append_with_concurrent_admission(event: Any) -> Any:
            if event.event_type == "cancellation_freeze_release_prepared":
                active = fixture.active()
                assert fixture.unknown_cause not in active
                assert fixture.progress_cause in active

                def try_new_order() -> None:
                    try:
                        fixture.runtime.risk_gate.reserve(
                            fixture.new_open_risk_intent("open-during-release")
                        )
                    except risk.RiskDeniedError:
                        admission_result.append("blocked")
                    else:
                        admission_result.append("admitted")
                    finally:
                        reached_monitor.set()

                worker = threading.Thread(target=try_new_order)
                worker.start()
                assert reached_monitor.wait(5)
                worker.join(timeout=5)
                assert not worker.is_alive()
                raise RuntimeError("simulated monitor commit failure after barrier probe")
            return original_append(event)

        fixture.runtime.outbox.append = append_with_concurrent_admission
        with pytest.raises(RuntimePluginError) as raised:
            _release(fixture)
        assert raised.value.code == "CANCELLATION_CONTROL_MONITOR_OUTBOX_UNCONFIRMED"
        assert admission_result == ["blocked"]
        active = fixture.active()
        assert fixture.unknown_cause in active
        assert fixture.progress_cause in active
        assert len(issued) == 1
        proof = issued[0]
        assert proof.cause_id not in active
        fixture.runtime.outbox.append = original_append

        result = _release(fixture)
        assert result.released is True
        assert result.idempotent is False
        active = fixture.active()
        assert fixture.unknown_cause not in active
        assert fixture.progress_cause not in active
        assert proof.cause_id not in active
        assert len(issued) == 1, "retry must reuse the exact persisted typed proof"
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "released"
        release_events = [
            item.event
            for item in fixture.runtime.outbox.read_pending(
                "cancel-control-test", fixture.runtime.scope.key
            )
            if item.event.event_id == "cancel-freeze-release:" + fixture.command.command_id
        ]
        assert len(release_events) == 1
        assert release_events[0].event_type == "cancellation_freeze_release_prepared"
        assert json.loads(release_events[0].data_json)["stage"] == (
            "final_in_progress_freeze_remains_active"
        )
        with sqlite3.connect(fixture.runtime.state_directory / "risk.sqlite3") as connection:
            rows = connection.execute(
                "SELECT proof_sha256 FROM risk_cancel_dispatch_resolutions WHERE cancel_id = ?",
                (fixture.cancel.cancel_id,),
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == proof.fingerprint
    finally:
        fixture.close()


def test_missing_authority_rejects_without_clearing_either_latch(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    try:
        from dataclasses import replace

        runtime_without_authority = replace(fixture.runtime, fake_dispatch_authority=None)
        control = ManagedCancellationReconciliationControlPort(
            runtime_without_authority,
            fixture.cancel_facade,
            state_directory=tmp_path / "direct-control",
            authorize=lambda request: AuthorizationDecision(
                True, request.command.issuer_id, "d" * 64, "approved"
            ),
        )
        try:
            with pytest.raises(RuntimePluginError) as raised:
                control.release_cancel_freeze(fixture.command)
            assert getattr(raised.value, "code", None) == (
                "CANCELLATION_DISPATCH_RESOLUTION_AUTHORITY_REQUIRED"
            )
            active = fixture.active()
            assert fixture.unknown_cause in active
            assert fixture.progress_cause not in active
            permit = fixture.cancel_facade.get(fixture.cancel.cancel_id).permit_reference
            claim = fixture.runtime.risk_gate.dispatch_claim_binding(permit)
            assert claim.cause_id in active
        finally:
            control.close()
    finally:
        fixture.close()


def test_proof_issuance_failure_reasserts_both_latches(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    try:

        def unavailable(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("fake authority unavailable")

        fixture.runtime.fake_dispatch_authority.create_cancel_dispatch_resolution_proof = (
            unavailable
        )
        with pytest.raises(RuntimePluginError) as raised:
            _release(fixture)
        assert getattr(raised.value, "code", None) == "CANCELLATION_DISPATCH_RESOLUTION_FAILED"
        active = fixture.active()
        assert fixture.unknown_cause in active
        assert fixture.progress_cause in active
        permit = fixture.cancel_facade.get(fixture.cancel.cancel_id).permit_reference
        assert fixture.runtime.risk_gate.dispatch_claim_binding(permit).cause_id in active
    finally:
        fixture.close()


def test_restart_replays_exact_proof_after_risk_commit_before_unknown_clear(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path)
    try:
        authority = fixture.runtime.fake_dispatch_authority
        create = authority.create_cancel_dispatch_resolution_proof
        issued: list[Any] = []

        def capture(cancel_id: str, gate: Any) -> Any:
            proof = create(cancel_id, gate)
            issued.append(proof)
            return proof

        authority.create_cancel_dispatch_resolution_proof = capture
        original_resolve = fixture.runtime.risk_gate.resolve_freeze

        def crash_before_unknown_commit(scope: Any, cause_id: str) -> None:
            if cause_id == fixture.unknown_cause:
                raise KeyboardInterrupt("simulated process stop after proof commit")
            original_resolve(scope, cause_id)

        fixture.runtime.risk_gate.resolve_freeze = crash_before_unknown_commit
        with pytest.raises(KeyboardInterrupt):
            _release(fixture)
        assert len(issued) == 1
        active = fixture.active()
        assert fixture.unknown_cause in active
        assert fixture.progress_cause in active
        assert issued[0].cause_id not in active

        fixture.control.close()
        fixture.control = fixture.new_control(tmp_path / "control")
        fixture.runtime.risk_gate.resolve_freeze = original_resolve
        active = fixture.active()
        assert fixture.unknown_cause in active
        assert fixture.progress_cause in active
        result = _release(fixture)
        assert result.released and not result.idempotent
        assert len(issued) == 1
        assert fixture.unknown_cause not in fixture.active()
        assert fixture.progress_cause not in fixture.active()
    finally:
        fixture.close()


def test_restart_finishes_last_latch_after_released_audit_commit(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    try:
        original_resolve = fixture.runtime.risk_gate.resolve_freeze

        def crash_before_final_latch_commit(scope: Any, cause_id: str) -> None:
            if cause_id == fixture.progress_cause:
                raise KeyboardInterrupt("simulated process stop at final latch")
            original_resolve(scope, cause_id)

        fixture.runtime.risk_gate.resolve_freeze = crash_before_final_latch_commit
        with pytest.raises(KeyboardInterrupt):
            _release(fixture)
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "released"
        active = fixture.active()
        assert fixture.unknown_cause not in active
        assert fixture.progress_cause in active

        fixture.control.close()
        fixture.control = fixture.new_control(tmp_path / "control")
        fixture.runtime.risk_gate.resolve_freeze = original_resolve
        result = _release(fixture)
        assert result.released and result.idempotent
        active = fixture.active()
        assert fixture.unknown_cause not in active
        assert fixture.progress_cause not in active
    finally:
        fixture.close()


def test_corrupt_replay_proof_reasserts_both_latches(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    try:
        original_resolve = fixture.runtime.risk_gate.resolve_freeze

        def crash_before_final_latch_commit(scope: Any, cause_id: str) -> None:
            if cause_id == fixture.progress_cause:
                raise KeyboardInterrupt("simulated process stop at final latch")
            original_resolve(scope, cause_id)

        fixture.runtime.risk_gate.resolve_freeze = crash_before_final_latch_commit
        with pytest.raises(KeyboardInterrupt):
            _release(fixture)
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "released"
        assert fixture.unknown_cause not in fixture.active()
        assert fixture.progress_cause in fixture.active()

        fixture.control.close()
        audit_db = tmp_path / "control" / "cancellation_operator_control.sqlite3"
        with sqlite3.connect(audit_db) as connection:
            connection.execute(
                "UPDATE cancellation_control_commands "
                "SET cancel_resolution_proof_sha256 = ? WHERE command_id = ?",
                ("0" * 64, fixture.command.command_id),
            )
        fixture.control = fixture.new_control(tmp_path / "control")
        fixture.runtime.risk_gate.resolve_freeze = original_resolve

        with pytest.raises(RuntimePluginError) as raised:
            _release(fixture)
        assert raised.value.code == "CANCELLATION_CONTROL_RELEASE_RECOVERY_FAILED"
        active = fixture.active()
        assert fixture.unknown_cause in active
        assert fixture.progress_cause in active
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "pending"
    finally:
        fixture.close()


@pytest.mark.parametrize("monitor_mutation", ("delete", "corrupt"))
def test_released_replay_requires_exact_prepared_monitor_fact(
    tmp_path: Path, monitor_mutation: str
) -> None:
    fixture = _Fixture(tmp_path)
    try:
        original_resolve = fixture.runtime.risk_gate.resolve_freeze

        def crash_before_final_latch_commit(scope: Any, cause_id: str) -> None:
            if cause_id == fixture.progress_cause:
                raise KeyboardInterrupt("simulated process stop at final latch")
            original_resolve(scope, cause_id)

        fixture.runtime.risk_gate.resolve_freeze = crash_before_final_latch_commit
        with pytest.raises(KeyboardInterrupt):
            _release(fixture)
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "released"
        assert fixture.progress_cause in fixture.active()

        fixture.control.close()
        outbox_db = tmp_path / "state" / "monitor.sqlite3"
        event_id = "cancel-freeze-release:" + fixture.command.command_id
        with sqlite3.connect(outbox_db) as connection:
            if monitor_mutation == "delete":
                connection.execute(
                    "DROP TRIGGER trg_cancel_release_prepared_immutable_delete"
                )
                connection.execute(
                    "DELETE FROM monitor_outbox_events WHERE event_id = ?", (event_id,)
                )
            else:
                connection.execute(
                    "DROP TRIGGER trg_cancel_release_prepared_immutable_update"
                )
                connection.execute(
                    "UPDATE monitor_outbox_events SET event_type = ? WHERE event_id = ?",
                    ("corrupted_release_event", event_id),
                )
        fixture.control = fixture.new_control(tmp_path / "control")
        fixture.runtime.risk_gate.resolve_freeze = original_resolve

        with pytest.raises(RuntimePluginError) as raised:
            _release(fixture)
        assert raised.value.code == "CANCELLATION_CONTROL_RELEASE_RECOVERY_FAILED"
        active = fixture.active()
        assert fixture.unknown_cause in active
        assert fixture.progress_cause in active
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "pending"
    finally:
        fixture.close()


def test_authorization_callback_returned_after_expiry_is_rejected(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    try:
        def approve_after_expiry(request: Any) -> AuthorizationDecision:
            fixture.now = request.command.expires_at + 0.01
            return AuthorizationDecision(
                True, request.command.issuer_id, "0" * 64, "approved"
            )

        fixture.control._authorize = approve_after_expiry
        with pytest.raises(RuntimePluginError) as raised:
            _release(fixture)

        assert raised.value.code == "CANCELLATION_CONTROL_COMMAND_EXPIRED"
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "expired"
        assert audit.release_applied_at is None
        assert fixture.control.audit.get_cancel_dispatch_proof(fixture.command.command_id) is None
        active = fixture.active()
        assert fixture.unknown_cause in active
        assert fixture.progress_cause not in active
        with sqlite3.connect(fixture.runtime.state_directory / "monitor.sqlite3") as connection:
            row = connection.execute(
                "SELECT 1 FROM monitor_outbox_events WHERE event_id = ?",
                ("cancel-freeze-release:" + fixture.command.command_id,),
            ).fetchone()
        assert row is None
    finally:
        fixture.close()


def test_expiry_after_release_audit_commit_reasserts_latches_and_marks_expired(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path)
    try:
        original_mark_released = fixture.control.audit.mark_command_released

        def mark_then_expire(command_id: str) -> Any:
            result = original_mark_released(command_id)
            fixture.now = fixture.command.expires_at + 0.01
            return result

        fixture.control.audit.mark_command_released = mark_then_expire
        with pytest.raises(RuntimePluginError) as raised:
            _release(fixture)

        assert raised.value.code == "CANCELLATION_CONTROL_COMMAND_EXPIRED"
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None
        assert audit.status.value == "expired"
        assert audit.released_at is None
        assert audit.release_applied_at is not None
        active = fixture.active()
        assert fixture.unknown_cause in active
        assert fixture.progress_cause in active
        with sqlite3.connect(fixture.runtime.state_directory / "monitor.sqlite3") as connection:
            row = connection.execute(
                "SELECT event_type FROM monitor_outbox_events WHERE event_id = ?",
                ("cancel-freeze-release:" + fixture.command.command_id,),
            ).fetchone()
        assert row == ("cancellation_freeze_release_prepared",)
    finally:
        fixture.close()


def test_first_release_rejects_monitor_event_deleted_after_append(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    try:
        original_append = fixture.runtime.outbox.append
        event_id = "cancel-freeze-release:" + fixture.command.command_id
        deleted = []

        def append_then_delete(event: Any) -> Any:
            receipt = original_append(event)
            if event.event_id == event_id:
                with sqlite3.connect(
                    fixture.runtime.state_directory / "monitor.sqlite3"
                ) as connection:
                    connection.execute(
                        "DELETE FROM monitor_outbox_events WHERE event_id = ?", (event_id,)
                    )
                deleted.append(event_id)
            return receipt

        fixture.runtime.outbox.append = append_then_delete
        with pytest.raises(RuntimePluginError) as raised:
            _release(fixture)

        assert raised.value.code == "CANCELLATION_CONTROL_MONITOR_OUTBOX_UNCONFIRMED"
        assert deleted == [event_id]
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "pending"
        assert audit.release_applied_at is not None
        active = fixture.active()
        assert fixture.unknown_cause in active
        assert fixture.progress_cause in active
        with sqlite3.connect(fixture.runtime.state_directory / "monitor.sqlite3") as connection:
            row = connection.execute(
                "SELECT 1 FROM monitor_outbox_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        assert row is None

        fixture.control.close()
        fixture.control = fixture.new_control(tmp_path / "control")
        active_after_reopen = fixture.active()
        assert fixture.unknown_cause in active_after_reopen
        assert fixture.progress_cause in active_after_reopen
    finally:
        fixture.close()


def test_release_holds_monitor_writer_boundary_against_cross_process_delete(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path)
    process: subprocess.Popen[str] | None = None
    try:
        original_resolve = fixture.runtime.risk_gate.resolve_freeze
        event_id = "cancel-freeze-release:" + fixture.command.command_id
        database_path = fixture.runtime.state_directory / "monitor.sqlite3"
        attempt_marker = tmp_path / "monitor-delete-attempt-ready.txt"
        delete_script = r'''
import sqlite3
import sys
from pathlib import Path

connection = sqlite3.connect(sys.argv[1], timeout=3.0, isolation_level=None)
Path(sys.argv[3]).write_text("ready", encoding="utf-8")
try:
    connection.execute("DELETE FROM monitor_outbox_events WHERE event_id = ?", (sys.argv[2],))
    print("DELETED")
except sqlite3.IntegrityError as error:
    print("BLOCKED:" + str(error))
except sqlite3.OperationalError as error:
    print("LOCKED:" + str(error))
finally:
    connection.close()
'''

        def start_competing_writer(scope: Any, cause_id: str) -> None:
            nonlocal process
            if cause_id == fixture.progress_cause:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        delete_script,
                        str(database_path),
                        event_id,
                        str(attempt_marker),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                deadline = time.monotonic() + 2.0
                while not attempt_marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert attempt_marker.exists()
                # The child signals immediately before DELETE, then must stay
                # blocked while this call owns the monitor write transaction.
                time.sleep(0.1)
                assert process.poll() is None
            original_resolve(scope, cause_id)

        fixture.runtime.risk_gate.resolve_freeze = start_competing_writer
        result = _release(fixture)
        assert result.released
        assert process is not None
        stdout, stderr = process.communicate(timeout=5)
        assert not stderr
        assert stdout.startswith("BLOCKED:")
        assert "immutable" in stdout
        print("cross-process direct DELETE result: " + stdout.strip())
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "released"
        assert fixture.unknown_cause not in fixture.active()
        assert fixture.progress_cause not in fixture.active()
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                "SELECT event_type FROM monitor_outbox_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        assert row == ("cancellation_freeze_release_prepared",)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        fixture.close()


def test_same_user_schema_writer_can_bypass_sqlite_only_guard_after_commit(
    tmp_path: Path,
) -> None:
    """Record the limit: SQLite triggers do not isolate the database file."""
    fixture = _Fixture(tmp_path)
    process: subprocess.Popen[str] | None = None
    try:
        result = _release(fixture)
        assert result.released
        event_id = "cancel-freeze-release:" + fixture.command.command_id
        database_path = fixture.runtime.state_directory / "monitor.sqlite3"
        attack_script = r'''
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1], timeout=3.0, isolation_level=None)
try:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("DROP TRIGGER trg_cancel_release_prepared_immutable_delete")
    connection.execute("DROP TRIGGER trg_cancel_release_prepared_immutable_update")
    connection.execute("DELETE FROM monitor_outbox_events WHERE event_id = ?", (sys.argv[2],))
    connection.execute("COMMIT")
    print("DROPPED_TRIGGERS_AND_DELETED")
except Exception:
    if connection.in_transaction:
        connection.execute("ROLLBACK")
    raise
finally:
    connection.close()
'''
        process = subprocess.Popen(
            [sys.executable, "-c", attack_script, str(database_path), event_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        assert stdout.strip() == "DROPPED_TRIGGERS_AND_DELETED"
        print("same-user post-commit DDL bypass result: " + stdout.strip())
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "released"
        assert fixture.unknown_cause not in fixture.active()
        assert fixture.progress_cause not in fixture.active()
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM monitor_outbox_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        assert row is None
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        fixture.close()


def test_readback_connection_is_closed_after_exact_monitor_check(tmp_path: Path, monkeypatch: Any) -> None:
    fixture = _Fixture(tmp_path)
    try:
        assert _release(fixture).released
        command_audit = fixture.control.audit.get_command(fixture.command.command_id)
        evidence = fixture.control.audit.get_reconciliation(fixture.command.evidence_id)
        stored_proof = fixture.control.audit.get_cancel_dispatch_proof(
            fixture.command.command_id
        )
        assert command_audit is not None and command_audit.release_applied_at is not None
        assert evidence is not None and stored_proof is not None
        proof = cancellation_control_module._restore_cancel_dispatch_proof(
            stored_proof[0], stored_proof[1], fixture.runtime.fake_dispatch_authority
        )

        real_connect = sqlite3.connect
        opened: list[sqlite3.Connection] = []

        def tracked_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            connection = real_connect(*args, **kwargs)
            opened.append(connection)
            return connection

        monkeypatch.setattr(cancellation_control_module.sqlite3, "connect", tracked_connect)
        fixture.control._verify_release_prepared_monitor_fact(
            fixture.command,
            evidence,
            proof,
            command_audit.release_applied_at,
        )
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            opened[0].execute("SELECT 1")
    finally:
        monkeypatch.undo()
        fixture.close()


def test_monitor_fact_readback_connection_is_closed(tmp_path: Path, monkeypatch: Any) -> None:
    fixture = _Fixture(tmp_path)
    try:
        assert _release(fixture).released
        command_audit = fixture.control.audit.get_command(fixture.command.command_id)
        evidence = fixture.control.audit.get_reconciliation(fixture.command.evidence_id)
        stored_proof = fixture.control.audit.get_cancel_dispatch_proof(
            fixture.command.command_id
        )
        assert command_audit is not None and command_audit.release_applied_at is not None
        assert evidence is not None and stored_proof is not None
        proof = cancellation_control_module._restore_cancel_dispatch_proof(
            stored_proof[0], stored_proof[1], fixture.runtime.fake_dispatch_authority
        )

        real_connect = sqlite3.connect
        opened: list[sqlite3.Connection] = []

        def tracked_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            connection = real_connect(*args, **kwargs)
            opened.append(connection)
            return connection

        monkeypatch.setattr(cancellation_control_module.sqlite3, "connect", tracked_connect)
        fixture.control._verify_release_prepared_monitor_fact(
            fixture.command,
            evidence,
            proof,
            command_audit.release_applied_at,
        )
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            opened[0].execute("SELECT 1")
    finally:
        monkeypatch.undo()
        fixture.close()


def test_risk_write_failure_reasserts_latches_and_releases_monitor_lock(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path)
    try:
        original_resolve = fixture.runtime.risk_gate.resolve_freeze

        def fail_after_final_risk_commit(scope: Any, cause_id: str) -> None:
            original_resolve(scope, cause_id)
            if cause_id == fixture.progress_cause:
                raise RuntimeError("simulated lost risk commit acknowledgement")

        fixture.runtime.risk_gate.resolve_freeze = fail_after_final_risk_commit
        with pytest.raises(RuntimePluginError) as raised:
            _release(fixture)
        assert raised.value.code == "CANCELLATION_CONTROL_FREEZE_RESOLUTION_FAILED"
        assert fixture.unknown_cause in fixture.active()
        assert fixture.progress_cause in fixture.active()
        audit = fixture.control.audit.get_command(fixture.command.command_id)
        assert audit is not None and audit.status.value == "pending"
        event_id = "cancel-freeze-release:" + fixture.command.command_id
        database_path = fixture.runtime.state_directory / "monitor.sqlite3"
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                "SELECT event_type FROM monitor_outbox_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        assert row == ("cancellation_freeze_release_prepared",)
        with sqlite3.connect(database_path) as connection, pytest.raises(
            sqlite3.IntegrityError, match="immutable"
        ):
            connection.execute(
                "DELETE FROM monitor_outbox_events WHERE event_id = ?", (event_id,)
            )
        fixture.control.close()
        fixture.control = fixture.new_control(tmp_path / "control")
        assert fixture.unknown_cause in fixture.active()
        assert fixture.progress_cause in fixture.active()
    finally:
        fixture.close()


def test_fake_resolution_authority_rejects_ctp_labeled_execution_scope(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    fixture = _Fixture(tmp_path)
    control = None
    authority = fixture.runtime.fake_dispatch_authority
    original_execution_scope = authority._execution_scope
    authorize_calls: list[Any] = []
    cancel_state_before = fixture.cancel_facade.get(fixture.cancel.cancel_id).state
    try:
        forged_scope = replace(fixture.runtime.scope, provider="ctp")
        # Model inconsistent in-process wiring that preserves matching object
        # references. The provider label itself must still fail the fixed
        # offline tuple allowlist before any release work begins.
        authority._execution_scope = forged_scope
        forged_runtime = replace(fixture.runtime, scope=forged_scope)
        control = ManagedCancellationReconciliationControlPort(
            forged_runtime,
            fixture.cancel_facade,
            state_directory=tmp_path / "forged-ctp-control",
            authorize=lambda request: authorize_calls.append(request),
        )
        command = replace(fixture.command, scope=forged_scope.key)
        with pytest.raises(RuntimePluginError) as raised:
            control.release_cancel_freeze(command)

        assert raised.value.code == "CANCELLATION_DISPATCH_RESOLUTION_AUTHORITY_REQUIRED"
        assert authorize_calls == []
        assert control.audit.get_command(command.command_id) is None
        assert fixture.unknown_cause in fixture.active()
        assert fixture.progress_cause not in fixture.active()
        assert fixture.cancel_facade.get(fixture.cancel.cancel_id).state is cancel_state_before
    finally:
        if control is not None:
            control.close()
        authority._execution_scope = original_execution_scope
        fixture.close()


@pytest.mark.parametrize(
    "mismatch", ("ctp_provider", "wrong_account", "wrong_strategy", "wrong_policy")
)
def test_fake_authority_constructor_rejects_unregistered_execution_scope(
    tmp_path: Path, mismatch: str
) -> None:
    from dataclasses import replace

    from bt_api_py.runtime_plugins.fake_dispatch_authority import (
        FakeDispatchJournalError,
        ManagedFakeProviderJournalAuthority,
    )

    fixture = _Fixture(tmp_path)
    try:
        execution_scope = fixture.runtime.scope
        risk_scope = fixture.runtime.risk_scope
        policy_id = fixture.runtime.risk_gate.policy.policy_id
        if mismatch == "ctp_provider":
            execution_scope = replace(execution_scope, provider="ctp")
        elif mismatch == "wrong_account":
            execution_scope = replace(execution_scope, account_ref="unregistered-account")
            risk_scope = replace(risk_scope, account_id="unregistered-account")
        elif mismatch == "wrong_strategy":
            execution_scope = replace(execution_scope, strategy_id="unregistered-strategy")
        else:
            policy_id = "unregistered-policy"
        database_path = tmp_path / ("rejected-authority-" + mismatch + ".sqlite3")
        with pytest.raises(FakeDispatchJournalError):
            ManagedFakeProviderJournalAuthority(
                database_path=database_path,
                execution_scope=execution_scope,
                risk_scope=risk_scope,
                execution_store=fixture.runtime.execution_store,
                facade=None,
                risk_types=risk,
                contract=fixture.runtime.contract,
                policy_id=policy_id,
            )
        assert not database_path.exists()
        assert fixture.unknown_cause in fixture.active()
        assert fixture.progress_cause not in fixture.active()
    finally:
        fixture.close()
