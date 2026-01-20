#!/usr/bin/env python
"""Futu Data Feed Module - Futu OpenD data.

This module provides the FutuFeed for connecting to Futu OpenD
for Hong Kong/US/A-Share stock market data.

Classes:
    FutuFeed: Futu OpenD data feed.

Example:
    >>> store = bt.stores.FutuStore(host='127.0.0.1', port=11111)
    >>> data = bt.feeds.FutuFeed(
    ...     dataname='HK.00700',
    ...     store=store,
    ...     timeframe=bt.TimeFrame.Minutes,
    ...     compression=5
    ... )
    >>> cerebro.adddata(data)

Note:
    Requires futu-api package: pip install futu-api
"""

import time
from datetime import datetime, timezone

from backtrader.feed import DataBase
from backtrader.stores.futustore import FutuStore
from backtrader.utils.py3 import queue

from ..utils import date2num


class FutuFeed(DataBase):
    """Futu OpenD Data Feed.
    
    Params:
        - historical (default: False): If True, stop after downloading
          historical data.
        - backfill_start (default: True): Perform backfilling at start.
        - ohlcv_limit (default: 100): Maximum bars to fetch per request.
        - drop_newest (default: False): Drop the newest (incomplete) bar.
        - debug (default: False): Enable debug output.
    """
    
    params = (
        ('historical', False),
        ('backfill_start', True),
        ('ohlcv_limit', 100),
        ('drop_newest', False),
        ('debug', False),
    )
    
    _store = FutuStore
    
    # States for the Finite State Machine in _load
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)
    
    def __init__(self, **kwargs):
        """Initialize the Futu data feed.
        
        Args:
            **kwargs: Keyword arguments for configuration.
        """
        super().__init__(**kwargs)
        
        # Register with store
        FutuStore.DataCls = self.__class__
        
        self._state = None
        self.store = self._store(**kwargs)
        self._data = queue.Queue()
        self._last_ts = 0
        self._last_update_bar_time = 0
    
    def utc_to_ts(self, dt):
        """Convert datetime to timestamp in milliseconds.
        
        Args:
            dt: Datetime object.
            
        Returns:
            int: Timestamp in milliseconds.
        """
        fromdate = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
        epoch = datetime(1970, 1, 1)
        return int((fromdate - epoch).total_seconds() * 1000)
    
    def start(self):
        """Start the data feed."""
        DataBase.start(self)
        
        # Subscribe to market data
        self.store.subscribe(self.p.dataname)
        
        if self.p.fromdate:
            self._state = self._ST_HISTORBACK
            self.put_notification(self.DELAYED)
            self._update_bar(self.p.fromdate)
        else:
            self._state = self._ST_LIVE
            self.put_notification(self.LIVE)
    
    def stop(self):
        """Stop the data feed."""
        DataBase.stop(self)
        self.store.stop()
    
    def _load(self):
        """Load the next bar of data.
        
        Returns:
            True: Data loaded successfully.
            False: Data source closed.
            None: No data available yet.
        """
        if self._state == self._ST_OVER:
            return False
        
        while True:
            if self._state == self._ST_LIVE:
                # Calculate update interval based on timeframe
                timeframe = self._timeframe
                compression = self._compression
                
                if timeframe == 4:  # Minutes
                    time_diff = 60 * compression
                elif timeframe == 5:  # Days
                    time_diff = 86400 * compression
                else:
                    time_diff = 60
                
                # Check if we need to update
                nts = time.time()
                if nts - self._last_update_bar_time / 1000 >= time_diff + 2:
                    self._update_bar(livemode=True)
                
                return self._load_bar()
            
            elif self._state == self._ST_HISTORBACK:
                ret = self._load_bar()
                if ret:
                    return ret
                else:
                    # End of historical data
                    if self.p.historical:
                        self.put_notification(self.DISCONNECTED)
                        self._state = self._ST_OVER
                        return False
                    else:
                        self._state = self._ST_LIVE
                        self.put_notification(self.LIVE)
                        continue
    
    def _update_bar(self, fromdate=None, livemode=False):
        """Fetch OHLCV data from Futu.
        
        Args:
            fromdate: Start date for historical data.
            livemode: If True, running in live mode.
        """
        try:
            kl_type = self.store.get_granularity(self._timeframe, self._compression)
        except ValueError as e:
            print(f"Error getting granularity: {e}")
            return
        
        # Determine start date
        start = None
        if fromdate:
            self._last_ts = self.utc_to_ts(fromdate)
            start = fromdate.strftime('%Y-%m-%d')
        
        limit = max(3, self.p.ohlcv_limit)
        
        while True:
            dlen = self._data.qsize()
            
            # Fetch data from Futu
            bars = self.store.fetch_ohlcv(
                self.p.dataname,
                kl_type=kl_type,
                start=start,
                limit=limit
            )
            
            # Sort by timestamp
            bars = sorted(bars, key=lambda x: x[0])
            
            # Drop newest if configured
            if self.p.drop_newest and len(bars) > 0:
                del bars[-1]
            
            # Process bars
            for bar in bars:
                if None in bar:
                    continue
                
                tstamp = bar[0]
                if tstamp > self._last_ts:
                    self._data.put(bar)
                    self._last_ts = tstamp
                    self._last_update_bar_time = tstamp
            
            # Exit if no new data
            if dlen == self._data.qsize():
                break
            
            # In live mode, don't loop
            if livemode:
                break
    
    def _load_bar(self):
        """Load a bar from the queue into lines.
        
        Returns:
            True if bar loaded, None if no data.
        """
        try:
            bar = self._data.get(block=False)
        except queue.Empty:
            return None
        
        tstamp, open_, high, low, close, volume = bar
        dtime = datetime.utcfromtimestamp(tstamp // 1000)
        
        self.lines.datetime[0] = date2num(dtime)
        self.lines.open[0] = open_
        self.lines.high[0] = high
        self.lines.low[0] = low
        self.lines.close[0] = close
        self.lines.volume[0] = volume
        
        return True
    
    def haslivedata(self):
        """Check if live data is available.
        
        Returns:
            bool: True if in live mode and queue not empty.
        """
        return self._state == self._ST_LIVE and not self._data.empty()
    
    def islive(self):
        """Check if feed is in live mode.
        
        Returns:
            bool: True if not historical-only mode.
        """
        return not self.p.historical
