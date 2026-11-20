"""Optimization workers must be reaped on normal and exceptional exits."""

import importlib

import pytest

import backtrader as bt


class RecordingPool:
    def __init__(self, failure):
        self.failure = failure
        self.calls = []

    def imap(self, func, iterable):
        self.calls.append("imap")
        if self.failure == "imap":
            raise ValueError("imap failed")
        if self.failure == "iteration":
            def failed_results():
                yield ["result"]
                raise ValueError("iteration failed")

            return failed_results()
        return iter([["result"]])

    def close(self):
        self.calls.append("close")

    def terminate(self):
        self.calls.append("terminate")

    def join(self):
        self.calls.append("join")


@pytest.mark.parametrize("failure", ["imap", "iteration", "callback", None])
def test_optimization_pool_is_reaped(monkeypatch, failure):
    pool = RecordingPool(failure)
    cerebro_module = importlib.import_module("backtrader.cerebro")
    monkeypatch.setattr(cerebro_module.multiprocessing, "Pool", lambda *args: pool)
    cerebro = bt.Cerebro(maxcpus=2, optdatas=False, stdstats=False)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname="unused.csv"))
    cerebro.optstrategy(bt.Strategy)

    def callback(result):
        if failure == "callback":
            raise ValueError("callback failed")

    cerebro.optcallback(callback)
    if failure is None:
        assert cerebro.run() == [["result"]]
        assert pool.calls == ["imap", "close", "join"]
    else:
        with pytest.raises(ValueError, match=f"{failure} failed"):
            cerebro.run()
        assert pool.calls == ["imap", "terminate", "join"]
