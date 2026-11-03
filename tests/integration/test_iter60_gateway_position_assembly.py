"""Iteration 60: BT refuses to reconcile against a filtered Gateway stream.

Product entry only: a spawned Gateway host, the public client configuration
mapping -> ``gateway_position_stream_from_config`` -> passed as
``account_positions`` to ``BtApiBroker.bind_direct_strategy_ledger``.  The
filtered view is usable for observation but does not prove the complete
account position set needed for reconciliation.

The Gateway host fixture lives in the SDK test suite (``tests.unit`` there),
which clashes with this repository's ``tests`` package, so the scenario runs
in a subprocess whose import path puts the SDK first. INTEGRATION_SIM.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

zmq = pytest.importorskip("zmq")
sdk = pytest.importorskip("bt_api_py.account_position_stream")

BT_ROOT = Path(__file__).resolve().parents[2]
SDK_ROOT = Path(sdk.__file__).resolve().parents[1]

SCENARIO = textwrap.dedent(
    """
    import itertools, sys, tempfile
    from decimal import Decimal
    from pathlib import Path
    from types import SimpleNamespace

    import pandas as pd
    import backtrader as bt
    from backtrader.brokers.btapibroker import BtApiBroker
    from backtrader.metabase import OwnerContext
    from backtrader.service.service_strategy_account_book import ServiceStrategyAccountBookError
    from bt_api_py.strategy_ledger import InstrumentTerms, LedgerIntent, SqliteStrategyLedger
    from bt_api_py.account_owner_handoff import AccountOwnerHandoff
    from tests.unit import test_iter60_gateway_position_config as gw
    from tests.unit import test_service_account_views_integration as views

    INSTRUMENT = "synthetic-perpetual"

    class Store:
        _sdk_mode = False
        def __init__(self): self.sent = []
        def evaluate_order_rules(self, o, **k):
            return SimpleNamespace(status="accepted", normalized_offset="open",
                                   normalized_position_side="long", normalized_time_in_force="GTC")
        def verify_order_rules(self, o, r): return True
        def evaluate_order_economics(self, o, r): return SimpleNamespace(status="accepted")
        def verify_order_economics(self, o, e): return True
        def prepare_order_correlation(self, o): return {"ref": o.ref}
        def verify_order_response(self, c, r): return True
        def submit_order(self, o):
            self.sent.append(o.ref)
            return {"kind": "verified_order_ack", "verified_order_ack": True,
                    "operation": "submit", "status": "accepted", "id": f"p-{o.ref}"}

    class S(bt.Strategy):
        params = (("strategy_ref", None), ("account_ref", None))

    if __name__ == "__main__":
        tmp = Path(tempfile.mkdtemp())
        records = []
        host, service, client_config, keys = gw.start_gateway(tmp, records)
        stream = ledger = handoff = None
        try:
            stream = gw.stream_for(service, client_config, keys, tmp / "projection.sqlite3")
            ledger = SqliteStrategyLedger(
                tmp / "ledger.sqlite3", account_ref=views._ACCOUNT_REF,
                instruments={INSTRUMENT: InstrumentTerms(Decimal("1"), "USD", "futures")},
                require_budget=False,
            )
            handoff = AccountOwnerHandoff(tmp / "owner.sqlite3", views._ACCOUNT_REF,
                                          initial_owner="direct", proof_verifier=lambda p, o: True)
            ledger.reserve(LedgerIntent("a", "A", INSTRUMENT, "BUY", Decimal("2"), Decimal("10")))
            ledger.apply_execution("a", cumulative_quantity=2, average_price=10)
            # The host publishes a linear-only strategy view, not evidence
            # that all positions of the account were covered.  Wait for the
            # actual position, so an uninitialized stream cannot pass.
            assert gw.wait_for(
                lambda: stream.report().positions.get(INSTRUMENT) == Decimal("2")
                and stream.positions.interruption == "GATEWAY_FULL_COVERAGE_UNPROVEN"
            ), (stream.error, stream.positions.interruption)
            report = stream.report()
            assert report.complete is False
            assert report.source.startswith("gateway:")
            assert report.valid_until_ns is None
            assert stream.positions.interruption == "GATEWAY_FULL_COVERAGE_UNPROVEN"
            reconciliation = ledger.reconcile(report)
            assert reconciliation.state == "UNVERIFIED"
            assert reconciliation.reason == "REPORT_INCOMPLETE"
            broker = BtApiBroker(store=Store())
            broker.bind_account_owner(handoff, "direct")
            frame = pd.DataFrame({"open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0],
                                  "volume": [1.0]}, index=pd.to_datetime(["2026-11-03 09:00"]))
            data = bt.feeds.PandasData(dataname=frame, name=INSTRUMENT); data._start(); data.load()
            cerebro = bt.Cerebro(); cerebro.setbroker(broker); cerebro.stcount = itertools.count()
            cerebro.datas = [data]; cerebro.datasbyname = {INSTRUMENT: data}
            with OwnerContext.set_owner(cerebro):
                a = S.__new__(S, strategy_ref="A", account_ref=views._ACCOUNT_REF)
            a.datas = [data]; a.data = data
            broker.bind_direct_strategy_ledger(a, ledger, account_positions=stream)  # the stream object
            try:
                a.getposition(data)
            except ServiceStrategyAccountBookError as error:
                assert error.code == "STRATEGY_BOOK_RECONCILIATION_UNVERIFIED", error.code
            else:
                raise AssertionError("an incomplete account view must not reconcile the strategy book")
            print("observed", report.positions[INSTRUMENT] == Decimal("2"), "reconcile", reconciliation.reason)
        finally:
            if stream is not None: stream.close()
            if handoff is not None: handoff.close()
            if ledger is not None: ledger.close()
            gw.stop_gateway(host, records)
        print("ok")
    """
)


def test_bt_binds_the_config_driven_gateway_stream(tmp_path):
    script = tmp_path / "scenario.py"
    script.write_text(SCENARIO)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(SDK_ROOT), str(BT_ROOT)]))
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=SDK_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert "observed True reconcile REPORT_INCOMPLETE" in result.stdout
    assert result.stdout.strip().endswith("ok")
