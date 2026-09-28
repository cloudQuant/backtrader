"""Offline acceptance for the Iteration 41 managed cancellation route.

The test combines only local SDK source packages after a sealed managed
configuration has resolved.  Its fake provider records every submission and
cancellation while socket connection attempts are forbidden.  It proves that
the Backtrader Store has no direct cancellation fallback after a managed route
is attached.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.test_utils.iteration41_source_roots import (
    iteration41_child_pythonpath,
    iteration41_source_paths,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _require_sdk_sources() -> tuple[str, ...]:
    return iteration41_source_paths("parent", "base", "execution", "risk", "monitor")


@pytest.mark.parametrize(
    ("scenario", "expected_submissions", "expected_cancellations", "expected_outcome"),
    (
        ("offline_fake", 3, 2, "reconciled"),
        ("production_synthetic", 1, 0, "dispatch_resolution_required"),
    ),
)
def test_managed_cancellation_is_journaled_idempotent_and_never_falls_back(
    scenario: str, expected_submissions: int, expected_cancellations: int, expected_outcome: str
) -> None:
    _sdk_sources = _require_sdk_sources()
    script = textwrap.dedent(
        """
        import importlib
        import importlib.metadata
        import json
        import socket
        import sqlite3
        import tempfile
        import time
        from decimal import Decimal
        from pathlib import Path
        from types import SimpleNamespace

        socket_attempts = []

        class DeniedSocket(socket.socket):
            def connect(self, *args, **kwargs):
                socket_attempts.append((args, kwargs))
                raise AssertionError("managed cancellation acceptance must remain offline")

            def connect_ex(self, *args, **kwargs):
                socket_attempts.append((args, kwargs))
                raise AssertionError("managed cancellation acceptance must remain offline")

        socket.socket = DeniedSocket

        from backtrader.order import OrderBase
        from backtrader.stores.btapistore import BtApiStore
        from backtrader_runtime import (
            ManagedExecutionBindingError,
            RegisteredRuntime,
            RuntimeRegistry,
            load_runtime_config,
            resolve_runtime_config,
        )
        from backtrader_runtime.managed_execution import bind_managed_execution
        from bt_api_py.runtime_plugins import (
            CAPABILITY_EXECUTION,
            CAPABILITY_MONITOR,
            CAPABILITY_RISK,
            AuthorizationDecision,
            CancellationReconciliationEvidence,
            CapabilityCatalog,
            CapabilityPin,
            ReleaseCancellationFreezeCommand,
            RuntimeCapabilityContract,
            SealedNormalizedInstrumentMetadataSnapshot,
            compose_managed_execution,
        )
        import bt_api_risk as risk

        scenario = __SCENARIO__
        offline_fake = scenario == "offline_fake"
        strategy_id = (
            "example.013_3.sa_midfreq_simnow"
            if offline_fake
            else "example.014_1.ctp_options_lowfreq"
        )
        runtime_mode = "simulation" if offline_fake else "live"
        runtime_preset = "replay" if offline_fake else "managed_live_direct"
        runtime_environment = "offline" if offline_fake else "production"
        runtime_secrets_ref = "none" if offline_fake else "runtime_secrets"
        provider_name = (
            "iteration41_managed_replay_fake_provider" if offline_fake else "fixture"
        )
        account_ref = (
            "iteration41_managed_replay_fake_account" if offline_fake else "account.41"
        )
        policy_id = "iteration41.managed_replay.l2" if offline_fake else "policy.41"

        class OfflineProvider:
            def __init__(self):
                self.submissions = []
                self.cancellations = []
                self.ambiguous_cancel_ids = set()
                self.cancel_claim_observations = []
                self.before_cancel = None

            def get_balance(self):
                return {"cash": 100.0, "value": 100.0}

            def submit_order(self, payload):
                payload = dict(payload)
                self.submissions.append(payload)
                return {"status": "accepted", "id": "provider." + payload["bt_order_ref"]}

            def cancel_order(self, order_ref, *, dataname=None):
                if self.before_cancel is not None:
                    self.before_cancel(order_ref, dataname)
                self.cancellations.append((order_ref, dataname))
                if order_ref in self.ambiguous_cancel_ids:
                    # The legacy Store accepts this historic shape, but its
                    # managed bridge must persist UNKNOWN because the target
                    # provider identity is absent from the response.
                    return {"status": "accepted"}
                return {"status": "cancelled", "id": order_ref}

        class ExplicitLimitOrder:
            exectype = OrderBase.Limit
            size = 2
            price = 10.25
            pricelimit = None
            valid = None
            tradeid = 0
            data = SimpleNamespace(_name="fixture/contract")
            created = SimpleNamespace(price=10.25)

            def __init__(self, intent_id, *, include_managed_identity=True):
                self.ref = intent_id
                self.info = {
                    "managed_order_type": "LIMIT",
                    "managed_signal_id": "signal." + intent_id,
                    "managed_instrument": "fixture/contract",
                    "managed_position_effect": "OPEN",
                    "managed_metadata_version": "metadata.1",
                    "managed_instrument_metadata_digest": metadata_digest,
                    "offset": "open",
                    "reduce_only": False,
                }
                if include_managed_identity:
                    self.info["managed_intent_id"] = intent_id

            def isbuy(self):
                return True

            def issell(self):
                return False

            def getordername(self):
                return "Limit"

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            runtime_dir = root / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "config.yaml").write_text(
                "config_schema_version: 4\\n"
                "strategy:\\n"
                "  id: " + strategy_id + "\\n"
                "runtime:\\n"
                "  mode: " + runtime_mode + "\\n"
                "  preset: " + runtime_preset + "\\n"
                "parameters: {}\\n"
                "secrets_ref: " + runtime_secrets_ref + "\\n",
                encoding="utf-8",
            )
            registration_options = (
                {"offline_managed_execution": True}
                if offline_fake
                else {"approval_receipt_digest": "a" * 64}
            )
            registry = RuntimeRegistry(
                (
                    RegisteredRuntime(
                        runtime_dir=runtime_dir,
                        runtime_id="fixture.iteration41.cancellation." + scenario,
                        strategy_id=strategy_id,
                        allowed_presets=(runtime_preset,),
                        allowed_secrets_refs=(runtime_secrets_ref,),
                        available_capabilities=(
                            CAPABILITY_EXECUTION,
                            CAPABILITY_RISK,
                            CAPABILITY_MONITOR,
                        ),
                        **registration_options,
                    ),
                )
            )
            effective = resolve_runtime_config(load_runtime_config(runtime_dir, registry=registry), registry)
            contract = RuntimeCapabilityContract.from_effective_public_dict(effective.as_public_dict())
            catalog = CapabilityCatalog(
                (
                    CapabilityPin(CAPABILITY_EXECUTION, "bt_api_execution", "bt_api_execution", "0.2.0"),
                    CapabilityPin(CAPABILITY_RISK, "bt_api_risk", "bt_api_risk", "0.1.0"),
                    CapabilityPin(CAPABILITY_MONITOR, "bt_api_monitor", "bt_api_monitor", "0.1.0"),
                ),
                importer=importlib.import_module,
                version_getter=importlib.metadata.version,
            )
            metadata_snapshot = SealedNormalizedInstrumentMetadataSnapshot.from_normalized_payload(
                {
                    "provider": provider_name,
                    "environment": runtime_environment,
                    "account_ref": account_ref,
                    "trading_day": "20260922",
                    "metadata_version": "metadata.1",
                    "as_of_ns": 1_700_000_000_000_000_000,
                    "expires_at_ns": 1_800_000_000_000_000_000,
                    "account_currency": "USD",
                    "instruments": [
                        {
                            "instrument": "fixture/contract",
                            "tick_size": "0.01",
                            "lot_size": "1",
                            "contract_multiplier": "1",
                            "max_gross_notional_account": "1000",
                            "quote_currency": "USD",
                            "fee_currency": "USD",
                            "quote_to_account_fx": "1",
                            "fee_to_account_fx": "1",
                            "taker_fee_bps": "0",
                            "fixed_fee": "0",
                            "max_slippage_bps": "0",
                            "min_quantity": "1",
                            "max_quantity": "10",
                            "quantity_unit": "contracts",
                        }
                    ],
                }
            )
            metadata_digest = metadata_snapshot.instrument_digest("fixture/contract")
            managed = compose_managed_execution(
                catalog.load(contract),
                state_directory=root / "state",
                provider=provider_name,
                environment=runtime_environment,
                account_ref=account_ref,
                strategy_id=effective.strategy_id,
                writer_id="writer.41",
                policy_id=policy_id,
                max_increase_notional=Decimal("1000"),
                max_increase_count=10,
                permit_ttl_seconds=300.0 if offline_fake else 0.2,
                trading_day="20260922",
                instrument_metadata_snapshot=metadata_snapshot,
                instrument_clock_ns=lambda: 1_750_000_000_000_000_000,
            )
            try:
                provider = OfflineProvider()
                store = BtApiStore(provider="btapi", api=provider)
                bridge = bind_managed_execution(store, effective, managed)

                active_cancel_id = {"value": None}

                def observe_cancel_risk_claim(_order_ref, _dataname):
                    cancel_id = active_cancel_id["value"]
                    cancel_record = managed.execution_store.get_cancel(
                        cancel_id, scope=managed.scope
                    )
                    cancel_intent = managed.execution_store.get_cancel_intent(
                        cancel_id, scope=managed.scope
                    )
                    observation = {
                        "cancel_id": cancel_id,
                        "state_at_provider_boundary": (
                            cancel_record.state.value if cancel_record is not None else None
                        ),
                        "attempts_at_provider_boundary": (
                            cancel_record.dispatch_attempts if cancel_record is not None else None
                        ),
                    }
                    try:
                        if cancel_record is None or cancel_intent is None:
                            raise AssertionError("durable cancel intent is missing at provider boundary")
                        expected_risk_intent_id = (
                            "cancel-admission:" + managed.scope.key + ":" + cancel_id
                        )
                        expected_risk_intent = risk.RiskIntent(
                            intent_id=expected_risk_intent_id,
                            scope=managed.risk_scope,
                            action=risk.IntentAction.CANCEL,
                            notional=Decimal("0"),
                            payload_fingerprint=cancel_intent.fingerprint,
                        )
                        claim = managed.risk_gate.dispatch_claim_binding(
                            cancel_record.permit_reference
                        )
                        observation.update(
                            {
                                "claim_scope": claim.scope.key,
                                "claim_intent_id": claim.intent_id,
                                "claim_intent_hash": claim.intent_hash,
                                "expected_intent_hash": expected_risk_intent.fingerprint,
                                "claim_digest": claim.claim_digest,
                                "claim_cause_id": claim.cause_id,
                            }
                        )
                    except Exception as error:
                        observation["claim_error"] = {
                            "type": type(error).__name__,
                            "code": getattr(error, "code", None),
                            "message": str(error),
                        }
                    provider.cancel_claim_observations.append(observation)

                provider.before_cancel = observe_cancel_risk_claim

                successful = ExplicitLimitOrder("intent.success")
                if not offline_fake:
                    # This is deliberately production-shaped but still local.
                    # The fake provider is called once and its ACK is durable;
                    # the run then fails at dispatch-latch resolution because
                    # no trusted production execution journal is composed.
                    try:
                        store.submit_order(successful)
                    except Exception as error:
                        assert type(error).__name__ == "RuntimePluginError", repr(error)
                        assert getattr(error, "code", None) == "DISPATCH_FREEZE_RESOLUTION_FAILED"
                        error_chain = []
                        cause = error
                        while cause is not None:
                            error_chain.append(
                                {
                                    "type": type(cause).__name__,
                                    "code": getattr(cause, "code", None),
                                    "message": str(cause),
                                }
                            )
                            cause = getattr(cause, "__cause__", None)
                        assert any(
                            entry["code"] == "DISPATCH_FREEZE_RECONCILIATION_REQUIRED"
                            for entry in error_chain
                        ), error_chain
                        assert any(
                            "offline fake journal authority" in entry["message"]
                            for entry in error_chain
                        ), error_chain
                    else:
                        raise AssertionError(
                            "production-shaped synthetic dispatch resolved without trusted authority"
                        )
                    durable_ack = managed.execution_store.get("intent.success", scope=managed.scope)
                    assert durable_ack is not None
                    assert durable_ack.state.value == "ACKED"
                    assert durable_ack.provider_order_id == "provider.intent.success"
                    assert durable_ack.dispatch_attempts == 1
                    dispatch_cause = "dispatch-inflight:intent.success"
                    assert dispatch_cause in managed.risk_gate.active_freeze_reasons(
                        managed.risk_scope
                    )
                    assert managed.fake_dispatch_authority is None
                    assert len(provider.submissions) == 1
                    # Replaying the same ACK and submitting a second intent
                    # must not turn the missing resolver into another provider
                    # call; the unresolved freeze remains visible.
                    try:
                        store.submit_order(successful)
                    except Exception as error:
                        assert type(error).__name__ == "RuntimePluginError", repr(error)
                    else:
                        raise AssertionError(
                            "replayed ACK bypassed unresolved dispatch-latch review"
                        )
                    replayed_ack = managed.execution_store.get(
                        "intent.success", scope=managed.scope
                    )
                    assert replayed_ack is not None
                    assert replayed_ack.state.value == "ACKED"
                    assert replayed_ack.dispatch_attempts == 1

                    extra_rejection = None
                    try:
                        extra_response = store.submit_order(
                            ExplicitLimitOrder("intent.extra")
                        )
                    except Exception as error:
                        assert type(error).__name__ == "RuntimePluginError", repr(error)
                        extra_rejection = {
                            "type": type(error).__name__,
                            "code": getattr(error, "code", None),
                            "message": str(error),
                        }
                    else:
                        assert extra_response["managed_execution_state"] == "BLOCKED"
                    extra_record = managed.execution_store.get(
                        "intent.extra", scope=managed.scope
                    )
                    if extra_record is not None:
                        assert extra_record.state.value in {"BLOCKED", "REJECTED"}
                        assert extra_record.dispatch_attempts == 0
                    assert len(provider.submissions) == 1
                    assert dispatch_cause in managed.risk_gate.active_freeze_reasons(
                        managed.risk_scope
                    )
                    print(
                        json.dumps(
                            {
                                "scenario": scenario,
                                "failed_stage": "post_dispatch_freeze_resolution",
                                "provider_submissions": len(provider.submissions),
                                "provider_cancellations": len(provider.cancellations),
                                "record_state": durable_ack.state.value,
                                "dispatch_attempts": durable_ack.dispatch_attempts,
                                "replayed_ack_state": replayed_ack.state.value,
                                "error_chain": error_chain,
                                "extra_rejection": extra_rejection,
                                "extra_record_state": (
                                    extra_record.state.value if extra_record is not None else None
                                ),
                                "extra_record_dispatch_attempts": (
                                    extra_record.dispatch_attempts
                                    if extra_record is not None
                                    else None
                                ),
                                "active_dispatch_freeze": dispatch_cause
                                in managed.risk_gate.active_freeze_reasons(managed.risk_scope),
                            }
                        )
                    )
                    raise SystemExit(0)

                assert store.submit_order(successful)["id"] == "provider.intent.success"
                active_cancel_id["value"] = "cancel.intent.success"
                first_cancel = store.cancel_order(successful)
                repeated_cancel = store.cancel_order(successful)
                cancel_record = managed.execution_store.get_cancel(
                    "cancel.intent.success", scope=managed.scope
                )
                target = managed.execution_store.get("intent.success", scope=managed.scope)

                assert first_cancel == {"status": "cancelled", "id": "provider.intent.success"}
                assert repeated_cancel == {
                    "status": "cancelled",
                    "id": "provider.intent.success",
                    "managed_execution_cancel_replayed": True,
                    "managed_execution_cancel_state": "CANCELLED",
                }
                assert cancel_record is not None and cancel_record.state.value == "CANCELLED"
                assert target is not None and target.state.value == "CANCELLED"
                assert provider.cancellations == [("provider.intent.success", "fixture/contract")]
                assert len(provider.cancel_claim_observations) == 1
                success_claim = provider.cancel_claim_observations[0]
                assert success_claim["state_at_provider_boundary"] == "DISPATCHING"
                assert success_claim["attempts_at_provider_boundary"] == 1
                assert "claim_error" not in success_claim, success_claim
                assert success_claim["claim_scope"] == managed.risk_scope.key
                assert success_claim["claim_intent_id"] == (
                    "cancel-admission:" + managed.scope.key + ":cancel.intent.success"
                )
                assert success_claim["claim_intent_hash"] == success_claim["expected_intent_hash"]
                success_claim_cause = success_claim["claim_cause_id"]
                assert success_claim_cause not in managed.risk_gate.active_freeze_reasons(
                    managed.risk_scope
                )
                risk_db = sqlite3.connect(root / "state" / "risk.sqlite3")
                try:
                    cancel_actions = risk_db.execute(
                        "SELECT action FROM risk_reservations WHERE intent_id = ?",
                        (
                            "cancel-admission:"
                            + managed.scope.key
                            + ":cancel.intent.success",
                        ),
                    ).fetchall()
                finally:
                    risk_db.close()
                assert cancel_actions == [("cancel",)]

                # A bare/under-annotated framework object cannot cause a
                # legacy provider cancellation after managed binding.
                missing_identity = ExplicitLimitOrder("intent.missing", include_managed_identity=False)
                with __import__("pytest").raises(ManagedExecutionBindingError, match="managed_intent_id"):
                    store.cancel_order(missing_identity)
                with __import__("pytest").raises(ManagedExecutionBindingError, match="managed_intent_id"):
                    store.cancel_order_ref("provider.intent.success", dataname="fixture/contract")
                assert provider.cancellations == [("provider.intent.success", "fixture/contract")]

                uncertain = ExplicitLimitOrder("intent.unknown")
                assert store.submit_order(uncertain)["id"] == "provider.intent.unknown"
                provider.ambiguous_cancel_ids.add("provider.intent.unknown")
                active_cancel_id["value"] = "cancel.intent.unknown"
                unknown = store.cancel_order(uncertain)
                replayed_unknown = store.cancel_order(uncertain)
                unknown_record = managed.execution_store.get_cancel(
                    "cancel.intent.unknown", scope=managed.scope
                )
                unknown_cause = (
                    "cancel-outcome-unknown:" + managed.scope.key + ":cancel.intent.unknown"
                )

                assert unknown["execution_unknown"] is True
                assert replayed_unknown["execution_unknown"] is True
                assert unknown_record is not None and unknown_record.state.value == "UNKNOWN"
                unknown_claim = provider.cancel_claim_observations[-1]
                assert unknown_claim["state_at_provider_boundary"] == "DISPATCHING"
                assert unknown_claim["attempts_at_provider_boundary"] == 1
                assert "claim_error" not in unknown_claim, unknown_claim
                unknown_claim_cause = unknown_claim["claim_cause_id"]
                assert unknown_claim_cause in managed.risk_gate.active_freeze_reasons(
                    managed.risk_scope
                )
                assert provider.cancellations == [
                    ("provider.intent.success", "fixture/contract"),
                    ("provider.intent.unknown", "fixture/contract"),
                ]
                assert unknown_cause in managed.risk_gate.active_freeze_reasons(managed.risk_scope)

                # Expired permits must not free the account after an uncertain
                # cancellation: the independent freeze still blocks a new open.
                time.sleep(0.3)
                blocked = store.submit_order(ExplicitLimitOrder("intent.blocked"))
                assert blocked["managed_execution_state"] == "BLOCKED"
                assert len(provider.submissions) == 2

                observation = managed.execution.CancelObservation.cancelled(
                    "cancel.intent.unknown", "intent.unknown", "provider.intent.unknown"
                )
                if not offline_fake:
                    # The production-shaped synthetic route can record a
                    # terminal observation, but it lacks the reviewed fake
                    # journal authority that supports local replay release.
                    reconciled = bridge.reconcile_cancel(observation)
                    assert reconciled.state.value == "CANCELLED"
                with __import__("pytest").raises(
                    ManagedExecutionBindingError,
                    match="CONTROLLED_CANCEL_FREEZE_RELEASE_REQUIRED",
                ):
                    bridge.resolve_confirmed_cancel_freeze("cancel.intent.unknown")
                assert unknown_cause in managed.risk_gate.active_freeze_reasons(managed.risk_scope)
                still_blocked = store.submit_order(ExplicitLimitOrder("intent.still.blocked"))
                assert still_blocked["managed_execution_state"] == "BLOCKED"
                assert len(provider.submissions) == 2

                # The offline fake path can complete the explicit audited
                # release. In the production-shaped synthetic path, a locally
                # fabricated authorization cannot substitute for the fake
                # journal proof or a production reconciliation authority.
                def approve_cancel_release(request):
                    assert request.command.issuer_id == "operator.alice"
                    assert request.evidence.cancel_id == "cancel.intent.unknown"
                    return AuthorizationDecision(
                        approved=True,
                        subject_id="operator.alice",
                        receipt_digest="c" * 64,
                        reason_code="dual_review_complete",
                    )

                control = bridge.create_cancellation_reconciliation_control(
                    authorize=approve_cancel_release,
                    clock=lambda: 1700000002.0,
                )
                try:
                    evidence = CancellationReconciliationEvidence(
                        evidence_id="cancel-evidence.unknown",
                        cancel_id="cancel.intent.unknown",
                        target_intent_id="intent.unknown",
                        provider_order_id="provider.intent.unknown",
                        observation=observation,
                        source_receipt_digest="b" * 64,
                        observed_at=1700000000.0,
                    )
                    if offline_fake:
                        try:
                            audited = control.reconcile(evidence)
                        except Exception as error:
                            current_record = managed.execution_store.get_cancel(
                                "cancel.intent.unknown", scope=managed.scope
                            )
                            raise AssertionError(
                                "offline control reconciliation failed: "
                                + repr(error)
                                + "; current cancellation="
                                + repr(current_record)
                            ) from error
                        assert audited.audit.monitor_published is True
                        assert unknown_claim_cause not in managed.risk_gate.active_freeze_reasons(
                            managed.risk_scope
                        )
                        command = ReleaseCancellationFreezeCommand(
                            command_id="cancel-release.unknown",
                            scope=managed.scope.key,
                            cancel_id="cancel.intent.unknown",
                            evidence_id=evidence.evidence_id,
                            evidence_fingerprint=evidence.fingerprint,
                            issuer_id="operator.alice",
                            reason_code="dual_review_complete",
                            issued_at=1700000001.0,
                            expires_at=1700000060.0,
                        )
                        assert control.release_cancel_freeze(command).released is True
                    else:
                        try:
                            control.reconcile(evidence)
                        except Exception as error:
                            assert type(error).__name__ == "RuntimePluginError", repr(error)
                            assert (
                                getattr(error, "code", None)
                                == "CANCELLATION_RECONCILIATION_REQUIRES_UNKNOWN"
                            )
                        else:
                            raise AssertionError(
                                "production-shaped terminal data borrowed fake release authority"
                            )
                finally:
                    control.close()
                if offline_fake:
                    assert unknown_cause not in managed.risk_gate.active_freeze_reasons(
                        managed.risk_scope
                    )
                else:
                    assert unknown_cause in managed.risk_gate.active_freeze_reasons(
                        managed.risk_scope
                    )
                if offline_fake:
                    after_controlled_release = store.submit_order(
                        ExplicitLimitOrder("intent.after.release")
                    )
                    assert after_controlled_release["id"] == "provider.intent.after.release"
                    assert len(provider.submissions) == 3
                else:
                    try:
                        store.submit_order(ExplicitLimitOrder("intent.after.release"))
                    except Exception as error:
                        assert type(error).__name__ == "RuntimePluginError", repr(error)
                        assert getattr(error, "code", None) == "DISPATCH_FREEZE_RESOLUTION_FAILED"
                        assert getattr(getattr(error, "__cause__", None), "code", None) == (
                            "DISPATCH_FREEZE_RECONCILIATION_REQUIRED"
                        )
                        assert "offline fake journal authority" in str(error.__cause__)
                    else:
                        raise AssertionError(
                            "production-shaped synthetic release bypassed the journal authority"
                        )
                    assert len(provider.submissions) == 2
            finally:
                managed.close()

        assert socket_attempts == []
        summary = {
            "scenario": scenario,
            "submissions": len(provider.submissions),
            "cancellations": len(provider.cancellations),
            "unknown": "reconciled",
        }
        if offline_fake:
            summary["cancel_claim_observations"] = provider.cancel_claim_observations
        print(json.dumps(summary, sort_keys=True))
        """
    ).replace("__SCENARIO__", repr(scenario))
    environment = dict(os.environ)
    environment["PYTHONPATH"] = iteration41_child_pythonpath(_sdk_sources)
    environment["BT_API_PY_LIGHT_IMPORT"] = "1"

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    outcome = json.loads(completed.stdout)
    if scenario == "production_synthetic":
        assert outcome["scenario"] == scenario
        assert outcome["failed_stage"] == "post_dispatch_freeze_resolution"
        assert outcome["provider_submissions"] == expected_submissions
        assert outcome["provider_cancellations"] == expected_cancellations
        assert outcome["record_state"] == "ACKED"
        assert outcome["dispatch_attempts"] == 1
        assert outcome["replayed_ack_state"] == "ACKED"
        assert outcome["extra_rejection"]["type"] == "RuntimePluginError"
        assert outcome["extra_record_state"] is None
        assert outcome["extra_record_dispatch_attempts"] is None
        assert outcome["active_dispatch_freeze"] is True
        assert any(
            entry["code"] == "DISPATCH_FREEZE_RECONCILIATION_REQUIRED"
            for entry in outcome["error_chain"]
        )
        assert any(
            "offline fake journal authority" in entry["message"]
            for entry in outcome["error_chain"]
        )
    else:
        assert outcome["scenario"] == scenario
        assert outcome["submissions"] == expected_submissions
        assert outcome["cancellations"] == expected_cancellations
        assert outcome["unknown"] == expected_outcome
        if offline_fake:
            assert len(outcome["cancel_claim_observations"]) == 2
    print(json.dumps({"managed_cancellation_outcome": outcome}, sort_keys=True))


def test_unknown_cancel_after_lease_takeover_blocks_live_bridge_until_restart() -> None:
    """Fence an old live bridge when a newer writer commits an UNKNOWN cancel."""

    _sdk_sources = _require_sdk_sources()
    script = textwrap.dedent(
        """
        import importlib
        import json
        import socket
        import sqlite3
        import tempfile
        import time
        from decimal import Decimal
        from pathlib import Path
        from types import SimpleNamespace

        socket_attempts = []

        class DeniedSocket(socket.socket):
            def connect(self, *args, **kwargs):
                socket_attempts.append((args, kwargs))
                raise AssertionError("recovery acceptance must remain offline")

            def connect_ex(self, *args, **kwargs):
                socket_attempts.append((args, kwargs))
                raise AssertionError("recovery acceptance must remain offline")

        socket.socket = DeniedSocket

        from backtrader.order import OrderBase
        from backtrader_runtime.managed_execution import ManagedExecutionBridge
        from bt_api_py.runtime_plugins import (
            CAPABILITY_EXECUTION,
            CAPABILITY_MONITOR,
            CAPABILITY_RISK,
            CapabilityCatalog,
            CapabilityPin,
            RuntimeCapabilityContract,
            DurableManagedRecoveryCoordinator,
            ManagedExecutionRuntime,
        )
        from bt_api_py.runtime_plugins.fake_dispatch_authority import (
            ManagedFakeProviderJournalAuthority,
        )

        class ManagedOrder:
            exectype = OrderBase.Limit
            size = 1
            price = 10
            created = SimpleNamespace(price=10)
            data = SimpleNamespace(_name="fixture/contract")

            def __init__(self, intent_id, cancel_id):
                self.ref = intent_id
                self.info = {
                    "managed_order_type": "LIMIT",
                    "managed_intent_id": intent_id,
                    "managed_signal_id": "signal." + intent_id,
                    "managed_instrument": "fixture/contract",
                    "managed_instrument_metadata_digest": metadata_digest,
                    "managed_position_effect": "OPEN",
                    "managed_metadata_version": "metadata.1",
                    "offset": "open",
                    "reduce_only": False,
                    # This deliberately collides across distinct execution
                    # scopes.  It remains the visible execution/audit id.
                    "managed_cancel_intent_id": cancel_id,
                }

            def isbuy(self):
                return True

            def issell(self):
                return False

        class SimulatedProcessCrash(RuntimeError):
            pass

        def contract(strategy_id):
            return RuntimeCapabilityContract(
                strategy_id=strategy_id,
                mode="simulation",
                preset="replay",
                environment="offline",
                order_route="managed_execution",
                required_capabilities=(
                    CAPABILITY_EXECUTION,
                    CAPABILITY_RISK,
                    CAPABILITY_MONITOR,
                ),
                effective_digest="a" * 64,
            )

        catalog = CapabilityCatalog(
            (
                CapabilityPin(CAPABILITY_EXECUTION, "bt_api_execution", "bt_api_execution", "0.2.0"),
                CapabilityPin(CAPABILITY_RISK, "bt_api_risk", "bt_api_risk", "0.1.0"),
                CapabilityPin(CAPABILITY_MONITOR, "bt_api_monitor", "bt_api_monitor", "0.1.0"),
            ),
            importer=importlib.import_module,
            version_getter=importlib.metadata.version,
        )
        metadata_digest = "d" * 64

        def compose(root, strategy_id, writer_id, lease_ttl_ns=5_000_000_000):
            capabilities = catalog.load(contract(strategy_id))
            execution = capabilities.require(CAPABILITY_EXECUTION)
            risk = capabilities.require(CAPABILITY_RISK)
            monitor = capabilities.require(CAPABILITY_MONITOR)
            state_directory = root / "state"
            state_directory.mkdir(exist_ok=True)
            scope = execution.ExecutionScope(
                provider="iteration41_managed_replay_fake_provider",
                environment="offline",
                account_ref="account.shared",
                strategy_id=strategy_id,
                trading_day="20260922",
            )
            risk_scope = risk.AccountScope(
                provider="fake", environment="offline", account_id="account.shared"
            )

            def map_intent(intent):
                if intent.position_effect.value == "OPEN":
                    if intent.price is None:
                        raise AssertionError("offline opening intent lacks a test price")
                    action = risk.IntentAction.INCREASE
                    notional = intent.quantity * intent.price
                else:
                    action = risk.IntentAction.REDUCE
                    notional = Decimal("0")
                return risk.RiskIntent(
                    intent_id=intent.intent_id,
                    scope=risk_scope,
                    action=action,
                    notional=notional,
                    payload_fingerprint=intent.fingerprint,
                )

            execution_store = execution.SqliteExecutionStore(
                state_directory / "execution.sqlite3"
            )
            fake_authority = ManagedFakeProviderJournalAuthority(
                database_path=state_directory / "fake_dispatch.sqlite3",
                execution_scope=scope,
                risk_scope=risk_scope,
                execution_store=execution_store,
                facade=None,
                risk_types=risk,
                risk_intent_mapper=map_intent,
            )
            risk_gate = risk.DurableRiskGate(
                state_directory / "risk.sqlite3",
                risk.RiskPolicy(
                    policy_id="policy.shared",
                    max_increase_notional=Decimal("100"),
                    max_increase_count=10,
                ),
                execution_journal_authority=fake_authority,
            )
            facade = execution.ManagedExecutionFacade(
                execution_store,
                scope,
                writer_id=writer_id,
                lease_ttl_ns=lease_ttl_ns,
                admission_gate=execution.SharedRiskAdmissionAdapter(risk_gate, map_intent),
            )
            fake_authority.bind_facade(facade)
            return ManagedExecutionRuntime(
                contract=contract(strategy_id),
                facade=facade,
                execution_store=execution_store,
                outbox=monitor.DurableOutbox(state_directory / "monitor.sqlite3"),
                risk_gate=risk_gate,
                risk_scope=risk_scope,
                scope=scope,
                execution=execution,
                outbox_event_type=monitor.OutboxEvent,
                state_directory=state_directory,
                recovery_coordinator=DurableManagedRecoveryCoordinator(
                    state_directory / "managed_recovery.sqlite3"
                ),
                fake_dispatch_authority=fake_authority,
                dispatch_resolution_proof_types=(
                    risk.DispatchTerminalProof,
                    risk.DispatchTrackedOrderProof,
                ),
                simulation_dispatch_evidence_class=risk.DispatchEvidenceClass.SIMULATION_JOURNAL,
            )

        provider_calls = []

        def create_unknown_before_freeze(bridge, order, provider_order_id):
            accepted = bridge.submit_order(
                order,
                lambda _order: (
                    provider_calls.append(("submit", order.info["managed_intent_id"]))
                    or {"status": "accepted", "id": provider_order_id}
                ),
            )
            assert accepted["id"] == provider_order_id

            def crash_after_execution_unknown(_record):
                raise SimulatedProcessCrash("execution journal committed before risk freeze")

            bridge._freeze_unknown_cancellation = crash_after_execution_unknown
            try:
                bridge.cancel_order(
                    order,
                    "fixture/contract",
                    lambda _provider_id, _dataname: (
                        provider_calls.append(("cancel", order.info["managed_intent_id"]))
                        # No target identity means the typed bridge persists
                        # UNKNOWN rather than treating this as a success.
                        or {"status": "accepted"}
                    ),
                )
            except SimulatedProcessCrash:
                return
            raise AssertionError("test fixture failed to simulate the crash window")

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            # Strategy one stays alive after its short writer lease expires.
            # The next writer generation will create an UNKNOWN cancel, then
            # crash before the independent risk freeze is persisted.
            first = compose(root, "strategy.one", "writer.one", lease_ttl_ns=25_000_000)
            try:
                first_bridge = ManagedExecutionBridge(first)
                first_scope = first.scope
                first_initial_lease = first.facade.acquire_writer_lease()
                first_initial_token = first_initial_lease.fencing_token
                time.sleep(0.075)
                try:
                    first.execution_store.assert_writer_lease(first.scope, first_initial_lease)
                except Exception as error:
                    assert type(error).__name__ == "WriterLeaseUnavailableError", repr(error)
                else:
                    raise AssertionError("strategy one writer lease did not expire")

                second = compose(
                    root,
                    "strategy.two",
                    "writer.two",
                    lease_ttl_ns=2_000_000_000,
                )
                try:
                    second_bridge = ManagedExecutionBridge(second)
                    second_order = ManagedOrder("intent.two", "cancel.shared")
                    second_initial_lease = second.facade._last_writer_lease
                    assert second_initial_lease is not None
                    assert second_initial_lease.fencing_token > 0
                    second.execution_store.assert_writer_lease(
                        second.scope, second_initial_lease
                    )

                    create_unknown_before_freeze(
                        second_bridge, second_order, "provider.two"
                    )
                    second_record = second.execution_store.get_cancel(
                        "cancel.shared", scope=second.scope
                    )
                    assert second_record is not None
                    assert second_record.state.value == "UNKNOWN"
                    assert second.risk_gate.active_freeze_reasons(second.risk_scope) == []
                    second_scope = second.scope

                    # Leave the second writer lease row intact, as an abrupt
                    # crash would. After it expires, strategy one must obtain
                    # a later account fencing generation rather than seeing
                    # a reset token from a clean lease release.
                    time.sleep(2.075)

                    # The original bridge is still alive, but its lease
                    # expired before strategy two took ownership. Its next
                    # submit gets the next fencing generation and is rejected
                    # atomically by the Store before provider dispatch.
                    attempted_order = ManagedOrder(
                        "intent.one.after.takeover", "cancel.shared"
                    )
                    try:
                        first_bridge.submit_order(
                            attempted_order,
                            lambda _order: (
                                provider_calls.append(
                                    ("submit", "intent.one.after.takeover")
                                )
                                or {
                                    "status": "accepted",
                                    "id": "provider.one.after.takeover",
                                }
                            ),
                        )
                    except Exception as error:
                        assert type(error).__name__ == "InvalidStateTransitionError", repr(
                            error
                        )
                        assert str(error) == "account has an unresolved managed cancellation"
                    else:
                        raise AssertionError(
                            "unresolved cancellation did not stop submit claim"
                        )

                    first_reacquired_lease = first.facade._last_writer_lease
                    assert first_reacquired_lease is not None
                    assert (
                        first_reacquired_lease.fencing_token
                        > second_initial_lease.fencing_token
                        > first_initial_token
                    )
                    blocked_record = first.execution_store.get(
                        "intent.one.after.takeover", scope=first.scope
                    )
                    assert blocked_record is not None
                    assert blocked_record.state.value == "PENDING_DISPATCH"
                    assert blocked_record.dispatch_attempts == 0
                    assert first.risk_gate.active_freeze_reasons(first.risk_scope) == []
                    assert provider_calls == [
                        ("submit", "intent.two"),
                        ("cancel", "intent.two"),
                    ]
                finally:
                    # The stale process cannot release strategy one’s new
                    # token when its resources eventually close.
                    second.close()

                # Restart still reconstructs the independent account risk
                # freeze from the immutable UNKNOWN cancellation record.
                time.sleep(0.04)
                restarted_second = compose(root, "strategy.two", "writer.two.restarted")
                try:
                    restarted_bridge = ManagedExecutionBridge(restarted_second)
                    first_cause = (
                        "cancel-outcome-unknown:" + second_scope.key + ":cancel.shared"
                    )
                    assert first_cause in restarted_second.risk_gate.active_freeze_reasons(
                        restarted_second.risk_scope
                    )
                    replayed = restarted_bridge.submit_order(
                        ManagedOrder("intent.two.restarted", "cancel.shared"),
                        lambda _order: (
                            provider_calls.append(("submit", "intent.two.restarted"))
                            or {"status": "accepted", "id": "provider.two.restarted"}
                        ),
                    )
                    assert replayed["managed_execution_state"] == "BLOCKED", replayed
                finally:
                    restarted_second.close()

                risk_db = sqlite3.connect(root / "state" / "risk.sqlite3")
                try:
                    reservations = risk_db.execute(
                        "SELECT intent_id, action FROM risk_reservations "
                        "WHERE intent_id LIKE 'cancel-admission:%' ORDER BY intent_id"
                    ).fetchall()
                finally:
                    risk_db.close()
                assert reservations == [
                    ("cancel-admission:" + second_scope.key + ":cancel.shared", "cancel")
                ]
                assert first_scope.key != second_scope.key
                assert (
                    "cancel-admission:" + first_scope.key + ":cancel.shared"
                    != "cancel-admission:" + second_scope.key + ":cancel.shared"
                )
            finally:
                first.close()

        assert provider_calls == [("submit", "intent.two"), ("cancel", "intent.two")]
        assert socket_attempts == []
        print(json.dumps({"provider_calls": len(provider_calls), "state": "ACCOUNT_FENCED"}))
        """
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = iteration41_child_pythonpath(_sdk_sources)
    environment["BT_API_PY_LIGHT_IMPORT"] = "1"

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"provider_calls": 2, "state": "ACCOUNT_FENCED"}
