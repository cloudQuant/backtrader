import time
from datetime import datetime
from functools import wraps
import queue
import backtrader as bt
from backtrader.store import MetaSingleton
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import with_metaclass


class CryptoStore(with_metaclass(MetaSingleton, object)):
    """bt_api_py and backtrader store
    """

    # Supported granularities
    _GRANULARITIES = {
        (bt.TimeFrame.Minutes, 1): '1m',
        (bt.TimeFrame.Minutes, 3): '3m',
        (bt.TimeFrame.Minutes, 5): '5m',
        (bt.TimeFrame.Minutes, 15): '15m',
        (bt.TimeFrame.Minutes, 30): '30m',
        (bt.TimeFrame.Minutes, 60): '1h',
        (bt.TimeFrame.Minutes, 90): '90m',
        (bt.TimeFrame.Minutes, 120): '2h',
        (bt.TimeFrame.Minutes, 180): '3h',
        (bt.TimeFrame.Minutes, 240): '4h',
        (bt.TimeFrame.Minutes, 360): '6h',
        (bt.TimeFrame.Minutes, 480): '8h',
        (bt.TimeFrame.Minutes, 720): '12h',
        (bt.TimeFrame.Days, 1): '1d',
        (bt.TimeFrame.Days, 3): '3d',
        (bt.TimeFrame.Weeks, 1): '1w',
        (bt.TimeFrame.Weeks, 2): '2w',
        (bt.TimeFrame.Months, 1): '1M',
        (bt.TimeFrame.Months, 3): '3M',
        (bt.TimeFrame.Months, 6): '6M',
        (bt.TimeFrame.Years, 1): '1y',
    }

    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns ``DataCls`` with args, kwargs"""
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered ``BrokerCls``"""
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self, exchange, asset_type, symbol, debug=False, **kwargs):
        self.exchange = exchange
        self.asset_type = asset_type
        self.symbol = symbol
        self.data_queue = queue.Queue()
        self.feed = None
        self.init_feed(exchange, asset_type, **kwargs)
        self.debug = debug



    def init_feed(self, exchange, asset_type, **kwargs):
        if exchange == "binance" and asset_type == "swap":
            self.init_binance_swap_feed(**kwargs)

        if exchange == "binance" and asset_type == "spot":
            self.init_binance_spot_feed(**kwargs)

        if exchange == "okx" and asset_type == "spot":
            self.init_okx_spot_feed(**kwargs)

        if exchange == "okx" and asset_type == "swap":
            self.init_okx_swap_feed(**kwargs)


    def init_binance_swap_feed(self, **kwargs):
        from bt_api_py.feeds.live_binance_feed import BinanceRequestDataSwap
        self.feed = BinanceRequestDataSwap(self.data_queue, ** kwargs)

    def init_binance_spot_feed(self, **kwargs):
        from bt_api_py.feeds.live_binance_feed import BinanceRequestDataSpot
        self.feed = BinanceRequestDataSpot(self.data_queue, ** kwargs)

    def init_okx_spot_feed(self, **kwargs):
        from bt_api_py.feeds.live_okx_feed import OkxRequestDataSpot
        self.feed = OkxRequestDataSpot(self.data_queue, ** kwargs)

    def init_okx_swap_feed(self, **kwargs):
        from bt_api_py.feeds.live_okx_feed import OkxRequestDataSwap
        self.feed = OkxRequestDataSwap(self.data_queue, ** kwargs)

    def wss_start(self):
        if self.exchange == "binance" and self.asset_type == "swap":
            self.wss_start_binance_swap()

        if self.exchange == "binance" and self.asset_type == "spot":
            self.wss_start_binance_spot()

        if self.exchange == "okx" and self.asset_type == "spot":
            self.wss_start_okx_spot()

        if self.exchange == "okx" and self.asset_type == "swap":
            self.wss_start_okx_swap()

    def wss_start_binance_swap(self):
        from bt_api_py.containers.exchanges.binance_exchange_data import BinanceExchangeDataSwap
        from bt_api_py.feeds.live_binance_feed import BinanceMarketWssDataSwap
        from bt_api_py.feeds.live_binance_feed import BinanceAccountWssDataSwap
        kwargs = {key:v for key, v in self.kwargs.items()}
        kwargs['wss_name'] = 'binance_market_data'
        kwargs["wss_url"] = 'wss://fstream.binance.com/ws'
        kwargs["exchange_data"] = BinanceExchangeDataSwap()
        BinanceMarketWssDataSwap(self.data_queue, **kwargs).start()
        account_kwargs = {k:v for k, v in kwargs.items()}
        account_kwargs['topics'] =  [
            {"topic": "account"},
            {"topic": "order"},
            {"topic": "trade"},
        ]
        BinanceAccountWssDataSwap(self.data_queue, **account_kwargs).start()


    def wss_start_binance_spot(self):
        from bt_api_py.containers.exchanges.binance_exchange_data import BinanceExchangeDataSpot
        from bt_api_py.feeds.live_binance_feed import BinanceMarketWssDataSpot
        from bt_api_py.feeds.live_binance_feed import BinanceAccountWssDataSpot
        kwargs = {key: v for key, v in self.kwargs.items()}
        kwargs['wss_name'] = 'binance_market_data'
        kwargs["wss_url"] = 'wss://fstream.binance.com/ws'
        kwargs["exchange_data"] = BinanceExchangeDataSpot()
        BinanceMarketWssDataSpot(self.data_queue, **kwargs).start()
        account_kwargs = {k: v for k, v in kwargs.items()}
        account_kwargs['topics'] = [
            {"topic": "account"},
            {"topic": "order"},
            {"topic": "trade"},
        ]
        BinanceAccountWssDataSpot(self.data_queue, **account_kwargs).start()

    def wss_start_okx_spot(self):
        from bt_api_py.containers.exchanges.okx_exchange_data import OkxExchangeDataSpot
        from bt_api_py.feeds.live_okx_feed import OkxMarketWssDataSpot
        from bt_api_py.feeds.live_okx_feed import OkxAccountWssDataSpot
        from bt_api_py.feeds.live_okx_feed import OkxKlineWssDataSpot
        topic_list = [i['topic'] for i in self.kwargs['topics']]
        if "kline" in topic_list:
            kline_kwargs = {key: v for key, v in self.kwargs.items()}
            kline_kwargs['wss_name'] = 'okx_spot_kline_data'
            kline_kwargs["wss_url"] = 'wss://ws.okx.com:8443/ws/v5/business'
            kline_kwargs["exchange_data"] = OkxExchangeDataSpot()
            kline_topics = [i for i in self.kwargs['topics'] if i['topic']=="kline"]
            kline_kwargs['topics'] = kline_topics
            OkxKlineWssDataSpot(self.data_queue, **kline_kwargs).start()
        ticker_true = "ticker" in topic_list
        depth_true = "depth" in topic_list
        funding_rate_true = "funding_rate" in topic_list
        mark_price_true = "mark_price" in topic_list
        if ticker_true or depth_true or funding_rate_true or mark_price_true:
            market_kwargs = {key: v for key, v in self.kwargs.items()}
            market_kwargs['wss_name'] = 'okx_spot_market_data'
            market_kwargs["wss_url"] = 'wss://ws.okx.com:8443/ws/v5/public'
            market_kwargs["exchange_data"] = OkxExchangeDataSpot()
            market_topics = [i for i in self.kwargs['topics'] if i['topic'] != "kline"]
            market_kwargs['topics'] = market_topics
            OkxMarketWssDataSpot(self.data_queue, **market_kwargs).start()

        account_kwargs = {key: v for key, v in self.kwargs.items()}

        account_topics = [{"topic": "account", "symbol": self.symbol, "currency": "USDT"},
            {"topic": "orders", "symbol": self.symbol},
            {"topic": "positions", "symbol": self.symbol}]
        account_kwargs['topics'] = account_topics
        OkxAccountWssDataSpot(self.data_queue, **account_kwargs).start()

    def wss_start_okx_swap(self):
        from bt_api_py.containers.exchanges.okx_exchange_data import OkxExchangeDataSwap
        from bt_api_py.feeds.live_okx_feed import OkxMarketWssDataSwap
        from bt_api_py.feeds.live_okx_feed import OkxAccountWssDataSwap
        from bt_api_py.feeds.live_okx_feed import OkxKlineWssDataSwap
        topic_list = [i['topic'] for i in self.kwargs['topics']]
        if "kline" in topic_list:
            kline_kwargs = {key: v for key, v in self.kwargs.items()}
            kline_kwargs['wss_name'] = 'okx_spot_kline_data'
            kline_kwargs["wss_url"] = 'wss://ws.okx.com:8443/ws/v5/business'
            kline_kwargs["exchange_data"] = OkxExchangeDataSwap()
            kline_topics = [i for i in self.kwargs['topics'] if i['topic'] == "kline"]
            kline_kwargs['topics'] = kline_topics
            OkxKlineWssDataSwap(self.data_queue, **kline_kwargs).start()
        ticker_true = "ticker" in topic_list
        depth_true = "depth" in topic_list
        funding_rate_true = "funding_rate" in topic_list
        mark_price_true = "mark_price" in topic_list
        if ticker_true or depth_true or funding_rate_true or mark_price_true:
            market_kwargs = {key: v for key, v in self.kwargs.items()}
            market_kwargs['wss_name'] = 'okx_spot_market_data'
            market_kwargs["wss_url"] = 'wss://ws.okx.com:8443/ws/v5/public'
            market_kwargs["exchange_data"] = OkxExchangeDataSwap()
            market_topics = [i for i in self.kwargs['topics'] if i['topic'] != "kline"]
            market_kwargs['topics'] = market_topics
            OkxMarketWssDataSwap(self.data_queue, **market_kwargs).start()

        account_kwargs = {key: v for key, v in self.kwargs.items()}

        account_topics = [{"topic": "account", "symbol": self.symbol, "currency": "USDT"},
                          {"topic": "orders", "symbol": self.symbol},
                          {"topic": "positions", "symbol": self.symbol}]
        account_kwargs['topics'] = account_topics
        account_kwargs['exchange_data'] = OkxExchangeDataSwap()
        OkxAccountWssDataSwap(self.data_queue, **account_kwargs).start()

    def get_granularity(self, timeframe, compression):
        granularity = self._GRANULARITIES.get((timeframe, compression))
        if granularity is None:
            raise ValueError("backtrader bt_api_py module doesn't support fetching OHLCV "
                             "data for time frame %s, comression %s" % \
                             (bt.TimeFrame.getname(timeframe), compression))

        return granularity





