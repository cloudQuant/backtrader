import time
from datetime import datetime, timedelta, timezone
from functools import wraps
import queue
from logging import raiseExceptions

import backtrader as bt
from backtrader.store import MetaSingleton
from backtrader.metabase import MetaParams
from backtrader.utils.py3 import with_metaclass
from bt_api_py.functions.log_message import SpdLogManager


class CryptoStore(with_metaclass(MetaSingleton, object)):
    """bt_api_py and backtrader store
    """
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

    def __init__(self, exchange, asset_type, symbol, debug=False, currency="USDT", **kwargs):
        self.exchange = exchange
        self.asset_type = asset_type
        self.symbol = symbol
        self.currency = currency
        self.kwargs = kwargs
        self.data_queue = queue.Queue()
        self.feed = None
        self.debug = debug
        self._cash = 0
        self._value = 0
        self.logger = self.init_logger()
        self.init_feed(exchange, asset_type, **kwargs)
        self.update_balance()


    def init_logger(self):
        if self.debug:
            print_info = True
        else:
            print_info = False
        logger = SpdLogManager(file_name='cryptofeed.log',
                               logger_name="feed",
                               print_info=print_info).create_logger()
        return logger

    def log(self, txt, level="info"):
        if level == "info":
            self.logger.info(txt)
        elif level == "warning":
            self.logger.warning(txt)
        elif level == "error":
            self.logger.error(txt)
        elif level == "debug":
            self.logger.debug(txt)
        else:
            pass


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

    def push_bar_data_to_queue(self, data):
        bar_list = data.get_data()
        for bar in bar_list:
            self.data_queue.put(bar)

    def download_history_bars(self, symbol, period, count=100, start_time=None, end_time=None, extra_data=None):
        def calculate_time_delta(period):
            """根据 period 计算增量时间"""
            time_deltas = {
                "1m": timedelta(hours=1),
                "3m": timedelta(hours=5),
                "5m": timedelta(hours=9),
                "15m": timedelta(hours=25),
                "30m": timedelta(hours=50),
                "1H": timedelta(hours=100),
                "1D": timedelta(days=100),
            }
            if period in time_deltas:
                return time_deltas[period]
            raise ValueError(f"Unsupported period: {period}")

        def parse_time(input_time):
            """解析时间，支持字符串和 datetime 类型，并将时间转换为 UTC"""
            if isinstance(input_time, str):
                # 假设输入的字符串时间是本地时间
                local_time = datetime.fromisoformat(input_time)
                return local_time.astimezone(timezone.utc)
            elif isinstance(input_time, datetime):
                # 如果是 datetime 类型，确保转换为 UTC
                if input_time.tzinfo is None:
                    local_time = input_time.replace(tzinfo=timezone.utc).astimezone()  # 假设为本地时间
                else:
                    local_time = input_time
                return local_time.astimezone(timezone.utc)
            elif input_time is None:
                return None
            else:
                raise TypeError(f"Unsupported time format: {type(input_time)}")

        # 解析开始时间和结束时间为 UTC
        begin_time = parse_time(start_time)
        stop_time = parse_time(end_time)

        if begin_time is None and count is not None:
            # 如果没有开始时间，只传入 count，获取最近 count 条数据
            data = self.feed.get_kline(symbol, period, count, extra_data=extra_data)
            self.push_bar_data_to_queue(data)
            self.log(f"download completely: {symbol}, new {count} bar")
            return

        if begin_time is not None:
            # 如果未提供结束时间，则默认为当前时间并对齐到 period
            if stop_time is None:
                now = datetime.now(timezone.utc)  # 当前时间为 UTC
                period_seconds = int(period[:-1]) * 60 if "m" in period else int(period[:-1]) * 3600
                stop_time = now - timedelta(seconds=now.timestamp() % period_seconds)

            # 循环下载数据
            while begin_time < stop_time:
                try:
                    # 计算当前时间段的结束时间
                    time_delta = calculate_time_delta(period)
                    current_end_time = min(begin_time + time_delta, stop_time)

                    # 转换时间戳为毫秒
                    begin_stamp = int(begin_time.timestamp() * 1000)
                    end_stamp = int(current_end_time.timestamp() * 1000)

                    # 下载数据
                    data = self.feed.get_kline(
                        symbol, period, start_time=begin_stamp, end_time=end_stamp, extra_data=extra_data
                    )
                    self.push_bar_data_to_queue(data)
                    print(f"download successfully: {symbol}, period: {period}, "
                          f"begin: {begin_time}, end: {current_end_time}")

                    # 更新开始时间
                    begin_time = current_end_time

                    # 如果数据已经下载完成，跳出循环
                    if begin_time >= stop_time:
                        break
                except Exception as e:
                    print(f"download fail, retry: {e}")
                    time.sleep(3)  # 暂停 3 秒后重试

            print(f"download all data completely: {symbol}, period: {period}")

    def get_wallet_balance(self, currency_list):
        balance_data = self.feed.get_balance()
        balance_data.init_data()
        account_list = balance_data.get_data()
        result = {}
        for account in account_list:
            account.init_data()
            currency = account.get_account_type()
            if currency in currency_list:
                result[currency] = {}
                result[currency]['cash'] = account.get_available_margin()
                result[currency]['value'] = account.get_margin() + account.get_unrealized_profit()
        for currency in currency_list:
            if currency not in result:
                result[currency] = {}
                result[currency]['cash'] = 0
                result[currency]['value'] = 0
        return result

    def update_balance(self):
        balance_data = self.feed.get_balance()
        balance_data.init_data()
        account_list = balance_data.get_data()
        update_value_cash = False
        for account in account_list:
            account.init_data()
            if account.get_account_type() == self.currency:
                self._value = account.get_margin() + account.get_unrealized_profit()
                self._cash = account.get_available_margin()
                update_value_cash = True
        if not update_value_cash:
            raise f"cannot find {self.currency} balance in get_balance()"
        else:
            self.log(f" now value is {self._value}, now cash is {self._cash}")

    def get_cash(self):
        return self._cash

    def get_value(self):
        return self._value
