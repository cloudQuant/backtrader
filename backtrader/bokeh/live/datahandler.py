#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Live data handler.

Handles real-time data updates and pushes.
"""

import time
import logging
from enum import Enum
from threading import Thread, Lock

try:
    from tornado import gen
    TORNADO_AVAILABLE = True
except ImportError:
    TORNADO_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

_logger = logging.getLogger(__name__)


class UpdateType(Enum):
    """Data update type."""
    ADD = 1     # Add new data
    UPDATE = 2  # Update existing data


class LiveDataHandler:
    """Live data handler.
    
    Responsible for receiving, storing and pushing real-time data.
    
    Attributes:
        _doc: Bokeh document
        _app: BacktraderBokeh application
        _figid: Figure page ID
        _lookback: Historical data retention
        _fill_gaps: Whether to fill data gaps
    """
    
    def __init__(self, doc, app, figid, lookback, fill_gaps=True, timeout=1):
        """Initialize data handler.
        
        Args:
            doc: Bokeh document
            app: BacktraderBokeh application
            figid: Figure page ID
            lookback: Historical data retention
            fill_gaps: Whether to fill data gaps
            timeout: Thread timeout
        """
        self._doc = doc
        self._app = app
        self._figid = figid
        self._lookback = lookback
        self._fill_gaps = fill_gaps
        self._timeout = timeout
        
        # Get figurepage
        self._figurepage = app.get_figurepage(figid)
        
        # Thread related
        self._thread = Thread(target=self._t_thread, daemon=True)
        self._lock = Lock()
        self._running = True
        self._new_data = False
        
        # Data storage
        self._datastore = None
        self._last_idx = -1
        self._patches = []
        
        # Callbacks
        self._cb_patch = None
        self._cb_add = None
        
        # Initial data fill
        self._fill()
        
        # Start thread
        self._thread.start()
    
    def _fill(self):
        """Fill initial data."""
        if not PANDAS_AVAILABLE:
            return
        
        df = self._app.generate_data(
            figid=self._figid,
            back=self._lookback,
            preserveidx=True,
            fill_gaps=self._fill_gaps
        )
        
        self._set_data(df)
        
        # Initialize CDS columns
        if self._figurepage is not None and hasattr(self._figurepage, 'set_cds_columns_from_df'):
            self._figurepage.set_cds_columns_from_df(self._datastore)
    
    def _set_data(self, data, idx=None):
        """Set or append data.
        
        Args:
            data: DataFrame or Series
            idx: Index (for updating specific row)
        """
        if not PANDAS_AVAILABLE:
            return
        
        with self._lock:
            if isinstance(data, pd.DataFrame):
                self._datastore = data
                self._last_idx = -1
            elif isinstance(data, pd.Series):
                if idx is None:
                    self._datastore = pd.concat([self._datastore, data.to_frame().T])
                else:
                    self._datastore.loc[idx] = data
            else:
                _logger.warning(f'Unsupported data type: {type(data)}')
                return
            
            # Keep data length within lookback range
            if self._datastore is not None:
                self._datastore = self._datastore.tail(self._get_data_stream_length())
    
    def _cb_push_adds(self):
        """Push new data to ColumnDataSources."""
        if self._datastore is None or 'index' not in self._datastore.columns:
            return
        
        # Get data not yet pushed
        update_df = self._datastore[self._datastore['index'] > self._last_idx]
        
        if update_df.shape[0] == 0:
            return
        
        # Update last pushed index
        self._last_idx = update_df['index'].iloc[-1]
        
        fp = self._figurepage
        if fp is None:
            return
        
        # Push to figurepage
        if hasattr(fp, 'get_cds_streamdata_from_df') and hasattr(fp, 'cds'):
            data = fp.get_cds_streamdata_from_df(update_df)
            if data:
                _logger.debug(f'Streaming data to figurepage: {len(data)} columns')
                fp.cds.stream(data, self._get_data_stream_length())
        
        # Push to each figure
        if hasattr(fp, 'figures'):
            for f in fp.figures:
                if hasattr(f, 'get_cds_streamdata_from_df') and hasattr(f, 'cds'):
                    data = f.get_cds_streamdata_from_df(update_df)
                    if data:
                        f.cds.stream(data, self._get_data_stream_length())
    
    def _cb_push_patches(self):
        """Push patch data to ColumnDataSources."""
        patches = []
        while len(self._patches) > 0:
            patches.append(self._patches.pop(0))
        
        if len(patches) == 0:
            return
        
        fp = self._figurepage
        if fp is None:
            return
        
        for patch in patches:
            # Patch figurepage
            if hasattr(fp, 'get_cds_patchdata_from_series') and hasattr(fp, 'cds'):
                p_data, s_data = fp.get_cds_patchdata_from_series(patch)
                if len(p_data) > 0:
                    _logger.debug(f'Patching figurepage: {len(p_data)} fields')
                    fp.cds.patch(p_data)
                if len(s_data) > 0:
                    fp.cds.stream(s_data, self._get_data_stream_length())
            
            # Patch all figures
            if hasattr(fp, 'figures'):
                for f in fp.figures:
                    if not hasattr(f, 'get_cds_patchdata_from_series') or not hasattr(f, 'cds'):
                        continue
                    
                    # Determine whether to fill NaN
                    c_fill_nan = []
                    if not self._fill_gaps and hasattr(f, 'fill_nan'):
                        c_fill_nan = f.fill_nan()
                    
                    p_data, s_data = f.get_cds_patchdata_from_series(patch, c_fill_nan)
                    if len(p_data) > 0:
                        f.cds.patch(p_data)
                    if len(s_data) > 0:
                        f.cds.stream(s_data, self._get_data_stream_length())
    
    def _push_adds(self):
        """Trigger new data push."""
        if self._doc is None:
            return
        
        try:
            if self._cb_add is not None:
                self._doc.remove_next_tick_callback(self._cb_add)
        except ValueError:
            pass
        
        self._cb_add = self._doc.add_next_tick_callback(self._cb_push_adds)
    
    def _push_patches(self):
        """Trigger patch data push."""
        if self._doc is None:
            return
        
        try:
            if self._cb_patch is not None:
                self._doc.remove_next_tick_callback(self._cb_patch)
        except ValueError:
            pass
        
        self._cb_patch = self._doc.add_next_tick_callback(self._cb_push_patches)
    
    def _process(self, rows):
        """Process new data rows.
        
        Args:
            rows: DataFrame containing new data
        """
        if not PANDAS_AVAILABLE or rows is None:
            return
        
        for idx, row in rows.iterrows():
            if (self._datastore is not None and 
                self._datastore.shape[0] > 0 and
                'index' in self._datastore.columns and
                idx in self._datastore['index'].values):
                update_type = UpdateType.UPDATE
            else:
                update_type = UpdateType.ADD
            
            if update_type == UpdateType.UPDATE:
                ds_idx = self._datastore.loc[
                    self._datastore['index'] == idx].index[0]
                self._set_data(row, ds_idx)
                self._patches.append(row)
                self._push_patches()
            else:
                self._set_data(row)
                self._push_adds()
    
    def _t_thread(self):
        """Data processing thread."""
        while self._running:
            if self._new_data:
                last_idx = self.get_last_idx()
                last_avail_idx = self._app.get_last_idx(self._figid)
                
                if last_avail_idx - last_idx > (2 * self._lookback):
                    # If new data exceeds lookback length, load from end
                    data = self._app.generate_data(
                        figid=self._figid,
                        back=self._lookback,
                        preserveidx=True,
                        fill_gaps=self._fill_gaps
                    )
                else:
                    # Otherwise load from last index
                    data = self._app.generate_data(
                        figid=self._figid,
                        start=last_idx,
                        preserveidx=True,
                        fill_gaps=self._fill_gaps
                    )
                
                self._new_data = False
                self._process(data)
            
            time.sleep(self._timeout)
    
    def _get_data_stream_length(self):
        """Get data stream length.
        
        Returns:
            int: Data stream length
        """
        if self._datastore is None:
            return self._lookback
        return min(self._lookback, self._datastore.shape[0])
    
    def get_last_idx(self):
        """Get last data index.
        
        Returns:
            int: Last index, returns -1 if no data
        """
        if self._datastore is not None and self._datastore.shape[0] > 0:
            if 'index' in self._datastore.columns:
                return self._datastore['index'].iloc[-1]
        return -1
    
    def set(self, df):
        """Set new DataFrame and push.
        
        Args:
            df: New DataFrame
        """
        self._set_data(df)
        self._push_adds()
    
    def update(self):
        """Notify that new data is available."""
        if self._running:
            self._new_data = True
    
    def stop(self):
        """Stop data handler."""
        self._running = False
        
        # Remove pending callbacks
        try:
            if self._cb_patch is not None:
                self._doc.remove_next_tick_callback(self._cb_patch)
        except (ValueError, AttributeError):
            pass
        
        try:
            if self._cb_add is not None:
                self._doc.remove_next_tick_callback(self._cb_add)
        except (ValueError, AttributeError):
            pass
        
        # Wait for thread to finish
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)
