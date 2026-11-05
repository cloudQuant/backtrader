"""Iteration 62 (62.08): place and cancel through the managed service route.

The BT-via-Gateway order path is the iteration-60 ``ServiceExecutionSession``:
``run_configured_cerebro`` sends each order as one typed command
(``command_binding``) over CURVE to a spawned SDK ``ServiceHost`` whose
execution ``account_owner`` dispatches to a provider. Here the provider is the
iteration-60 synthetic one (accepts submits and cancels; never touches a venue).
The Strategy places a limit buy and cancels it once Accepted; the cancel must
leave through the same service route (no direct facade write), and the Strategy
must see ``Accepted -> Canceled`` for that order.

Test seam (same as ``test_iter60_service_session_cerebro_curve``): the
SDK-mode Store's direct account reads report a proven-flat account; a real
deployment needs a facade with provider account ports, which for CTP via
Gateway does not exist yet (iteration 62 report, GAP list).

INTEGRATION_SIM: spawned local host, temp SQLite, CURVE on 127.0.0.1; no real
account, provider, CTP front or network.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("zmq")
pytest.importorskip("msgpack")
pytest.importorskip("bt_api_execution")
pytest.importorskip("bt_api_py.service_strategy_ledger_host")

import backtrader as bt  # noqa: E402
from backtrader.service.service_execution_session import run_configured_cerebro  # noqa: E402
from tests.integration.test_iter60_service_session_cerebro_curve import (  # noqa: E402
    _FlatAccountStore,
    _NoDirectWriteFacade,
    _support,
)


class _PlaceThenCancel(bt.Strategy):
    """Place one far limit buy; cancel it once the service accepted it."""

    params = (("host", None),)

    def __init__(self):
        self.statuses = []
        self.intents = []
        self.order = None
        self.stage = "place"

    def next(self):
        if self.stage == "place":
            self.stage = "placed"
            self.order = self.buy(
                size=1,
                price=float(self.data.close[0]) - 100.0,
                exectype=bt.Order.Limit,
                managed_intent_id="bt-iter62-cancel-1",
                managed_signal_id="signal-bt-iter62-cancel-1",
                managed_instrument=_support().INSTRUMENT,
                managed_position_effect="OPEN",
                managed_metadata_version="bt-r2e-metadata-v1",
            )
        elif self.stage in {"placed", "cancelling"}:
            # Live bars are spaced in wall-clock time; let the session's
            # refresh loop run while the order is outstanding (test pacing).
            time.sleep(0.02)

    def notify_order(self, order):
        self.statuses.append(order.getstatusname())
        if order.status == order.Accepted and self.stage == "placed":
            self.intents.append(order.info.get("managed_intent_id"))
            self.stage = "cancelling"
            self.cancel(order)
            # The cancel request left through the service (the synthetic
            # provider accepted it); the venue's terminal report is then
            # driven on the host, as a real provider callback would be.
            self.p.host.command(
                "fill", order.info.get("managed_intent_id"), "CANCELLED", "0", None, None
            )
        elif order.status == order.Canceled:
            self.stage = "done"


@pytest.mark.integration
def test_limit_order_is_placed_and_cancelled_through_the_service_route(tmp_path):
    t = _support()
    host = t.Host(tmp_path)
    assert host.ready[0] == "ready", host.ready
    facade = _NoDirectWriteFacade()
    strategy = None
    try:
        csv_path = tmp_path / "bars.csv"
        csv_path.write_text(
            "".join(
                f"2026-{10 + day // 28}-{1 + day % 28:02d},50000,50010,49990,50000,1\n"
                for day in range(40)
            ),
            encoding="ascii",
        )
        store = _FlatAccountStore(
            provider="okx", api=facade, cash=0.0, value=0.0, autostart=False
        )
        broker = store.getbroker(
            cash=0.0,
            value=0.0,
            validation_enabled=False,
            cash_check_enabled=False,
            flatten_on_stop=False,
            sdk_preflight=False,
        )
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.setbroker(broker)
        cerebro.adddata(
            bt.feeds.GenericCSVData(
                dataname=str(csv_path),
                headers=False,
                dtformat="%Y-%m-%d",
                datetime=0,
                open=1,
                high=2,
                low=3,
                close=4,
                volume=5,
                openinterest=-1,
            ),
            name=t.INSTRUMENT,
        )
        cerebro.addstrategy(_PlaceThenCancel, host=host)
        results = run_configured_cerebro(
            cerebro,
            t.client_config(host.endpoint),
            runtime_factory=t.runtime_factory(host.keys),
            session_options={"refresh_interval_seconds": 0.05},
            runonce=False,
            preload=False,
        )
        (strategy,) = results
        assert strategy.intents == ["bt-iter62-cancel-1"], strategy.statuses
        # The managed route answers the submit with the durable record
        # (Accepted); the cancel request stays pending until the execution
        # owner's durable record reports CANCELLED (Canceled). No UNKNOWN.
        assert strategy.statuses == ["Accepted", "Canceled"], strategy.statuses
        (order,) = broker.orders.values()
        assert order.ref == strategy.order.ref
        assert order.status == bt.Order.Canceled
        assert order.info.get("external_order_id") == "provider-bt-iter62-cancel-1"
        assert order.info.get("execution_unknown") in (None, False)
        assert order.info.get("cancel_error_code") in (None, "")
        assert strategy.getposition(strategy.data).size == 0
        assert facade.direct_writes == 0  # place and cancel both went through the service
    finally:
        submitted = host.close()
    assert submitted == ["bt-iter62-cancel-1"]
