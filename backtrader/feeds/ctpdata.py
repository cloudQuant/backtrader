"""CTP Data Feed Module - CTP futures data via ctp-python.

This module provides the CTPData feed for connecting to CTP (China Futures)
using the ctp-python package for live tick data and akshare for historical
backfill.

Classes:
    CTPData: CTP futures data feed.

Example:
    >>> store = bt.stores.CTPStore(
    ...     user_id='your_id',
    ...     password='your_password',
    ... )
    >>> data = store.getdata(dataname='rb2501.SHFE')
    >>> cerebro.adddata(data)
"""

import logging
from datetime import datetime, timedelta

import pytz

from backtrader.feed import DataBase
from backtrader.stores.ctpstore import CTPStore
from backtrader.utils.py3 import queue

from ..utils import date2num

logger = logging.getLogger(__name__)

CHINA_TZ = pytz.timezone("Asia/Shanghai")


class CTPData(DataBase):
    """CTP Data Feed via ctp-python.

    Receives live tick data from CTPStore's MdSpi and aggregates ticks
    into bars based on timeframe/compression. Historical backfill uses
    akshare.

    Params:
      - ``historical`` (default: ``False``): Stop after backfill.
      - ``num_init_backfill`` (default: ``100``): Number of bars to backfill.
    """

    params = (
        ("historical", False),
        ("num_init_backfill", 100),
    )

    _store = CTPStore

    # States for the Finite State Machine in _load
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)

    def islive(self):
        """True notifies `Cerebro` that `preloading` and `runonce` should be deactivated."""
        return True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        CTPStore.DataCls = self.__class__

        self._state = None
        self.o = self._store(**kwargs)
        # Register tick queue for this instrument
        self.qlive = self.o.register(self)
        self._instrument = self.p.dataname.split('.')[0] if '.' in self.p.dataname else self.p.dataname

        # Bar aggregation state
        self._bar_compression_secs = self._calc_bar_seconds()
        self._bar_open = 0.0
        self._bar_high = 0.0
        self._bar_low = 0.0
        self._bar_close = 0.0
        self._bar_volume = 0
        self._bar_oi = 0.0
        self._bar_dt = None
        self._bar_end_dt = None
        self._last_tick_volume = 0

    def _calc_bar_seconds(self):
        """Calculate bar duration in seconds based on timeframe/compression."""
        # timeframe: 4=Minutes, 5=Days
        if self._timeframe == 4:  # Minutes
            return 60 * self._compression
        elif self._timeframe == 5:  # Days
            return 86400 * self._compression
        else:
            return 60  # default 1 minute

    def start(self):
        super().start()
        # Subscribe to market data via store
        self.o.subscribe(self.p.dataname)
        self._get_backfill_data()
        self._state = self._ST_HISTORBACK

    def _get_backfill_data(self):
        """Get backfill data from akshare."""
        self.put_notification(self.DELAYED)
        self.qhist = queue.Queue()

        if self.p.num_init_backfill <= 0:
            self.qhist.put({})
            return True

        try:
            import akshare as ak
            symbol = self._instrument
            if self._timeframe == 4:
                futures_sina_df = ak.futures_zh_minute_sina(
                    symbol=symbol, period=str(self._compression)
                ).tail(self.p.num_init_backfill)
            elif self._timeframe == 5:
                futures_sina_df = ak.futures_zh_daily_sina(symbol=symbol)
            else:
                futures_sina_df = ak.futures_zh_minute_sina(
                    symbol=symbol, period="1"
                ).tail(self.p.num_init_backfill)

            futures_sina_df.columns = [
                "datetime", "OpenPrice", "HighPrice", "LowPrice",
                "LastPrice", "BarVolume", "hold",
            ]
            futures_sina_df["symbol"] = self.p.dataname

            for i in range(min(self.p.num_init_backfill, len(futures_sina_df))):
                msg = futures_sina_df.iloc[i].to_dict()
                dt = datetime.strptime(msg["datetime"], "%Y-%m-%d %H:%M:%S")
                dt = CHINA_TZ.localize(dt)
                msg["datetime"] = dt
                msg["OpenPrice"] = float(msg["OpenPrice"])
                msg["HighPrice"] = float(msg["HighPrice"])
                msg["LowPrice"] = float(msg["LowPrice"])
                msg["LastPrice"] = float(msg["LastPrice"])
                msg["BarVolume"] = int(msg["BarVolume"])
                msg["hold"] = int(msg["hold"])
                msg["OpenInterest"] = 0
                self.qhist.put(msg)
        except Exception as e:
            logger.warning(f"[CTPData] Backfill failed: {e}")

        self.qhist.put({})
        return True

    def stop(self):
        super().stop()
        self.o.stop()

    def haslivedata(self):
        return not self.qlive.empty()

    def _load(self):
        if self._state == self._ST_OVER:
            return False

        while True:
            if self._state == self._ST_LIVE:
                return self._load_live()

            elif self._state == self._ST_HISTORBACK:
                msg = self.qhist.get()
                if msg is None:
                    self.put_notification(self.DISCONNECTED)
                    self._state = self._ST_OVER
                    return False
                elif msg:
                    if self._load_candle_history(msg):
                        return True
                    continue
                else:
                    if self.p.historical:
                        self.put_notification(self.DISCONNECTED)
                        self._state = self._ST_OVER
                        return False
                    self._state = self._ST_LIVE
                    self.put_notification(self.LIVE)

    def _load_live(self):
        """Aggregate ticks into bars from live tick queue."""
        while True:
            try:
                tick = self.qlive.get(timeout=0.1)
            except queue.Empty:
                return None

            if tick is None:
                continue

            last_price = tick.get('last_price', 0.0)
            tick_volume = tick.get('volume', 0)
            open_interest = tick.get('open_interest', 0.0)
            update_time = tick.get('update_time', '')
            action_day = tick.get('action_day', '')
            update_ms = tick.get('update_millisec', 0)

            if last_price == 0.0 or last_price >= 1e300:
                continue

            # Parse tick datetime
            try:
                if action_day and update_time:
                    tick_dt = datetime.strptime(
                        f"{action_day} {update_time}", "%Y%m%d %H:%M:%S"
                    )
                else:
                    tick_dt = datetime.now()
                tick_dt = CHINA_TZ.localize(tick_dt)
            except (ValueError, TypeError):
                tick_dt = datetime.now(CHINA_TZ)

            # Calculate incremental volume
            delta_vol = tick_volume - self._last_tick_volume
            if delta_vol < 0:
                delta_vol = tick_volume
            self._last_tick_volume = tick_volume

            # Initialize bar if needed
            if self._bar_dt is None:
                bar_secs = self._bar_compression_secs
                ts = tick_dt.timestamp()
                bar_start_ts = int(ts // bar_secs) * bar_secs
                self._bar_dt = datetime.fromtimestamp(bar_start_ts, tz=CHINA_TZ)
                self._bar_end_dt = self._bar_dt + timedelta(seconds=bar_secs)
                self._bar_open = last_price
                self._bar_high = last_price
                self._bar_low = last_price
                self._bar_close = last_price
                self._bar_volume = delta_vol
                self._bar_oi = open_interest
                continue

            # Check if tick is in a new bar period
            if tick_dt >= self._bar_end_dt:
                # Emit the completed bar
                dt_num = date2num(self._bar_end_dt)
                if dt_num <= self.lines.datetime[-1]:
                    # Time already seen, skip
                    pass
                else:
                    self.lines.datetime[0] = dt_num
                    self.lines.open[0] = self._bar_open
                    self.lines.high[0] = self._bar_high
                    self.lines.low[0] = self._bar_low
                    self.lines.close[0] = self._bar_close
                    self.lines.volume[0] = self._bar_volume
                    self.lines.openinterest[0] = self._bar_oi

                    # Start new bar
                    bar_secs = self._bar_compression_secs
                    ts = tick_dt.timestamp()
                    bar_start_ts = int(ts // bar_secs) * bar_secs
                    self._bar_dt = datetime.fromtimestamp(bar_start_ts, tz=CHINA_TZ)
                    self._bar_end_dt = self._bar_dt + timedelta(seconds=bar_secs)
                    self._bar_open = last_price
                    self._bar_high = last_price
                    self._bar_low = last_price
                    self._bar_close = last_price
                    self._bar_volume = delta_vol
                    self._bar_oi = open_interest
                    return True
            else:
                # Update current bar
                self._bar_high = max(self._bar_high, last_price)
                self._bar_low = min(self._bar_low, last_price)
                self._bar_close = last_price
                self._bar_volume += delta_vol
                self._bar_oi = open_interest

    def _load_candle_history(self, msg):
        """Load a historical bar from backfill data."""
        if msg.get("symbol") != self.p.dataname:
            return
        dt = date2num(msg["datetime"])
        if dt <= self.lines.datetime[-1]:
            return False
        self.lines.datetime[0] = dt
        self.lines.open[0] = msg["OpenPrice"]
        self.lines.high[0] = msg["HighPrice"]
        self.lines.low[0] = msg["LowPrice"]
        self.lines.close[0] = msg["LastPrice"]
        self.lines.volume[0] = msg["BarVolume"]
        self.lines.openinterest[0] = msg.get("OpenInterest", 0)
        return True
