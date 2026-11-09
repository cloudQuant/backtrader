"""R28 synthetic framework restart tests; no provider or network access."""

import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

import backtrader as bt
from backtrader.live_state import pending as pending_module
from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.metabase import OwnerContext
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from tests.unit.live_state.conftest import state, strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import make_event, page, ready
from tests.unit.live_state.test_gateway_pending import inputs


class RecordingStrategy(bt.Strategy):
    def notify_order(self, order):
        self.events.append(("order", order.notification_id, order.replayed))
        if self.fail == "order":
            raise RuntimeError("synthetic order callback")

    def notify_trade(self, trade):
        self.events.append(("trade", trade.notification_id, trade.replayed))

    def notify_fee_correction(self, order, trade, delta, currency):
        self.events.append(("fee", order.notification_id, order.replayed))
        if self.fail == "fee":
            raise RuntimeError("synthetic fee callback")


def framework(quick=False):
    frame = pd.DataFrame({"open": [10.0], "high": [11.0], "low": [9.0],
                          "close": [10.0], "volume": [1.0]},
                         index=pd.to_datetime(["2026-11-03 09:00"]))
    data = bt.feeds.PandasData(dataname=frame, name="rb")
    data._start()
    assert data.load()
    broker = bt.brokers.BtApiBroker()
    cerebro = bt.Cerebro(quicknotify=quick)
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas, cerebro.datasbyname = [data], {"rb": data}
    with OwnerContext.set_owner(cerebro):
        strategy = RecordingStrategy.__new__(RecordingStrategy)
    strategy.datas, strategy.data = [data], data
    strategy._tradehistoryon, strategy._quicknotify = True, quick
    strategy.events, strategy.fail = [], None
    return data, broker, strategy


def setup(ready, quick):
    host, binding, consumer = ready
    data, broker, strategy = framework(quick)
    order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10.0,
                        exectype=bt.Order.Limit)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.submit(broker)
    order.accept(broker)
    broker.bind_gateway_notification_state(strategy, host=host, data_by_ref={"rb": data},
                                           orders_by_key={"key-a": order})
    events = [make_event(host), make_event(host, 8, fact="f" * 64, trade="c" * 64)]
    host.ingest_execution_page(page(binding, consumer, events), expected_revision=0, after_sequence=0)
    return host, data, broker, strategy, order


def fill(broker, strategy, order, quick):
    broker.positions["rb"].update(1, 10)
    order.execute(order.data.datetime[0], 1, 10, 0, 0, 0, 1, 10, 0.1, 0, 0, 1, 10)
    strategy._addnotification(order.clone(), quicknotify=quick)


def run_child(state, host, order, quick, expected_events, sequence, fee, status):
    expected = {"directory": str(state.strategy_dir), "uuid": state.strategy_uuid,
                "old_ref": order.ref, "quick": quick, "events": expected_events,
                "sequence": sequence, "fee": fee, "status": status}
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), json.dumps(expected)],
                            cwd=env["PYTHONPATH"], env=env, text=True, capture_output=True,
                            timeout=60)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "child restart verified" in result.stdout


def child(expected):
    data, broker, strategy = framework(expected["quick"])
    # Ensure the freshly allocated order ref is distinguishable in this process.
    while bt.Order.refbasis.__reduce__()[1][0] <= expected["old_ref"]:
        next(bt.Order.refbasis)
    binding = GatewayCommandBinding("journal-a", "account-a", "strategy-a", "principal-a")
    host = GatewayPendingHost(expected["directory"], expected["uuid"], binding)
    broker.bind_gateway_notification_state(strategy, host=host, data_by_ref={"rb": data},
                                           orders_by_key={})
    broker.restore_gateway_notification_state(strategy)
    original = next(iter(broker.orders.values()))
    assert original.ref != expected["old_ref"]
    trade = next(iter(next(iter(strategy._trades.values())).values()))[0]
    assert isinstance(original, bt.Order) and isinstance(trade, bt.Trade)
    assert isinstance(broker.positions["rb"], bt.Position)
    assert (original.executed.size, broker.positions["rb"].size, trade.size) == (1, 1, 1)
    assert trade.commission == pytest.approx(0.3 if expected["fee"] else 0.1)
    assert original.executed.comm == pytest.approx(0.3 if expected["fee"] else 0.1)
    if expected["fee"]:
        assert strategy.__dict__["_fee_corrections_applied"][original.ref] == 1
        assert strategy.__dict__["_fee_correction_trades"][original.ref] is trade
    if expected["status"] == "pending":
        with pytest.raises(ValueError, match="ACK_BLOCKED"):
            broker.assert_gateway_notifications_ackable(strategy, expected["sequence"])
        # Replay may only deliver callbacks, never reapply a fill or fee.
        def forbidden(*args, **kwargs):
            raise AssertionError("replay recalculated framework state")
        bt.Trade.update = forbidden
        RecordingStrategy._addnotification = forbidden
        broker.replay_gateway_notifications(strategy)
        assert strategy.events == [tuple(item) for item in expected["events"]]
    else:
        assert not strategy.events
        with pytest.raises(ValueError, match="NO_PENDING"):
            broker.replay_gateway_notifications(strategy)
    assert host.load_execution_notification_batch()["status"] == "confirmed"
    broker.assert_gateway_notifications_ackable(strategy, expected["sequence"])
    assert (original.executed.size, broker.positions["rb"].size, trade.size) == (1, 1, 1)
    assert trade.commission == pytest.approx(0.3 if expected["fee"] else 0.1)
    print("child restart verified")


@pytest.mark.parametrize("quick", [False, True])
@pytest.mark.parametrize("window", ["before_callback", "callback", "confirm_before", "confirm_after"])
def test_restart_durable_notifications(state, ready, monkeypatch, quick, window):
    host, data, broker, strategy, order = setup(ready, quick)
    broker.arm_gateway_notification_state(strategy, 3)
    if window == "before_callback":
        monkeypatch.setattr(strategy, "_notify_inner", lambda **kw: (_ for _ in ()).throw(RuntimeError("before callback")))
    elif window == "callback":
        strategy.fail = "order"
    else:
        write = pending_module.atomic_write_json
        def fail_confirm(*args, **kwargs):
            if window == "confirm_after":
                write(*args, **kwargs)
            raise OSError("synthetic confirmation failure")
        original_confirm = host.confirm_execution_notification_batch
        def confirm(*args, **kwargs):
            with monkeypatch.context() as patch:
                patch.setattr(pending_module, "atomic_write_json", fail_confirm)
                return original_confirm(*args, **kwargs)
        monkeypatch.setattr(host, "confirm_execution_notification_batch", confirm)
    with pytest.raises((RuntimeError, OSError)):
        fill(broker, strategy, order, quick)
        if not quick:
            strategy._notify()
    batch = host.load_execution_notification_batch()
    status = "confirmed" if window == "confirm_after" else "pending"
    assert batch["status"] == status
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 3)
    ids = [(item["kind"], item["notification_id"], True) for item in batch["notifications"]]
    run_child(state, host, order, quick, ids, 3, False, status)


@pytest.mark.parametrize("quick", [False, True])
@pytest.mark.parametrize("window", ["before_replace", "after_replace"])
def test_commit_error_candidate_can_retry_then_restart(state, ready, monkeypatch, quick, window):
    host, data, broker, strategy, order = setup(ready, quick)
    broker.arm_gateway_notification_state(strategy, 3)
    write = pending_module.atomic_write_json
    def fail_commit(*args, **kwargs):
        if window == "after_replace":
            write(*args, **kwargs)
        raise OSError("synthetic commit failure")
    with monkeypatch.context() as patch:
        patch.setattr(pending_module, "atomic_write_json", fail_commit)
        with pytest.raises(OSError, match="synthetic commit failure"):
            fill(broker, strategy, order, quick)
            if not quick:
                strategy._notify()
    assert not strategy.events
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 3)
    batch = host.load_execution_notification_batch()
    assert (batch is None) == (window == "before_replace")
    broker.replay_gateway_notifications(strategy)
    batch = host.load_execution_notification_batch()
    assert batch["status"] == "confirmed"
    assert strategy.events == [(item["kind"], item["notification_id"], True)
                               for item in batch["notifications"]]
    broker.assert_gateway_notifications_ackable(strategy, 3)
    run_child(state, host, order, quick, [], 3, False, "confirmed")


def test_fee_only_callback_failure_restart(state, ready):
    host, data, broker, strategy, order = setup(ready, False)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order, False)
    strategy._notify()
    strategy.clear()
    broker.arm_gateway_notification_state(strategy, 8)
    order.executed.comm += 0.2  # Explicit synthetic fee; no provider fee claim.
    order.info["fee_corrections"] = [{"sequence": 1, "delta": 0.2, "currency": "CNY"}]
    strategy.fail = "fee"
    with pytest.raises(RuntimeError, match="fee callback"):
        strategy._addnotification(order.clone())
    batch = host.load_execution_notification_batch()
    assert batch["status"] == "pending"
    assert [item["kind"] for item in batch["notifications"]] == ["fee", "order"]
    ids = [(item["kind"], item["notification_id"], True) for item in batch["notifications"]]
    run_child(state, host, order, False, ids, 8, True, "pending")


if __name__ == "__main__":
    child(json.loads(sys.argv[1]))
