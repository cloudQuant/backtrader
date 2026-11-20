"""Channel runs release their started resources when event delivery fails."""

from types import SimpleNamespace

import pytest

import backtrader as bt


class RecordingBroker(bt.brokers.BackBroker):
    def __init__(self):
        super().__init__()
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        super().stop()


class FailingStrategy(bt.Strategy):
    params = (("stops", None),)

    def notify_funding(self, event):
        raise ValueError("callback failed")

    def stop(self):
        self.p.stops.append("stopped")


def test_channel_callback_error_stops_strategy_and_broker():
    stops = []
    cerebro = bt.Cerebro(stdstats=False)
    broker = RecordingBroker()
    cerebro.setbroker(broker)
    cerebro.addstrategy(FailingStrategy, stops=stops)
    event = SimpleNamespace(channel_type="funding", data=SimpleNamespace(symbol="X"))

    with pytest.raises(ValueError, match="callback failed"):
        cerebro.run(channel=[event])

    assert stops == ["stopped"]
    assert broker.stop_calls == 1
    assert not cerebro._run_active


def test_broker_stops_even_if_strategy_stop_fails():
    class StopFails(bt.Strategy):
        def stop(self):
            raise ValueError("stop failed")

    cerebro = bt.Cerebro(stdstats=False)
    broker = RecordingBroker()
    cerebro.setbroker(broker)
    cerebro.addstrategy(StopFails)

    with pytest.raises(ValueError, match="stop failed"):
        cerebro.run(channel=[])

    assert broker.stop_calls == 1
    assert not cerebro._run_active
