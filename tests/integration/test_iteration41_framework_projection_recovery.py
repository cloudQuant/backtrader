"""No-network crash-boundary acceptance for managed framework projection.

The first process durably records a filled SDK execution and then stops before
any Backtrader order/position/observer projection occurs.  A second framework
runtime session materializes the same sealed intent: it must make no provider
call, apply the durable fill exactly once to fresh framework state, and expose
the ordinary completed-order event to ``TradeLogger``.
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
    return iteration41_source_paths("parent", "base", "execution")


def test_crashed_managed_fill_is_recovered_once_into_a_fresh_broker_and_trade_logger() -> None:
    _sdk_sources = _require_sdk_sources()
    script = textwrap.dedent(
        """
        import json
        import socket
        import tempfile
        import uuid
        from decimal import Decimal
        from pathlib import Path
        from types import SimpleNamespace

        import backtrader as bt
        import pandas as pd
        from backtrader.order import OrderBase
        from backtrader.stores.btapistore import BtApiStore
        from backtrader_runtime.managed_execution import ManagedExecutionBindingError, ManagedExecutionBridge
        import bt_api_execution as execution

        attempts = []

        class DeniedSocket(socket.socket):
            def connect(self, *args, **kwargs):
                attempts.append((args, kwargs))
                raise AssertionError("framework projection recovery must remain offline")

            def connect_ex(self, *args, **kwargs):
                attempts.append((args, kwargs))
                raise AssertionError("framework projection recovery must remain offline")

        socket.socket = DeniedSocket

        SYMBOL = "fixture/contract"
        INTENT_ID = "projection.crash.41"
        METADATA_DIGEST = "a" * 64

        def info():
            return {
                "managed_order_type": "LIMIT",
                "managed_intent_id": INTENT_ID,
                "managed_signal_id": "signal." + INTENT_ID,
                "managed_instrument": SYMBOL,
                "managed_position_effect": "OPEN",
                "managed_metadata_version": "projection.metadata.v1",
                    "managed_instrument_metadata_digest": METADATA_DIGEST,
                    "offset": "open",
                    "reduce_only": False,
                    # BtApiBroker applies its reviewed default to the actual
                    # framework order before it reaches the managed bridge.
                    # The pre-crash fixture must therefore carry the same
                    # provider payload, rather than testing recovery across a
                    # material order-policy change.
                    "position_mode": "net",
                }

        class Runtime:
            def __init__(self, root, session_id):
                self.execution = execution
                self.scope = execution.ExecutionScope(
                    "fixture", "offline", "account.projection", "strategy.projection", "20260922"
                )
                self.execution_store = execution.SqliteExecutionStore(root / "execution.sqlite3")
                self.facade = execution.ManagedExecutionFacade(
                    self.execution_store,
                    self.scope,
                    writer_id="projection.writer",
                    allow_unprotected=True,
                )
                self.state_directory = root
                self.framework_projection_session_id = session_id

            def submit(self, intent, dispatcher):
                return self.facade.submit(intent, dispatcher)

            def close(self):
                self.facade.close()
                self.execution_store.close()

        class ExplicitOrder:
            ref = 41
            exectype = OrderBase.Limit
            size = 2
            price = 101.0
            pricelimit = None
            valid = None
            tradeid = 0
            data = SimpleNamespace(_name=SYMBOL)
            created = SimpleNamespace(price=101.0)

            def __init__(self):
                self.info = info()

            def isbuy(self):
                return True

            def issell(self):
                return False

            def getordername(self):
                return "Limit"

        class NoNetworkApi:
            def __init__(self):
                self.submissions = []

            def get_balance(self):
                return {"cash": 1000.0, "value": 1000.0}

            def submit_order(self, payload):
                self.submissions.append(dict(payload))
                raise AssertionError("recovered framework order must not dispatch the provider")

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            first = Runtime(root, uuid.uuid4().hex)
            first_bridge = ManagedExecutionBridge(first)
            try:
                # This is the injected crash boundary: the provider result has
                # reached the SDK journal and a projection receipt is claimed,
                # but no Backtrader Broker has seen the response yet.
                initial = first_bridge.submit_order(
                    ExplicitOrder(),
                    lambda _order: {
                        "status": "filled",
                        "id": "provider.projection.41",
                        "filled_quantity": "2",
                        "average_price": "101.5",
                        "cumulative_commission": "0.50",
                    },
                )
                assert initial["managed_framework_projection_receipt_id"]
                durable = first.execution_store.get(INTENT_ID, scope=first.scope)
                assert durable is not None
                assert durable.state is execution.ExecutionState.FILLED
                assert durable.cumulative_commission == Decimal("0.50")
            finally:
                # Closing models process death only after the injected point;
                # it deliberately does not complete the framework receipt.
                first_bridge.close()
                first.close()

            restarted = Runtime(root, uuid.uuid4().hex)
            bridge = ManagedExecutionBridge(restarted)
            api = NoNetworkApi()
            store = BtApiStore(
                provider="btapi", api=api, managed_execution_adapter=bridge
            )
            broker = store.getbroker(
                validation_enabled=False,
                cash_check_enabled=False,
                account_refresh_interval=3600.0,
                positions_refresh_interval=3600.0,
                open_orders_refresh_interval=3600.0,
            )
            data = bt.feeds.PandasData(
                dataname=pd.DataFrame(
                    {
                        "open": [100.0, 101.0],
                        "high": [102.0, 103.0],
                        "low": [99.0, 100.0],
                        "close": [101.0, 102.0],
                        "volume": [1.0, 1.0],
                        "openinterest": [0.0, 0.0],
                    },
                    index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
                )
            )
            cerebro = bt.Cerebro(stdstats=False, runonce=False)

            class Strategy(bt.Strategy):
                def next(self):
                    if len(self) == 1:
                        self.order = self.buy(
                            data=self.datas[0],
                            size=2,
                            price=101.0,
                            exectype=bt.Order.Limit,
                            **info(),
                        )
                    elif len(self) == 2:
                        self.cerebro.runstop()

            cerebro.setbroker(broker)
            cerebro.adddata(data, name=SYMBOL)
            cerebro.addstrategy(Strategy)
            cerebro.addobserver(
                bt.observers.TradeLogger,
                obsname="trade_logger",
                log_dir=str(root / "trade-logger"),
                log_format="json",
                log_orders=False,
                log_trades=False,
                log_positions=False,
                log_indicators=False,
                log_signals=False,
                log_ticks=False,
                log_bars=False,
                log_position_snapshot=False,
                report_max_records=20,
            )
            try:
                strategy = cerebro.run()[0]
                report = strategy.stats.trade_logger.final_report()
                completed = [
                    item for item in report["order_summaries"] if item["status"] == "Completed"
                ]
                assert strategy.order.status == bt.Order.Completed
                assert strategy.order.executed.size == 2.0
                assert strategy.order.executed.price == 101.5
                assert strategy.order.executed.comm == 0.5
                assert broker.positions[SYMBOL].size == 2.0
                assert len(completed) == 1
                assert completed[0]["executed_size"] == 2.0
                assert completed[0]["executed_price"] == 101.5
                assert completed[0]["commission"] == 0.5
                assert api.submissions == []

                # A second callback in this same framework session has no
                # active receipt and cannot duplicate the local fill.
                try:
                    bridge.submit_order(ExplicitOrder(), lambda _order: None)
                except ManagedExecutionBindingError:
                    pass
                else:
                    raise AssertionError("same-session duplicate projection was not blocked")
            finally:
                bridge.close()
                restarted.close()

        assert attempts == []
        print(json.dumps({"provider_dispatches_after_restart": 0, "completed_orders": 1}))
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
        "provider_dispatches_after_restart": 0,
        "completed_orders": 1,
    }
