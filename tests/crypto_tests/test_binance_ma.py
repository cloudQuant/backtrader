
import backtrader as bt
from datetime import datetime, timedelta, UTC
import json
from backtrader.stores.cryptostore import CryptoStore
from backtrader.feeds.cryptofeed import CryptoFeed
from backtrader.brokers.cryptobroker import CryptoBroker
from bt_api_py.functions.utils import read_yaml_file

class TestStrategy(bt.Strategy):

    def __init__(self):

        self.sma = bt.indicators.SMA(self.data, period=21)

    def next(self):

        # Get cash and balance
        # New broker method that will let you get the cash and balance for
        # any wallet. It also means we can disable the getcash() and getvalue()
        # rest calls before and after next which slows things down.

        # NOTE: If you try to get the wallet balance from a wallet you have
        # never funded, a KeyError will be raised! Change LTC below as approriate
        if self.live_data:
            cash, value = self.broker.get_wallet_balance('USDT')
        else:
            # Avoid checking the balance during a backfill. Otherwise, it will
            # Slow things down.
            cash = 'NA'

        for data in self.datas:
            print('{} - {} | Cash {} | O: {} H: {} L: {} C: {} V:{} SMA:{}'.format(data.datetime.datetime(),
                                                                                   data._name, cash, data.open[0], data.high[0], data.low[0], data.close[0], data.volume[0],
                                                                                   self.sma[0]))

    def notify_data(self, data, status, *args, **kwargs):
        dn = data._name
        dt = datetime.now()
        msg= 'Data Status: {}'.format(data._getstatusname(status))
        print(dt,dn,msg)
        if data._getstatusname(status) == 'LIVE':
            self.live_data = True
        else:
            self.live_data = False

def get_account_config():
    account_config_data = read_yaml_file('account_config.yaml')
    return account_config_data


def run():
    cerebro = bt.Cerebro(quicknotify=True)
    # Add the strategy
    cerebro.addstrategy(TestStrategy)
    # IMPORTANT NOTE - Kraken (and some other exchanges) will not return any values
    # for get cash or value if You have never held any BNB coins in your account.
    # So switch BNB to a coin you have funded previously if you get errors
    account_config_data = get_account_config()
    kwargs = {
        "public_key": account_config_data['binance']['public_key'],
        "private_key": account_config_data['binance']['private_key'],
    }
    store = CryptoStore(exchange='binance', asset_type='swap', symbol="BTC-USDT", **kwargs)
    # Get our data
    # Drop newest will prevent us from loading partial data from incomplete candles
    hist_start_date = datetime.now(UTC) - timedelta(minutes=50)
    data = store.getdata(dataname='BNB/USDT', name="BNB-USDT",
                         timeframe=bt.TimeFrame.Minutes, fromdate=hist_start_date,
                         compression=1, ohlcv_limit=50, drop_newest=True)  # , historical=True)

    # Add the feed
    cerebro.adddata(data)
    broker = CryptoBroker(store=store)
    cerebro.setbroker(broker)

    # Run the strategy
    cerebro.run()



if __name__ == '__main__':
    run()