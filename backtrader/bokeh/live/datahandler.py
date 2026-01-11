#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
实时数据处理器

处理实时数据的更新和推送
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
    """数据更新类型"""
    ADD = 1     # 新增数据
    UPDATE = 2  # 更新现有数据


class LiveDataHandler:
    """实时数据处理器
    
    负责处理实时数据的接收、存储和推送。
    
    属性:
        _doc: Bokeh 文档
        _app: BacktraderBokeh 应用
        _figid: 图表页面 ID
        _lookback: 历史数据保留量
        _fill_gaps: 是否填充数据间隙
    """
    
    def __init__(self, doc, app, figid, lookback, fill_gaps=True, timeout=1):
        """初始化数据处理器
        
        Args:
            doc: Bokeh 文档
            app: BacktraderBokeh 应用
            figid: 图表页面 ID
            lookback: 历史数据保留量
            fill_gaps: 是否填充数据间隙
            timeout: 线程超时时间
        """
        self._doc = doc
        self._app = app
        self._figid = figid
        self._lookback = lookback
        self._fill_gaps = fill_gaps
        self._timeout = timeout
        
        # 获取 figurepage
        self._figurepage = app.get_figurepage(figid)
        
        # 线程相关
        self._thread = Thread(target=self._t_thread, daemon=True)
        self._lock = Lock()
        self._running = True
        self._new_data = False
        
        # 数据存储
        self._datastore = None
        self._last_idx = -1
        self._patches = []
        
        # 回调
        self._cb_patch = None
        self._cb_add = None
        
        # 初始填充数据
        self._fill()
        
        # 启动线程
        self._thread.start()
    
    def _fill(self):
        """填充初始数据"""
        if not PANDAS_AVAILABLE:
            return
        
        df = self._app.generate_data(
            figid=self._figid,
            back=self._lookback,
            preserveidx=True,
            fill_gaps=self._fill_gaps
        )
        
        self._set_data(df)
        
        # 初始化 CDS 列
        if self._figurepage is not None and hasattr(self._figurepage, 'set_cds_columns_from_df'):
            self._figurepage.set_cds_columns_from_df(self._datastore)
    
    def _set_data(self, data, idx=None):
        """设置或追加数据
        
        Args:
            data: DataFrame 或 Series
            idx: 索引（用于更新特定行）
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
            
            # 保持数据长度在 lookback 范围内
            if self._datastore is not None:
                self._datastore = self._datastore.tail(self._get_data_stream_length())
    
    def _cb_push_adds(self):
        """推送新增数据到 ColumnDataSources"""
        if self._datastore is None or 'index' not in self._datastore.columns:
            return
        
        # 获取尚未推送的数据
        update_df = self._datastore[self._datastore['index'] > self._last_idx]
        
        if update_df.shape[0] == 0:
            return
        
        # 更新最后推送的索引
        self._last_idx = update_df['index'].iloc[-1]
        
        fp = self._figurepage
        if fp is None:
            return
        
        # 推送到 figurepage
        if hasattr(fp, 'get_cds_streamdata_from_df') and hasattr(fp, 'cds'):
            data = fp.get_cds_streamdata_from_df(update_df)
            if data:
                _logger.debug(f'Streaming data to figurepage: {len(data)} columns')
                fp.cds.stream(data, self._get_data_stream_length())
        
        # 推送到每个 figure
        if hasattr(fp, 'figures'):
            for f in fp.figures:
                if hasattr(f, 'get_cds_streamdata_from_df') and hasattr(f, 'cds'):
                    data = f.get_cds_streamdata_from_df(update_df)
                    if data:
                        f.cds.stream(data, self._get_data_stream_length())
    
    def _cb_push_patches(self):
        """推送补丁数据到 ColumnDataSources"""
        patches = []
        while len(self._patches) > 0:
            patches.append(self._patches.pop(0))
        
        if len(patches) == 0:
            return
        
        fp = self._figurepage
        if fp is None:
            return
        
        for patch in patches:
            # 补丁 figurepage
            if hasattr(fp, 'get_cds_patchdata_from_series') and hasattr(fp, 'cds'):
                p_data, s_data = fp.get_cds_patchdata_from_series(patch)
                if len(p_data) > 0:
                    _logger.debug(f'Patching figurepage: {len(p_data)} fields')
                    fp.cds.patch(p_data)
                if len(s_data) > 0:
                    fp.cds.stream(s_data, self._get_data_stream_length())
            
            # 补丁所有 figures
            if hasattr(fp, 'figures'):
                for f in fp.figures:
                    if not hasattr(f, 'get_cds_patchdata_from_series') or not hasattr(f, 'cds'):
                        continue
                    
                    # 确定是否填充 NaN
                    c_fill_nan = []
                    if not self._fill_gaps and hasattr(f, 'fill_nan'):
                        c_fill_nan = f.fill_nan()
                    
                    p_data, s_data = f.get_cds_patchdata_from_series(patch, c_fill_nan)
                    if len(p_data) > 0:
                        f.cds.patch(p_data)
                    if len(s_data) > 0:
                        f.cds.stream(s_data, self._get_data_stream_length())
    
    def _push_adds(self):
        """触发新增数据推送"""
        if self._doc is None:
            return
        
        try:
            if self._cb_add is not None:
                self._doc.remove_next_tick_callback(self._cb_add)
        except ValueError:
            pass
        
        self._cb_add = self._doc.add_next_tick_callback(self._cb_push_adds)
    
    def _push_patches(self):
        """触发补丁数据推送"""
        if self._doc is None:
            return
        
        try:
            if self._cb_patch is not None:
                self._doc.remove_next_tick_callback(self._cb_patch)
        except ValueError:
            pass
        
        self._cb_patch = self._doc.add_next_tick_callback(self._cb_push_patches)
    
    def _process(self, rows):
        """处理新数据行
        
        Args:
            rows: DataFrame 包含新数据
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
        """数据处理线程"""
        while self._running:
            if self._new_data:
                last_idx = self.get_last_idx()
                last_avail_idx = self._app.get_last_idx(self._figid)
                
                if last_avail_idx - last_idx > (2 * self._lookback):
                    # 如果新数据超过 lookback 长度，从末尾加载
                    data = self._app.generate_data(
                        figid=self._figid,
                        back=self._lookback,
                        preserveidx=True,
                        fill_gaps=self._fill_gaps
                    )
                else:
                    # 否则从上次索引加载
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
        """获取数据流长度
        
        Returns:
            int: 数据流长度
        """
        if self._datastore is None:
            return self._lookback
        return min(self._lookback, self._datastore.shape[0])
    
    def get_last_idx(self):
        """获取最后的数据索引
        
        Returns:
            int: 最后索引，如果无数据则返回 -1
        """
        if self._datastore is not None and self._datastore.shape[0] > 0:
            if 'index' in self._datastore.columns:
                return self._datastore['index'].iloc[-1]
        return -1
    
    def set(self, df):
        """设置新的 DataFrame 并推送
        
        Args:
            df: 新的 DataFrame
        """
        self._set_data(df)
        self._push_adds()
    
    def update(self):
        """通知有新数据可用"""
        if self._running:
            self._new_data = True
    
    def stop(self):
        """停止数据处理器"""
        self._running = False
        
        # 移除待处理的回调
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
        
        # 等待线程结束
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)
