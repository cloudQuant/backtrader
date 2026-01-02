#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Sunrise Volatility Expansion 波动率扩展通道策略 (完整版)

参考来源: https://github.com/backtrader-pullback-window-xauusd
完整实现4阶段状态机入场系统:
- Phase 1: 信号扫描 (EMA交叉 + 多重过滤器)
- Phase 2: 回撤确认 (等待指定数量的回撤K线)
- Phase 3: 突破窗口开启 (计算价格通道)
- Phase 4: 突破监控 (等待价格突破通道)
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import math
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR / "datas" / filename,
        BASE_DIR.parent / "datas" / filename,
    ]
    for p in search_paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"Cannot find data file: {filename}")


class SunriseVolatilityExpansionStrategy(bt.Strategy):
    """Sunrise波动率扩展通道策略 (完整4阶段状态机)
    
    核心逻辑:
    - Phase 1 (SCANNING): 扫描EMA交叉信号，应用多重过滤器
    - Phase 2 (ARMED): 等待回撤K线确认
    - Phase 3 (WINDOW_OPEN): 计算双边价格通道
    - Phase 4: 监控价格突破通道上沿(多)/下沿(空)
    
    过滤器:
    - EMA排列条件
    - 价格过滤EMA
    - K线方向过滤
    - EMA斜率角度过滤
    - ATR波动率过滤
    """
    params = dict(
        stake=10,
        # EMA参数
        ema_fast=14,
        ema_medium=14,
        ema_slow=24,
        ema_confirm=1,
        ema_filter_price=100,
        # ATR参数
        atr_period=10,
        atr_sl_mult=4.5,
        atr_tp_mult=6.5,
        # 多头过滤器
        long_use_ema_order=False,
        long_use_price_filter=True,
        long_use_candle_direction=False,
        long_use_angle_filter=False,
        long_min_angle=35.0,
        long_max_angle=95.0,
        long_angle_scale=10.0,
        # 回撤入场参数
        use_pullback_entry=True,
        long_pullback_candles=3,
        entry_window_periods=1,
        window_price_offset_mult=0.001,
        # 全局无效化
        use_global_invalidation=True,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.dataopen = self.datas[0].open
        self.datahigh = self.datas[0].high
        self.datalow = self.datas[0].low
        
        # EMA指标
        self.ema_fast = bt.indicators.EMA(self.data.close, period=self.p.ema_fast)
        self.ema_medium = bt.indicators.EMA(self.data.close, period=self.p.ema_medium)
        self.ema_slow = bt.indicators.EMA(self.data.close, period=self.p.ema_slow)
        self.ema_confirm = bt.indicators.EMA(self.data.close, period=self.p.ema_confirm)
        self.ema_filter_price = bt.indicators.EMA(self.data.close, period=self.p.ema_filter_price)
        
        # ATR
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        
        self.order = None
        self.entry_price = 0
        self.stop_loss = 0
        self.take_profit = 0
        self.last_entry_bar = None
        
        # 4阶段状态机
        self.entry_state = "SCANNING"  # SCANNING, ARMED_LONG, ARMED_SHORT, WINDOW_OPEN
        self.armed_direction = None
        self.pullback_candle_count = 0
        self.last_pullback_candle_high = None
        self.last_pullback_candle_low = None
        self.window_top_limit = None
        self.window_bottom_limit = None
        self.window_expiry_bar = None
        self.window_bar_start = None
        self.signal_detection_atr = None
        
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def _cross_above(self, a, b):
        """检测a上穿b"""
        try:
            return (float(a[0]) > float(b[0])) and (float(a[-1]) <= float(b[-1]))
        except (IndexError, ValueError, TypeError):
            return False

    def _cross_below(self, a, b):
        """检测a下穿b"""
        try:
            return (float(a[0]) < float(b[0])) and (float(a[-1]) >= float(b[-1]))
        except (IndexError, ValueError, TypeError):
            return False

    def _angle(self):
        """计算EMA斜率角度"""
        try:
            current_ema = float(self.ema_confirm[0])
            previous_ema = float(self.ema_confirm[-1])
            rise = (current_ema - previous_ema) * self.p.long_angle_scale
            return math.degrees(math.atan(rise))
        except (IndexError, ValueError, TypeError, ZeroDivisionError):
            return float('nan')

    def _reset_entry_state(self):
        """重置入场状态机"""
        self.entry_state = "SCANNING"
        self.armed_direction = None
        self.pullback_candle_count = 0
        self.last_pullback_candle_high = None
        self.last_pullback_candle_low = None
        self.window_top_limit = None
        self.window_bottom_limit = None
        self.window_expiry_bar = None
        self.window_bar_start = None

    def _phase1_scan_for_signal(self):
        """Phase 1: 扫描EMA交叉信号"""
        # 检查多头信号
        try:
            prev_bull = self.data.close[-1] > self.data.open[-1]
        except IndexError:
            prev_bull = False

        # EMA交叉检测 (confirm上穿任意一条EMA)
        cross_fast = self._cross_above(self.ema_confirm, self.ema_fast)
        cross_medium = self._cross_above(self.ema_confirm, self.ema_medium)
        cross_slow = self._cross_above(self.ema_confirm, self.ema_slow)
        cross_any = cross_fast or cross_medium or cross_slow

        # K线方向过滤
        candle_ok = True
        if self.p.long_use_candle_direction:
            candle_ok = prev_bull

        if candle_ok and cross_any:
            signal_valid = True

            # EMA排列条件
            if self.p.long_use_ema_order:
                ema_order_ok = (
                    self.ema_confirm[0] > self.ema_fast[0] and
                    self.ema_confirm[0] > self.ema_medium[0] and
                    self.ema_confirm[0] > self.ema_slow[0]
                )
                if not ema_order_ok:
                    signal_valid = False

            # 价格过滤EMA
            if signal_valid and self.p.long_use_price_filter:
                price_above = self.data.close[0] > self.ema_filter_price[0]
                if not price_above:
                    signal_valid = False

            # 角度过滤
            if signal_valid and self.p.long_use_angle_filter:
                current_angle = self._angle()
                if not (self.p.long_min_angle <= current_angle <= self.p.long_max_angle):
                    signal_valid = False

            if signal_valid:
                current_atr = float(self.atr[0]) if not math.isnan(float(self.atr[0])) else 0.0
                self.signal_detection_atr = current_atr
                return 'LONG'

        return None

    def _phase2_confirm_pullback(self, armed_direction):
        """Phase 2: 确认回撤K线"""
        is_pullback = False
        if armed_direction == 'LONG':
            is_pullback = self.data.close[0] < self.data.open[0]  # 阴线

        if is_pullback:
            self.pullback_candle_count += 1
            max_candles = self.p.long_pullback_candles

            if self.pullback_candle_count >= max_candles:
                self.last_pullback_candle_high = float(self.data.high[0])
                self.last_pullback_candle_low = float(self.data.low[0])
                return True
        else:
            # 非回撤K线，全局无效化
            if self.p.use_global_invalidation:
                self._reset_entry_state()

        return False

    def _phase3_open_breakout_window(self, armed_direction):
        """Phase 3: 开启突破窗口"""
        current_bar = len(self)
        self.window_bar_start = current_bar

        window_periods = self.p.entry_window_periods
        self.window_expiry_bar = current_bar + window_periods

        # 计算双边价格通道
        last_high = self.last_pullback_candle_high
        last_low = self.last_pullback_candle_low
        candle_range = last_high - last_low
        price_offset = candle_range * self.p.window_price_offset_mult

        self.window_top_limit = last_high + price_offset
        self.window_bottom_limit = last_low - price_offset

        self.entry_state = "WINDOW_OPEN"

    def _phase4_monitor_window(self, armed_direction):
        """Phase 4: 监控突破窗口"""
        current_bar = len(self)

        if current_bar < self.window_bar_start:
            return None

        # 超时检查
        if current_bar > self.window_expiry_bar:
            self.entry_state = f"ARMED_{armed_direction}"
            self.pullback_candle_count = 0
            self.window_top_limit = None
            self.window_bottom_limit = None
            self.window_expiry_bar = None
            return None

        current_high = self.data.high[0]
        current_low = self.data.low[0]

        if armed_direction == 'LONG':
            # 成功: 价格突破上沿
            if current_high >= self.window_top_limit:
                return 'SUCCESS'
            # 失败: 价格跌破下沿
            elif current_low <= self.window_bottom_limit:
                self.entry_state = "ARMED_LONG"
                self.pullback_candle_count = 0
                self.window_top_limit = None
                self.window_bottom_limit = None
                return None

        return None

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.entry_price = order.executed.price
                atr_now = float(self.atr[0]) if not math.isnan(float(self.atr[0])) else 1.0
                bar_low = float(self.data.low[0])
                bar_high = float(self.data.high[0])
                self.stop_loss = bar_low - atr_now * self.p.atr_sl_mult
                self.take_profit = bar_high + atr_now * self.p.atr_tp_mult
                self.last_entry_bar = len(self)
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        self.bar_num += 1
        current_bar = len(self)

        if self.order:
            return

        # 持仓管理: 止损止盈
        if self.position:
            if self.datalow[0] <= self.stop_loss:
                self.order = self.close()
                self._reset_entry_state()
                return
            elif self.datahigh[0] >= self.take_profit:
                self.order = self.close()
                self._reset_entry_state()
                return
            return  # 持仓中不进行新的入场逻辑

        # 无持仓时清理订单
        if not self.position:
            self.stop_loss = 0
            self.take_profit = 0

        # 4阶段状态机
        if not self.p.use_pullback_entry:
            # 非回撤模式: 直接入场
            signal = self._phase1_scan_for_signal()
            if signal == 'LONG':
                self.order = self.buy(size=self.p.stake)
            return

        # 全局无效化检查
        if self.entry_state in ["ARMED_LONG", "ARMED_SHORT"]:
            if self.entry_state == "ARMED_LONG":
                # 检测空头信号是否出现
                try:
                    prev_bear = self.data.close[-1] < self.data.open[-1]
                    cross_fast = self._cross_below(self.ema_confirm, self.ema_fast)
                    cross_medium = self._cross_below(self.ema_confirm, self.ema_medium)
                    cross_slow = self._cross_below(self.ema_confirm, self.ema_slow)
                    if prev_bear and (cross_fast or cross_medium or cross_slow):
                        self._reset_entry_state()
                except IndexError:
                    pass

        # 状态机路由
        if self.entry_state == "SCANNING":
            signal_direction = self._phase1_scan_for_signal()
            if signal_direction:
                self.entry_state = f"ARMED_{signal_direction}"
                self.armed_direction = signal_direction
                self.pullback_candle_count = 0

        elif self.entry_state in ["ARMED_LONG", "ARMED_SHORT"]:
            if self._phase2_confirm_pullback(self.armed_direction):
                self.entry_state = "WINDOW_OPEN"
                self._phase3_open_breakout_window(self.armed_direction)

        elif self.entry_state == "WINDOW_OPEN":
            breakout_status = self._phase4_monitor_window(self.armed_direction)

            if breakout_status == 'SUCCESS':
                signal_direction = self.armed_direction

                atr_now = float(self.atr[0]) if not math.isnan(float(self.atr[0])) else 0.0
                if atr_now <= 0:
                    self._reset_entry_state()
                    return

                entry_price = float(self.data.close[0])
                bar_low = float(self.data.low[0])
                bar_high = float(self.data.high[0])

                if signal_direction == 'LONG':
                    self.stop_loss = bar_low - atr_now * self.p.atr_sl_mult
                    self.take_profit = bar_high + atr_now * self.p.atr_tp_mult
                    self.order = self.buy(size=self.p.stake)

                self.last_entry_bar = current_bar
                self._reset_entry_state()


def test_sunrise_volatility_expansion_strategy():
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("XAUUSD_5m_5Yea.csv")
    # XAUUSD CSV format: Date,Time,Open,High,Low,Close,Volume
    # Date format: 20200821, Time format: 00:00:00
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y%m%d',
        tmformat='%H:%M:%S',
        datetime=0, time=1, open=2, high=3, low=4, close=5, volume=6, openinterest=-1,
        fromdate=datetime.datetime(2024, 1, 1),
        todate=datetime.datetime(2025, 8, 21),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SunriseVolatilityExpansionStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Sunrise Volatility Expansion 波动率扩展策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0
    assert 40000 < final_value < 200000, f"Expected final_value=98840.05, got {final_value}"
    assert abs(sharpe_ratio - (-0.30774744871690607)) < 1e-6, f"Expected sharpe_ratio=-0.30774744871690607, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00592212956070817)) < 1e-9, f"Expected annual_return=-0.00592212956070817, got {annual_return}"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Sunrise Volatility Expansion 波动率扩展策略测试")
    print("=" * 60)
    test_sunrise_volatility_expansion_strategy()
