"""Current strategy-stream role boundary with a synthetic local event.

This uses a temporary journal and local fixture identities, not real transport,
authentication, a provider, or an account. It does not prove a future
Execution service has an authorized event stream or independent cursor.
"""

from dataclasses import replace
from pathlib import Path
import sys

import pytest

from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus, NativeOrderIdentity
from bt_api_base.gateway_execution_protocol import GatewayReturnFact
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_gateway.direct_command_journal import GatewayDirectCommandJournal
from bt_api_gateway.direct_execution_journal import GatewayDirectExecutionLedger
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py.gateway_execution_stream_service import GatewayExecutionStreamService
from bt_api_py.service_registry import ServiceCallContext


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    yield
    root = Path(__file__).resolve().parents[3]
    assert root.name == "wt-iter65"
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(root):
                escaped[name] = source
    assert not escaped, escaped


def test_strategy_stream_rejects_service_role_for_progress_read_and_ack(tmp_path):
    directory = tmp_path / "guard"
    directory.mkdir()
    account, strategy, principal = "synthetic-account", "synthetic-strategy", "synthetic-principal"
    guard = LocalAccountSessionGuard(directory, account, "synthetic-owner")
    generation = guard.acquire()
    stream = None
    try:
        journal = GatewayDirectCommandJournal.create(tmp_path / "journal.sqlite", account, generation=generation)
        ledger = GatewayDirectExecutionLedger(journal, guard)
        row = journal.reserve(strategy, "request-1", principal,
                              {"symbol": "rb2601", "side": "buy", "offset": "open", "quantity": "2"})
        native = {"exchange_name": "CTP", "client_order_id": "request-1",
                  "session_generation": 1, "fields_json": "{}"}
        journal.begin_dispatch(strategy, "request-1", row.reservation_id, row.digest, principal,
                               row.version, native, ("synthetic-anchor",))
        fact = GatewayReturnFact(
            account, "CTP", MarketInstrumentKey("ctp", "SHFE", "synthetic", "future", "rb2601", "rb2601"),
            "20300101", DirectExecutionEventKind.ORDER, "synthetic-source",
            identity=NativeOrderIdentity("CTP", "request-1", {"trading_day": "20300101"}, 1),
            identity_keys=("synthetic-anchor", "synthetic-venue"), binding_keys=("synthetic-anchor",),
            venue_key="synthetic-venue", status=DirectOrderStatus.ACCEPTED, side="buy", offset="open",
        )
        result = ledger.ingest(fact)
        assert result.disposition == "ATTRIBUTED"
        assert len(ledger.read_events(strategy)) == 1
        stream = GatewayExecutionStreamService(ledger, journal, {principal: strategy},
                                               execution_domain_ref="synthetic-domain")
        identity = WireIdentity(WireRole.STRATEGY_CLIENT, principal, strategy)
        context = ServiceCallContext(identity, WireScope("synthetic-domain", account_ref=account,
                                                        strategy_ref=strategy, run_id="synthetic-run"),
                                     "synthetic-registration", principal, lambda _: True)
        service_context = replace(context, identity=replace(identity, role=WireRole.SERVICE))
        assert replace(service_context, identity=identity) == context

        def invoke(operation, arguments, call_context):
            return stream.handle("direct.events." + operation, context=call_context, arguments=arguments)

        initial = invoke("progress", {}, context)
        assert initial["status"] == "OK"
        assert initial["progress"]["offered_sequence"] == 0
        assert invoke("progress", {}, service_context) == {"status": "REQUEST_REJECTED", "code": "SCOPE_DENIED"}

        read_arguments = {"after_sequence": 0, "expected_epoch": None, "limit": 256}
        assert invoke("read_after", read_arguments, service_context) == {"status": "REQUEST_REJECTED", "code": "SCOPE_DENIED"}
        page = invoke("read_after", read_arguments, context)
        assert page["status"] == "OK"
        events = page["page"]["events"]
        assert len(events) == 1 and events[0]["request_key"] == "request-1"
        sequence, epoch = events[0]["sequence"], page["page"]["epoch"]
        ack_arguments = {"sequence": sequence, "expected_epoch": epoch}
        assert invoke("ack", ack_arguments, service_context) == {"status": "REQUEST_REJECTED", "code": "SCOPE_DENIED"}
        before_ack = invoke("progress", {}, context)
        assert before_ack["progress"]["acknowledged_sequence"] == 0
        accepted = invoke("ack", ack_arguments, context)
        assert accepted["status"] == "OK"
        assert accepted["progress"]["acknowledged_sequence"] == sequence
    finally:
        if stream is not None:
            stream.close()
        guard.release()
