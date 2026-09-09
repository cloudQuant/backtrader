"""Cerebro-idle integration for the managed CTP reconciliation lane."""

import threading
import time

import backtrader as bt

from backtrader.brokers.btapibroker import BtApiBroker
from tests.fixtures.fake_btapi import make_store
from tests.unit.brokers.test_btapibroker_iteration22 import ManagedAsyncCtpClient


class SilentLiveFeed(bt.feed.DataBase):
    params = (("qcheck", 0.0001),)

    def __init__(self):
        super().__init__()
        self.polls = 0

    def islive(self):
        return True

    def haslivedata(self):
        return True

    def _load(self):
        self.polls += 1
        time.sleep(0.0001)
        return None if self.polls < 100000 else False


class IdleCtpBroker(BtApiBroker):
    """Keep this integration focused on the idle worker/callback boundary."""

    def start(self):
        self._live_started = False

    def stop(self):
        return self.store.stop(timeout=2.0)


class ReconciliationLifecycleStrategy(bt.Strategy):
    def __init__(self):
        self.phase = "RECOVERING"
        self.phase_rounds = 0
        self.transitions = [self.phase]
        self.callback_threads = []
        self.request_ids = []

    def notify_idle(self):
        if self.phase != "STOPPED_FLAT":
            self.broker.request_ctp_reconciliation(timeout=0)

    def notify_reconciliation(self, snapshot):
        self.callback_threads.append(threading.get_ident())
        self.request_ids.append(snapshot["request_id"])
        assert snapshot["complete"] is True
        assert snapshot["unknown_intent_count"] == 0
        assert snapshot["unmatched_trade_count"] == 0
        self.phase_rounds += 1
        if self.phase == "RECOVERING" and self.phase_rounds == 2:
            self.phase = "COOLDOWN"
            self.transitions.append(self.phase)
            self.phase = "DRAINING"
            self.transitions.append(self.phase)
            self.phase_rounds = 0
        elif self.phase == "DRAINING" and self.phase_rounds == 2:
            self.phase = "STOPPED_FLAT"
            self.transitions.append(self.phase)
            self.cerebro.runstop()


def test_idle_queries_run_off_thread_and_drive_strategy_reconciliation_lifecycle():
    main_thread = threading.get_ident()
    client = ManagedAsyncCtpClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        symbol_routes={"SA609": "CTP___FUTURE"},
    )
    broker = IdleCtpBroker(store=store, provider="btapi")
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(broker)
    cerebro.adddata(SilentLiveFeed())
    cerebro.addstrategy(ReconciliationLifecycleStrategy)

    strategy = cerebro.run(runonce=False, preload=False)[0]

    assert strategy.transitions == ["RECOVERING", "COOLDOWN", "DRAINING", "STOPPED_FLAT"]
    assert len(strategy.request_ids) == 4
    assert len(set(strategy.request_ids)) == 4
    assert strategy.callback_threads == [main_thread] * 4
    assert client.query_threads
    assert all(thread_id != main_thread for thread_id in client.query_threads)
    assert len(strategy) == 0
