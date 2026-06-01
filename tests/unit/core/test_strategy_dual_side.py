import backtrader as bt
import pytest

from backtrader.brokers.bbroker import BackBroker
from tests.unit.core.test_core_deep_coverage import SimpleFeed, generate_ohlcv


class DualSideLifecycleStrategy(bt.Strategy):
    params = (("tradeid", 7),)

    def __init__(self):
        self.ambiguous_close_rejected = False
        self.long_seen = 0.0
        self.short_seen = 0.0
        self.net_seen = 0.0
        self.closed_tradeids = []

    def notify_trade(self, trade):
        if trade.isclosed:
            self.closed_tradeids.append(trade.tradeid)

    def next(self):
        if len(self) == 1:
            self.buy(size=2, tradeid=self.p.tradeid, position_side="long", offset="open")
        elif len(self) == 2:
            self.sell(size=1, tradeid=self.p.tradeid, position_side="short", offset="open")
        elif len(self) == 3:
            self.long_seen = self.getposition(self.data, side="long").size
            self.short_seen = self.getposition(self.data, side="short").size
            self.net_seen = self.position.size
            try:
                self.close()
            except ValueError:
                self.ambiguous_close_rejected = True
            self.close(position_side="long", tradeid=self.p.tradeid)
        elif len(self) == 4:
            self.close(position_side="short", tradeid=self.p.tradeid)


def test_strategy_close_and_trade_grouping_support_dual_side_positions():
    cerebro = bt.Cerebro()
    broker = BackBroker(position_mode="dual_side")
    broker.setcommission(commission=0.0)
    cerebro.setbroker(broker)
    cerebro.adddata(SimpleFeed(data_list=generate_ohlcv(num_bars=8)))
    cerebro.addstrategy(DualSideLifecycleStrategy)

    strategy = cerebro.run()[0]

    assert strategy.ambiguous_close_rejected is True
    assert strategy.long_seen == pytest.approx(2.0)
    assert strategy.short_seen == pytest.approx(1.0)
    assert strategy.net_seen == pytest.approx(1.0)
    assert strategy.position.size == pytest.approx(0.0)
    assert strategy.getposition(strategy.data, side="long").size == pytest.approx(0.0)
    assert strategy.getposition(strategy.data, side="short").size == pytest.approx(0.0)
    assert sorted(strategy.closed_tradeids, key=str) == [
        (7, "long"),
        (7, "short"),
    ]
