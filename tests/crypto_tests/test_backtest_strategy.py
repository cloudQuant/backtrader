import time
from datetime import datetime, timedelta
import backtrader as bt

from backtrader.feeds.cryptofeed import CryptoFeed


class TestStrategy(bt.Strategy):
    def __init__(self):
        self.next_runs = 0

    def next(self, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        print('%s closing price: %s' % (dt.isoformat(), self.datas[0].close[0]))
        self.next_runs += 1


def test_backtest_strategy():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TestStrategy)
    data = CryptoFeed(  exchange='binance',
                        symbol='BNB-USDT',
                        asset_type="swap",
                        timeframe=bt.TimeFrame.Minutes,
                        compression=1,
                        fromdate=datetime(2021, 8, 1, 0, 0),

                        ohlcv_limit=1000,
                        drop_newest=True,
                        currency='BNB',
                        retries=5,
                        #debug=True,
                        # 'apiKey' and 'secret' are skipped
                        config={'enableRateLimit': True, 'nonce': lambda: str(int(time.time() * 1000))})
    cerebro.adddata(data)

    # Run the strategy
    cerebro.run()


if __name__ == '__main__':
    test_backtest_strategy()