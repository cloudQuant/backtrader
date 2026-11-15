"""65.01: non-venue transfer representability, not transfer implementation.

Two independent BT strategy consumers, real Gateway stream clients and real
local checkpoints, with no commands, native identities, trades, networking or
provider/account authority. The current SDK has no internal-transfer event
kind. A failed attempt to construct one is not an event delivery, and the
empty-checkpoint experiments cannot prove transfer atomicity or replay.
"""

import sys
from dataclasses import fields
from pathlib import Path

import pytest

import backtrader
import bt_api_base
import bt_api_py
from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import (
    GatewayExecutionObservation,
    GatewayExecutionStreamEvent,
    GatewayExecutionStreamProtocolError,
    gateway_execution_consumer_ref,
)
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py.gateway_direct_client import GatewayClientRoute
from bt_api_py.gateway_execution_stream_client import (
    GatewayExecutionReadContext, GatewayExecutionStreamClientResult,
)
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_stream_consumer import INSTRUMENT, api_for, framework
from tests.unit.live_state.test_gateway_execution_checkpoint import page

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    for module in (backtrader, bt_api_base, bt_api_py):
        assert Path(module.__file__).resolve().is_relative_to(ROOT), module.__file__
    yield
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(ROOT):
                escaped[name] = source
    assert not escaped, f"non-worktree modules: {escaped}"


@pytest.fixture
def consumers(tmp_path, monkeypatch):
    """Separate strategy hosts because the current BT stream binds one strategy."""
    import backtrader.brokers._btapi_gateway_stream as stream_module
    monkeypatch.setattr(stream_module, "_IDLE_READ_INTERVAL_SECONDS", 0.0)
    result = []
    for label in ("a", "b"):
        directory = tmp_path / label
        directory.mkdir()
        state = StrategyStateDir.initialize(directory)
        strategy_ref, principal = "strategy-" + label, "principal-" + label
        binding = GatewayCommandBinding("journal-" + label, "synthetic-account", strategy_ref, principal)
        route = GatewayClientRoute("broker.direct_write", "service", "instance", "scope",
            WireScope("synthetic-domain", account_ref="synthetic-account", strategy_ref=strategy_ref,
                      run_id="run-" + label),
            WireIdentity(WireRole.STRATEGY_CLIENT, principal, strategy_ref))
        GatewayPendingHost.upgrade_for_gateway(directory, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(directory, state.strategy_uuid, binding,
                                                     max_cancel_entries=10)
        consumer = gateway_execution_consumer_ref(principal_ref=principal, actor_ref=strategy_ref,
            execution_domain_ref="synthetic-domain", account_scope="synthetic-account",
            strategy_scope=strategy_ref)
        host = GatewayPendingHost.upgrade_for_execution(directory, state.strategy_uuid, binding,
                                                         consumer_ref=consumer)
        api = api_for(host, route)
        stream = api.gateway_execution_stream("CTP___FUTURE")
        calls = []
        def read(after, epoch, limit, *, timeout_seconds, binding=binding, consumer=consumer, calls=calls):
            calls.append((after, epoch))
            return GatewayExecutionStreamClientResult("OBSERVED", page=page(binding, consumer),
                request_context=GatewayExecutionReadContext(binding, consumer, after, epoch, limit))
        def unexpected_ack(*args, **kwargs):
            raise AssertionError("empty stream must not acknowledge an event")
        monkeypatch.setattr(stream, "read_after", read)
        monkeypatch.setattr(stream, "ack", unexpected_ack)
        data, broker, strategy = framework()
        broker.bind_gateway_execution_stream(strategy, api=api, host=host,
            data_by_ref={"rb": data}, orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"))
        result.append((state, binding, consumer, host, broker, strategy, calls))
    return result


def test_independent_empty_checkpoints_and_restart_are_not_transfer_atomicity(consumers):
    a, b = consumers
    assert a[2] != b[2] and a[1].strategy_scope != b[1].strategy_scope
    b_before = b[3].load_execution_checkpoint()
    a[4].next()
    assert a[6] and not b[6]
    assert b[3].load_execution_checkpoint() == b_before
    b[4].next()
    for state, binding, _, host, broker, strategy, calls in consumers:
        checkpoint = host.load_execution_checkpoint()
        assert checkpoint.stored_sequence == checkpoint.applied_sequence == 0
        assert checkpoint.acknowledged_sequence == 0
        assert broker.positions["rb"].size == 0
        assert strategy.events == [] and calls
        reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
        assert reopened.load_execution_checkpoint() == checkpoint
        assert reopened.read_execution_events() == ()


def test_non_venue_transfer_has_no_sdk_observation_kind_for_either_consumer(consumers):
    assert {kind.value for kind in DirectExecutionEventKind} == {
        "order", "trade", "order_error", "cancel_error"
    }
    for _, binding, _, host, broker, strategy, _ in consumers:
        before = host.load_execution_checkpoint()
        # Candidate type explicitly says internal_transfer; it is not recast as
        # TRADE, and carries no venue ID, fake execution ID or authority.
        with pytest.raises(GatewayExecutionStreamProtocolError, match="INVALID_STREAM"):
            GatewayExecutionObservation(account_scope=binding.account_scope, route="CTP___FUTURE",
                instrument=INSTRUMENT, trading_day="20261108", kind="internal_transfer",
                side="buy" if binding.strategy_scope.endswith("a") else "sell")
        assert host.load_execution_checkpoint() == before
        assert broker.positions["rb"].size == 0 and strategy.events == []


def test_current_stream_contract_has_no_transfer_source_or_shared_id_fields():
    """Static schema boundary; it does not test SDK extensions or future contracts."""
    observation_fields = {item.name for item in fields(GatewayExecutionObservation)}
    event_fields = {item.name for item in fields(GatewayExecutionStreamEvent)}
    for name in ("transfer_id", "transfer_source", "source_ref", "origin", "counterparty_strategy", "transfer_legs"):
        assert name not in observation_fields and name not in event_fields


def test_existing_envelope_requires_command_even_for_legitimate_nontrade_observation(consumers):
    """This ORDER object is a contract control, not a transfer or a venue fact."""
    for _, binding, _, host, broker, strategy, _ in consumers:
        before = host.load_execution_checkpoint()
        observation = GatewayExecutionObservation(account_scope=binding.account_scope,
            route="CTP___FUTURE", instrument=INSTRUMENT, trading_day="20261108",
            kind=DirectExecutionEventKind.ORDER, status=DirectOrderStatus.UNKNOWN)
        assert observation.native_identity_digest is None and observation.trade_key_digest is None
        with pytest.raises(GatewayExecutionStreamProtocolError, match="INVALID_STREAM"):
            GatewayExecutionStreamEvent(sequence=1, request_key=None, reservation_id=None,
                command_digest=None, command_principal=None, fact_digest=None, observation=observation)
        assert host.load_execution_checkpoint() == before
        assert broker.positions["rb"].size == 0 and strategy.events == []
