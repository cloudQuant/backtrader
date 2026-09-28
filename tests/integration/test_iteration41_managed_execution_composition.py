"""Local composition acceptance for the Iteration 41 managed Store route.

This is deliberately a subprocess integration test. The Backtrader checkout
does not import optional SDK packages during ordinary runtime-config validation;
the test combines local SDK sources only after resolving an exact offline fake
replay contract. The provider is a no-network fake.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


from tests.test_utils.iteration41_source_roots import (
    iteration41_child_pythonpath,
    iteration41_source_paths,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _require_sdk_sources() -> tuple[str, ...]:
    return iteration41_source_paths("parent", "base", "execution", "risk", "monitor")


def test_resolved_managed_config_composes_real_durability_before_one_store_provider_call() -> None:
    _sdk_sources = _require_sdk_sources()
    script = textwrap.dedent(
        """
        import importlib
        import json
        import socket
        import ssl
        import tempfile
        import time
        from decimal import Decimal
        from pathlib import Path
        from types import SimpleNamespace

        attempts = []

        class DeniedSocket(socket.socket):
            def connect(self, *args, **kwargs):
                attempts.append((args, kwargs))
                raise AssertionError("the managed composition acceptance test must stay offline")

            def connect_ex(self, *args, **kwargs):
                attempts.append((args, kwargs))
                raise AssertionError("the managed composition acceptance test must stay offline")

        socket.socket = DeniedSocket

        from backtrader.order import OrderBase
        from backtrader.stores.btapistore import BtApiStore
        from backtrader_runtime import (
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
            CapabilityCatalog,
            CapabilityPin,
            RuntimeCapabilityContract,
            SealedNormalizedInstrumentMetadataSnapshot,
            compose_managed_execution,
        )

        class NoNetworkApi:
            def __init__(self):
                self.submissions = []

            def get_balance(self):
                return {"cash": 100.0, "value": 100.0}

            def submit_order(self, payload):
                self.submissions.append(dict(payload))
                return {"status": "accepted", "id": "provider.41"}

        class ExplicitLimitOrder:
            ref = 41
            exectype = OrderBase.Limit
            size = 2
            price = 10.25
            pricelimit = None
            valid = None
            tradeid = 0
            data = SimpleNamespace(_name="fixture/contract")
            created = SimpleNamespace(price=10.25)
            def __init__(self, intent_id="intent.41"):
                self.info = {
                    "managed_order_type": "LIMIT",
                    "managed_intent_id": intent_id,
                    "managed_signal_id": "signal." + intent_id,
                    "managed_instrument": "fixture/contract",
                    "managed_position_effect": "OPEN",
                    "managed_metadata_version": "metadata.1",
                    "managed_instrument_metadata_digest": metadata_digest,
                    "offset": "open",
                    "reduce_only": False,
                }

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
                "  id: example.013_3.sa_midfreq_simnow\\n"
                "runtime:\\n"
                "  mode: simulation\\n"
                "  preset: replay\\n"
                "parameters: {}\\n"
                "secrets_ref: none\\n",
                encoding="utf-8",
            )
            registry = RuntimeRegistry(
                (
                    RegisteredRuntime(
                        runtime_dir=runtime_dir,
                        strategy_id="example.013_3.sa_midfreq_simnow",
                        allowed_presets=("replay",),
                        allowed_secrets_refs=("none",),
                        offline_managed_execution=True,
                        available_capabilities=(
                            CAPABILITY_EXECUTION,
                            CAPABILITY_RISK,
                            CAPABILITY_MONITOR,
                        ),
                    ),
                )
            )
            effective = resolve_runtime_config(load_runtime_config(runtime_dir, registry=registry), registry)
            contract = RuntimeCapabilityContract.from_effective_public_dict(effective.as_public_dict())
            catalog = CapabilityCatalog(
                (
                    CapabilityPin(CAPABILITY_EXECUTION, "bt_api_execution", "bt_api_execution", "0.1.0"),
                    CapabilityPin(CAPABILITY_RISK, "bt_api_risk", "bt_api_risk", "0.1.0"),
                    CapabilityPin(CAPABILITY_MONITOR, "bt_api_monitor", "bt_api_monitor", "0.1.0"),
                ),
                importer=importlib.import_module,
                version_getter=lambda _distribution: "0.1.0",
            )
            metadata_snapshot = SealedNormalizedInstrumentMetadataSnapshot.from_normalized_payload(
                {
                    "provider": "iteration41_managed_replay_fake_provider",
                    "environment": "offline",
                    "account_ref": "iteration41_managed_replay_fake_account",
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
                            "max_gross_notional_account": "100",
                            "quote_currency": "USD",
                            "fee_currency": "USD",
                            "quote_to_account_fx": "1",
                            "fee_to_account_fx": "1",
                            "taker_fee_bps": "0",
                            "fixed_fee": "0",
                            "max_slippage_bps": "0",
                            "min_quantity": "1",
                            "max_quantity": "5",
                            "quantity_unit": "contracts",
                        }
                    ],
                }
            )
            metadata_digest = metadata_snapshot.instrument_digest("fixture/contract")
            managed = compose_managed_execution(
                catalog.load(contract),
                state_directory=root / "state",
                provider="iteration41_managed_replay_fake_provider",
                environment="offline",
                account_ref="iteration41_managed_replay_fake_account",
                strategy_id=effective.strategy_id,
                writer_id="writer.41",
                policy_id="iteration41.managed_replay.l2",
                max_increase_notional=Decimal("100"),
                max_increase_count=5,
                permit_ttl_seconds=1.0,
                trading_day="20260922",
                instrument_metadata_snapshot=metadata_snapshot,
                instrument_clock_ns=lambda: 1_750_000_000_000_000_000,
            )
            try:
                api = NoNetworkApi()
                store = BtApiStore(provider="btapi", api=api)
                bind_managed_execution(store, effective, managed)

                first = store.submit_order(ExplicitLimitOrder())
                repeated = store.submit_order(ExplicitLimitOrder())
                record = managed.execution_store.get("intent.41", scope=managed.scope)
                pending = managed.outbox.read_pending("observer.41", managed.scope.key)

                assert first == {"status": "accepted", "id": "provider.41"}, first
                assert repeated == {
                    "status": "accepted",
                    "id": "provider.41",
                    "managed_execution_replayed": True,
                    "managed_execution_state": "ACKED",
                }
                assert len(api.submissions) == 1
                assert api.submissions[0]["order_type"] == "limit"
                assert api.submissions[0]["price"] == 10.25
                assert record is not None and record.state.value == "ACKED"
                assert len(pending) == 1
                assert pending[0].event.data["intent_id"] == "intent.41"

                class UncertainApi(NoNetworkApi):
                    def submit_order(self, payload):
                        self.submissions.append(dict(payload))
                        # The legacy Store path made one request but cannot
                        # prove acceptance without a provider order identity.
                        return {"status": "accepted"}

                uncertain_api = UncertainApi()
                uncertain_store = BtApiStore(provider="btapi", api=uncertain_api)
                bind_managed_execution(uncertain_store, effective, managed)
                unknown = uncertain_store.submit_order(ExplicitLimitOrder("intent.unknown"))
                time.sleep(1.1)
                blocked = uncertain_store.submit_order(ExplicitLimitOrder("intent.blocked"))

                assert unknown["execution_unknown"] is True
                assert unknown["managed_execution_state"] == "UNKNOWN"
                assert "dispatch-inflight:intent.unknown" in managed.risk_gate.active_freeze_reasons(
                    managed.risk_scope
                )
                assert blocked["managed_execution_state"] == "BLOCKED"
                assert len(uncertain_api.submissions) == 1
            finally:
                managed.close()

        assert attempts == []
        print(json.dumps({"provider_submissions": 1, "state": "ACKED", "outbox_events": 1}))
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
    assert json.loads(completed.stdout) == {
        "provider_submissions": 1,
        "state": "ACKED",
        "outbox_events": 1,
    }
