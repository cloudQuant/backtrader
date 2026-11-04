"""Iteration 60 (P1-3): the ServiceExecutionSession / Cerebro run loop over CURVE.

``run_configured_cerebro`` runs an ordinary Cerebro whose Strategy buys once.
The order leaves through the configured execution session as one typed
command (``command_binding``) to a spawned SDK ``ServiceHost`` (real CURVE/ZMQ,
strict MessagePack envelopes, host-owned strategy ledger). The host's
synthetic provider accepts it; the test then drives the fill on the host and
the session's managed-order refresh loop brings it back into the Broker, so
the Strategy sees Accepted -> Completed for a buy and the closing sell, and the
session closes
its runtime cleanly.

This test found and covers two iteration-53 regressions: ``BtApiBroker`` had
lost ``refresh_managed_orders`` (every session failed ``BROKER_CANNOT_REFRESH``)
and ``BtApiStore`` had lost ``uses_async_commands`` (every SDK-mode start failed
with ``AttributeError``).

Test seam, stated plainly: direct provider account reads of the SDK-mode Store
(balances, positions, open orders, account-risk baseline, the startup and
shutdown reconciliations, instrument rules and affordability) need a real SDK facade with provider ports; here a test-only
``BtApiStore`` subclass reports a proven-flat empty account instead. Those
reads are covered by their own tests; this one covers the session path.
INTEGRATION_SIM: local subprocess, temp SQLite, CURVE on 127.0.0.1; no real
account, provider or network.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("zmq")
pytest.importorskip("msgpack")
pytest.importorskip("bt_api_execution")
pytest.importorskip("bt_api_py.service_strategy_ledger_host")

import backtrader as bt  # noqa: E402
from backtrader.service.service_execution_session import run_configured_cerebro  # noqa: E402
from backtrader.stores.btapistore import BtApiStore  # noqa: E402

_HERE = Path(__file__).resolve().parent


def _support():
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    import iter60_service_ledger_host_support as support

    return support


class _NoDirectWriteFacade:
    """Unified-facade call shape for market/account plumbing; never writes."""

    def __init__(self) -> None:
        self.closed = False
        self.direct_writes = 0

    def list_exchanges(self):
        return ["OKX___SWAP"]

    async def async_make_order(self, exchange_name, request, *, normalized=True,
                               budget_capability=None):
        self.direct_writes += 1
        raise RuntimeError("NO_DIRECT_WRITES")

    async def async_cancel_order(self, exchange_name, request, *, normalized=True,
                                 budget_capability=None):
        self.direct_writes += 1
        raise RuntimeError("NO_DIRECT_WRITES")

    async def async_query_order(self, exchange_name, request, *, normalized=True):
        raise RuntimeError("NO_DIRECT_QUERIES")

    def poll_events(self, exchange_name, *, max_raw_items=None,
                    coalesce_market_snapshots=("orderbook", "tick")):
        return []

    def close(self):
        self.closed = True


_IDENTITY = hashlib.sha256(b"synthetic-flat-account").hexdigest()


class _FlatAccountStore(BtApiStore):
    """Test seam: the direct account reads report a proven-flat empty account."""

    def get_balance(self, *args, **kwargs):
        self._cash, self._value = 0.0, 0.0
        return {"cash": 0.0, "value": 0.0}

    def get_positions(self, *args, **kwargs):
        return []

    def get_open_orders(self, *args, **kwargs):
        return []

    def fetch_open_orders(self, *args, **kwargs):
        return []

    def _read_account_risk_snapshot(self, api, **_kwargs):
        return {
            "evidence_complete": True,
            "durable": True,
            "trading_blocked": False,
            "identity_binding_sha256": _IDENTITY,
        }

    # Instrument rules and affordability come from the direct SDK facade in a
    # real deployment; the seam accepts them (open for a buy, close for a sell).
    def evaluate_order_rules(self, order, **_kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(
            status="accepted",
            normalized_offset="open" if order.isbuy() else "close",
            normalized_position_side="long",
            normalized_time_in_force="GTC",
        )

    def verify_order_rules(self, order, rules):
        return True

    def evaluate_order_economics(self, order, rules):
        from types import SimpleNamespace

        return SimpleNamespace(status="accepted")

    def verify_order_economics(self, order, economics):
        return True

    # The final shutdown reconciliation is queued and answered through the
    # Store's ordinary broker-update channel (here: the same flat snapshot).
    def enqueue_reconcile(self):
        self.__dict__.setdefault("_seam_updates", []).append(
            {
                "kind": "command_completion",
                "command": "reconcile",
                "success": True,
                "response": self.get_reconcile_snapshot(),
            }
        )
        return {"kind": "command_receipt", "command": "reconcile", "queued": True}

    def apply_reconcile_snapshot(self, snapshot):
        return None  # the seam's flat snapshot carries no Store-bound projection

    def poll_broker_update(self):
        pending = self.__dict__.get("_seam_updates")
        if pending:
            return pending.pop(0)
        return super().poll_broker_update()

    def get_reconcile_snapshot(self):
        now = time.monotonic_ns()
        return {
            "evidence_complete": True,
            "configured_venues": ["OKX___SWAP"],
            "reconciled_venues": ["OKX___SWAP"],
            "generation": 1,
            "session_generation": 1,
            "fencing_epoch": 1,
            "as_of_monotonic_ns": now,
            "unknown_ids": [],
            "trading_blocked": False,
            "open_orders": [],
            "positions": [],
            "identity_binding_sha256": _IDENTITY,
            "execution_summary": {
                "active_orders": 0,
                "generation": 1,
                "session_generation": 1,
                "fencing_epoch": 1,
                "as_of_monotonic_ns": now,
                "session_enabled": True,
                "evidence_complete": True,
                "reconciliation_errors": {},
                "unknown_ids": [],
                "fee_unresolved_orders": [],
                "funding_unresolved_orders": [],
                "unmatched_trade_count": 0,
                "trading_blocked": False,
                "identity_binding_sha256": _IDENTITY,
            },
        }


class _RoundTrip(bt.Strategy):
    """Buy 1, then sell it back once the buy completed; the run ends flat."""

    params = (("host", None),)

    def __init__(self):
        self.statuses = []
        self.intents = []
        self.stage = "buy"

    def next(self):
        if self.stage in {"buying", "selling"}:
            # Live bars are spaced in wall-clock time; let the session's
            # refresh loop run while an order is outstanding (test pacing).
            time.sleep(0.02)
        if self.stage == "buy":
            self.stage = "buying"
            self.buy(
                size=1,
                price=float(self.data.close[0]),
                exectype=bt.Order.Limit,
                **self._managed("bt-cerebro-buy-1", "OPEN"),
            )
        elif self.stage == "sell":
            self.stage = "selling"
            self.sell(
                size=1,
                price=float(self.data.close[0]),
                exectype=bt.Order.Limit,
                **self._managed("bt-cerebro-sell-1", "CLOSE"),
            )

    @staticmethod
    def _managed(intent_id, effect):
        """Strategy-supplied managed intent metadata (the service adapter's contract)."""
        return {
            "managed_intent_id": intent_id,
            "managed_signal_id": "signal-" + intent_id,
            "managed_instrument": _support().INSTRUMENT,
            "managed_position_effect": effect,
            "managed_metadata_version": "bt-r2e-metadata-v1",
        }

    def notify_order(self, order):
        side = "buy" if order.isbuy() else "sell"
        self.statuses.append((side, order.getstatusname()))
        if order.status == order.Accepted:
            intent = order.info.get("managed_intent_id")
            self.intents.append(intent)
            # The provider fills on the host; the refresh loop brings it back.
            self.p.host.command("fill", intent, "FILLED", "1", "50000", "0.5")
        elif order.status == order.Completed:
            self.stage = "sell" if order.isbuy() else "done"


@pytest.mark.integration
def test_cerebro_run_loop_submits_through_the_typed_session_and_refreshes_the_fill(tmp_path):
    t = _support()
    host = t.Host(tmp_path)
    assert host.ready[0] == "ready", host.ready
    facade = _NoDirectWriteFacade()
    try:
        csv_path = tmp_path / "bars.csv"
        csv_path.write_text(
            "".join(f"2026-{10 + day // 28}-{1 + day % 28:02d},50000,50010,49990,50000,1\n" for day in range(56)),
            encoding="ascii",
        )
        store = _FlatAccountStore(provider="okx", api=facade, cash=0.0, value=0.0, autostart=False)
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
        cerebro.addstrategy(_RoundTrip, host=host)
        results = run_configured_cerebro(
            cerebro,
            t.client_config(host.endpoint),
            runtime_factory=t.runtime_factory(host.keys),
            session_options={"refresh_interval_seconds": 0.05},
            runonce=False,
            preload=False,
        )
        (strategy,) = results
        assert len(strategy.intents) == 2 and all(strategy.intents), strategy.statuses
        for side in ("buy", "sell"):
            seen = [status for item_side, status in strategy.statuses if item_side == side]
            # The managed route answers the submit with the durable record:
            # the first notification is Accepted, the last Completed.
            assert seen == ["Accepted", "Completed"], strategy.statuses
        assert strategy.getposition(strategy.data).size == 0
        assert facade.direct_writes == 0  # every write went through the service
    finally:
        submitted = host.close()
    assert submitted == strategy.intents
