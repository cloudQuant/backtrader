"""INV64-02: observe a fake direct Broker lifecycle in a fresh interpreter.

UNIT/FAKE in an isolated process: the real Broker, SDK direct coordinator and
local state are exercised with a fake Store, provider and account facts. No
provider or account is contacted. This does not establish isolation of a real
provider session or installed wheel.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_CHILD = textwrap.dedent(
    """
    import importlib
    import importlib.util
    import json
    import socket
    import sys
    import tempfile
    from pathlib import Path

    assert importlib.util.find_spec('bt_api_risk') is not None, 'risk must be importable'
    attempts = []
    connections = []

    def audit(event, args):
        if event == 'import' and args and (args[0] == 'bt_api_risk' or args[0].startswith('bt_api_risk.')):
            attempts.append(args[0])
        if event in ('socket.connect', 'socket.sendto'):
            connections.append(event)
            raise RuntimeError('network access forbidden in direct isolation test')

    sys.addaudithook(audit)
    if sys.argv[1] == 'control':
        # Explicit import tests the same observer, including importlib imports.
        import bt_api_risk
    else:
        import backtrader as bt
        from tests.unit.brokers.direct._fakes import (
            Env, EXCHANGE, native_identity, order_event, trade_event,
        )
        from bt_api_base.direct_write_protocol import (
            DirectOrderReservation, DirectSubmitResult, DirectWriteErrorPolicy, WriteOperation,
        )
        from bt_api_py.direct_write import DirectWriteCoordinator
        from bt_api_py.write_admission import WriteAdmission

        class Provider:
            direct_write_error_policy = DirectWriteErrorPolicy(frozenset(), frozenset())

            def __init__(self, fake_api):
                self.api = fake_api
                self.calls = []
                self.events = []
                self.closed = False

            def account_reference(self):
                return self.api.provider.account_reference()

            def trading_day(self):
                return self.api.trading_day

            def session_generation(self):
                return self.api.session_generation

            def settlement_status(self):
                return self.api.provider.settlement_status()

            def reserve_order(self, request):
                self.calls.append('reserve')
                return DirectOrderReservation(native_identity('000000000001'), request.symbol, 'r1')

            def release_reservation(self, reservation):
                self.calls.append('release')

            def submit_order(self, reservation, request, grant, verifier):
                self.calls.append('submit')
                assert self.port.store.get(self.marker) is not None
                verifier.consume(grant, exchange_name=EXCHANGE, operation=WriteOperation.PLACE,
                                 session_generation=self.session_generation())
                return DirectSubmitResult(sent=True, identity=reservation.identity)

            def drain_execution_events(self, limit):
                out, self.events = self.events[:limit], self.events[limit:]
                return tuple(out)

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as directory:
            env = Env(Path(directory))
            provider = Provider(env.api)
            admission = WriteAdmission({EXCHANGE: True})
            coordinator = DirectWriteCoordinator(admission, lambda _: provider)
            env.api._writes = coordinator
            env.api.write_admission = admission
            env.api.poll_direct_execution_events = coordinator.poll_events

            def place(exchange_name, request, *, pre_dispatch_commit, host_scope, request_summary=None):
                provider.port = pre_dispatch_commit
                class TracedPort:
                    def commit(self, record):
                        provider.calls.append('commit')
                        provider.marker = pre_dispatch_commit.commit(record)
                        return provider.marker
                outcome = coordinator.place(exchange_name, request, commit_port=TracedPort(),
                                            host_scope=host_scope, request_summary=request_summary)
                provider.outcome = outcome
                return outcome
            env.api.make_order = place
            try:
                broker = env.start(first_init=True)
                assert broker._direct_active()
                order = broker.buy(env.strategy, env.feed, 1, price=3500.0,
                                   exectype=bt.Order.Limit, offset='open')
                assert order.status == bt.Order.Submitted
                assert provider.calls == ['reserve', 'commit', 'submit']
                assert provider.outcome.sent is True
                provider.events.append(order_event(provider.outcome.identity, 'accepted', sys_id='1001'))
                broker.next()
                assert order.status == bt.Order.Accepted
                provider.events.append(trade_event('T1', sys_id='1001', qty=1))
                broker.next()
                assert order.status == bt.Order.Completed
                assert broker.getposition(env.feed).size == 1
                assert broker.stop()['status'] == 'STOPPED'
                assert env.store.stop_calls == 1
                coordinator.close()
                assert provider.closed
            finally:
                env.close()
    loaded = sorted(name for name in sys.modules
                    if name == 'bt_api_risk' or name.startswith('bt_api_risk.'))
    print(json.dumps({'attempts': attempts, 'loaded': loaded, 'connections': connections}))
    """
)


def _observe(mode):
    result = subprocess.run(
        [sys.executable, "-c", _CHILD, mode],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.integration
def test_fake_direct_lifecycle_never_imports_risk_or_connects():
    observed = _observe("direct")
    assert observed == {"attempts": [], "loaded": [], "connections": []}


def test_observer_detects_risk_import():
    observed = _observe("control")
    assert "bt_api_risk" in observed["attempts"]
    assert "bt_api_risk" in observed["loaded"]
    assert observed["connections"] == []
