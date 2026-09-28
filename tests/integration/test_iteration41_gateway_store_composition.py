"""Local gateway composition acceptance through the real Backtrader Store bridge.

The test starts an inproc ZMQ gateway authority only.  It never connects to a
provider: the server's provider port is a local typed fake and the Store's
legacy provider callback raises if the gateway client attempts to invoke it.
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
    return iteration41_source_paths(
        "parent", "base", "execution", "risk", "monitor", "gateway", "transport_zmq"
    )


def test_gateway_client_store_path_never_invokes_legacy_provider_dispatch() -> None:
    """Config seal → Store bridge → ZMQ client → server authority → one fake provider call."""

    _sdk_sources = _require_sdk_sources()
    script = textwrap.dedent(
        """
        import importlib
        import json
        import sqlite3
        import tempfile
        import threading
        import uuid
        from decimal import Decimal
        from pathlib import Path
        from types import SimpleNamespace

        import zmq

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
            CAPABILITY_GATEWAY,
            CAPABILITY_MONITOR,
            CAPABILITY_RISK,
            CAPABILITY_TRANSPORT_ZMQ,
            CapabilityCatalog,
            CapabilityPin,
            RuntimeCapabilityContract,
            SealedNormalizedInstrumentMetadataSnapshot,
            compose_gateway_execution_authority,
            compose_gateway_managed_client,
        )

        class NoDirectProviderApi:
            def __init__(self):
                self.direct_submit_calls = []
                self.direct_cancel_calls = []

            def get_balance(self):
                return {"cash": 100.0, "value": 100.0}

            def submit_order(self, payload):
                self.direct_submit_calls.append(dict(payload))
                raise AssertionError("gateway route must not call BtApiStore legacy provider dispatch")

            def cancel_order(self, order_ref, dataname=None):
                self.direct_cancel_calls.append((order_ref, dataname))
                raise AssertionError("gateway route must not call BtApiStore legacy provider cancel")

        class ExplicitLimitOrder:
            ref = 411
            exectype = OrderBase.Limit
            size = 2
            price = 10.25
            pricelimit = None
            valid = None
            tradeid = 0
            data = SimpleNamespace(_name="fixture/contract")
            created = SimpleNamespace(price=10.25)

            def __init__(self):
                self.info = {
                    "managed_order_type": "LIMIT",
                    "managed_intent_id": "intent.gateway.411",
                    "managed_signal_id": "signal.gateway.411",
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
                "  id: example.014_1.ctp_options_lowfreq\\n"
                "runtime:\\n"
                "  mode: live\\n"
                "  preset: managed_live_gateway\\n"
                "parameters: {}\\n"
                "secrets_ref: runtime_secrets\\n",
                encoding="utf-8",
            )
            capabilities = (
                CAPABILITY_EXECUTION,
                CAPABILITY_RISK,
                CAPABILITY_MONITOR,
                CAPABILITY_GATEWAY,
                CAPABILITY_TRANSPORT_ZMQ,
            )
            registry = RuntimeRegistry(
                (
                    RegisteredRuntime(
                        runtime_dir=runtime_dir,
                        strategy_id="example.014_1.ctp_options_lowfreq",
                        allowed_presets=("managed_live_gateway",),
                        allowed_secrets_refs=("runtime_secrets",),
                        available_capabilities=capabilities,
                        approval_receipt_digest="a" * 64,
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
                    CapabilityPin(CAPABILITY_GATEWAY, "bt_api_gateway", "bt_api_gateway", "0.1.0"),
                    CapabilityPin(
                        CAPABILITY_TRANSPORT_ZMQ,
                        "bt_api_transport_zmq",
                        "bt_api_transport_zmq",
                        "0.1.0",
                    ),
                ),
                importer=importlib.import_module,
                version_getter=lambda _distribution: "0.1.0",
            )
            loaded = catalog.load(contract)
            execution = loaded.require(CAPABILITY_EXECUTION)
            gateway = loaded.require(CAPABILITY_GATEWAY)
            transport = loaded.require(CAPABILITY_TRANSPORT_ZMQ)
            metadata_snapshot = SealedNormalizedInstrumentMetadataSnapshot.from_normalized_payload(
                {
                    "provider": "fixture_provider",
                    "environment": "production",
                    "account_ref": "account.411",
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
            server_provider_calls = []
            server_state_directory = root / "server"
            server_state_directory.mkdir()
            writer_authority = gateway.GatewayAccountWriterAuthority(
                server_state_directory / "gateway_router.sqlite3"
            )

            def server_provider(intent):
                server_provider_calls.append(intent.intent_id)
                return execution.ProviderObservation.accepted(intent.intent_id, "gateway.provider.411")

            authority = compose_gateway_execution_authority(
                loaded,
                state_directory=server_state_directory,
                provider="fixture_provider",
                environment="production",
                account_ref="account.411",
                strategy_id=effective.strategy_id,
                writer_id="gateway.server.411",
                policy_id="gateway.policy.411",
                max_increase_notional=Decimal("100"),
                    max_increase_count=1,
                    provider_dispatch=server_provider,
                    server_admission=lambda _principal, _command: True,
                    writer_authority=writer_authority,
                    trading_day="20260922",
                    instrument_metadata_snapshot=metadata_snapshot,
                    instrument_clock_ns=lambda: 1_750_000_000_000_000_000,
            )
            writer_authority.acquire_writer(
                authority.scope.account_key, "gateway.server.411", lease_seconds=60.0
            )
            principal = gateway.GatewayPrincipal(
                principal_id="server-derived-fixture-principal",
                account_scopes=frozenset({authority.scope.account_key}),
                strategy_scopes=frozenset({authority.scope.key}),
                allowed_kinds=frozenset({gateway.GatewayCommandKind.SUBMIT}),
            )
            context = zmq.Context()
            endpoint = "inproc://iteration41-store-gateway-" + uuid.uuid4().hex
            server = authority.create_zmq_server(
                endpoint,
                lambda _peer, _message: principal,
                context=context,
            )
            client = transport.ZmqCommandClient(endpoint, context=context)
            managed = compose_gateway_managed_client(
                loaded,
                state_directory=root / "client",
                provider="fixture_provider",
                environment="production",
                account_ref="account.411",
                strategy_id=effective.strategy_id,
                    writer_id="gateway.client.411",
                    client=client,
                    trading_day="20260922",
                    instrument_metadata_snapshot=metadata_snapshot,
                    instrument_clock_ns=lambda: 1_750_000_000_000_000_000,
                )
            api = NoDirectProviderApi()
            store = BtApiStore(provider="btapi", api=api)
            bind_managed_execution(store, effective, managed)
            worker = threading.Thread(target=lambda: server.serve_once(timeout_ms=2_000))
            worker.start()
            try:
                response = store.submit_order(ExplicitLimitOrder())
                worker.join(timeout=5)
                assert not worker.is_alive()
                assert response["status"] == "submitted"
                assert response["execution_unknown"] is True
                assert response["error_code"] == "dispatch_outcome_unknown"
                assert response["managed_execution_state"] == "UNKNOWN"
                assert response["managed_execution_replayed"] is True
                assert api.direct_submit_calls == []
                assert server_provider_calls == ["intent.gateway.411"]
                record = managed.execution_store.get("intent.gateway.411", scope=managed.scope)
                assert record is not None and record.state.value == "UNKNOWN"
                server_record = authority.server_runtime.execution_store.get(
                    "intent.gateway.411", scope=authority.scope
                )
                assert server_record is not None and server_record.state.value == "ACKED"
                server_freezes = authority.server_runtime.risk_gate.active_freeze_reasons(
                    authority.server_runtime.risk_scope
                )
                assert "dispatch-inflight:intent.gateway.411" in server_freezes
                repeated_response = store.submit_order(ExplicitLimitOrder())
                assert repeated_response["status"] == "submitted"
                assert repeated_response["execution_unknown"] is True
                assert repeated_response["managed_execution_state"] == "UNKNOWN"
                assert server_provider_calls == ["intent.gateway.411"]
                assert "dispatch-inflight:intent.gateway.411" in (
                    authority.server_runtime.risk_gate.active_freeze_reasons(
                        authority.server_runtime.risk_scope
                    )
                )
                connection = sqlite3.connect(root / "server" / "gateway_router.sqlite3")
                try:
                    router_statuses = connection.execute(
                        "SELECT status FROM gateway_commands"
                    ).fetchall()
                finally:
                    connection.close()
                assert router_statuses == [("unknown",)]
                try:
                    store.cancel_order(ExplicitLimitOrder())
                except Exception as error:
                    assert "MANAGED_GATEWAY_CANCEL_NOT_IMPLEMENTED" in str(error)
                else:
                    raise AssertionError("gateway cancellation must stay fail-closed")
                assert api.direct_cancel_calls == []
            finally:
                managed.close()
                client.close()
                server.close()
                authority.close()
                context.term()

        print(
            json.dumps(
                {
                    "direct_store_submit_calls": 0,
                    "direct_store_cancel_calls": 0,
                    "server_provider_calls": 1,
                    "client_execution_state": "UNKNOWN",
                    "gateway_command_state": "UNKNOWN",
                }
            )
        )
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
        "direct_store_submit_calls": 0,
        "direct_store_cancel_calls": 0,
        "server_provider_calls": 1,
        "client_execution_state": "UNKNOWN",
        "gateway_command_state": "UNKNOWN",
    }
