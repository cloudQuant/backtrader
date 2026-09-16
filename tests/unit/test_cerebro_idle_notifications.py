import backtrader as bt
from backtrader.brokers.tickbroker import TickBroker


class _SilentLiveFeed(bt.feed.DataBase):
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
        return None if self.polls <= 3 else False


class _IdleAwareStrategy(bt.Strategy):
    def __init__(self):
        self.idle_calls = 0

    def notify_idle(self):
        self.idle_calls += 1


class _IdleCancelStrategy(bt.Strategy):
    def __init__(self):
        self.idle_calls = 0
        self.order_statuses = []

    def notify_idle(self):
        self.idle_calls += 1
        if self.idle_calls == 1:
            order = self.buy(size=1, exectype=bt.Order.Limit, price=1)
            self.cancel(order)

    def notify_order(self, order):
        self.order_statuses.append(order.status)


def test_live_broker_idle_polls_reach_overridden_strategy_hook_without_fake_bars():
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    data = _SilentLiveFeed()
    cerebro.adddata(data)
    cerebro.addstrategy(_IdleAwareStrategy)
    strategy = cerebro.run(runonce=False, preload=False)[0]

    assert strategy.idle_calls == 3
    assert len(strategy) == 0


def test_tickbroker_drains_idle_cancel_notifications_without_fake_bars():
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(TickBroker())
    data = _SilentLiveFeed()
    cerebro.adddata(data)
    cerebro.addstrategy(_IdleCancelStrategy)
    strategy = cerebro.run(runonce=False, preload=False)[0]

    assert strategy.idle_calls == 3
    assert bt.Order.Submitted in strategy.order_statuses
    assert bt.Order.Cancelled in strategy.order_statuses
    assert len(strategy) == 0
