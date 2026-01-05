#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
调试MACD在replay模式下的行为
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR / "tests" / "datas" / filename,
        BASE_DIR / "datas" / filename,
        BASE_DIR.parent / "tests" / "datas" / filename,
    ]
    for p in search_paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"Cannot find data file: {filename}")


class DebugMACDStrategy(bt.Strategy):
    """调试策略 - 打印MACD和Signal值"""
    params = (('fast_period', 12), ('slow_period', 26), ('signal_period', 9))

    def __init__(self):
        self.macd = bt.ind.MACD(
            period_me1=self.p.fast_period,
            period_me2=self.p.slow_period,
            period_signal=self.p.signal_period
        )
        self.crossover = bt.ind.CrossOver(self.macd.macd, self.macd.signal)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.last_data_len = 0

    def next(self):
        current_data_len = len(self.datas[0])
        self.bar_num += 1

        # 检测replay更新
        is_replay_update = (current_data_len == self.last_data_len and current_data_len > 0)
        self.last_data_len = current_data_len

        # 打印前50个bar的详细信息
        if self.bar_num <= 50 or is_replay_update:
            dt = bt.num2date(self.datas[0].datetime[0])
            macd_val = self.macd.macd[0] if len(self.macd.macd) > 0 else float('nan')
            signal_val = self.macd.signal[0] if len(self.macd.signal) > 0 else float('nan')
            cross_val = self.crossover[0] if len(self.crossover) > 0 else float('nan')

            print(f"Bar {self.bar_num:3d} | Date: {dt.isoformat()} | "
                  f"data_len={current_data_len:3d} | replay={is_replay_update} | "
                  f"MACD={macd_val:7.2f} | Signal={signal_val:7.2f} | Cross={cross_val:5.1f}")

        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
            print(f"  >>> BUY at bar {self.bar_num}, crossover={self.crossover[0]:.2f}")
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()
                print(f"  >>> SELL (close) at bar {self.bar_num}, crossover={self.crossover[0]:.2f}")

    def notify_order(self, order):
        if not order.alive():
            self.order = None

        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1


def main():
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))

    # 使用回放功能，将日线回放为周线
    cerebro.replaydata(
        data,
        timeframe=bt.TimeFrame.Weeks,
        compression=1
    )

    cerebro.addstrategy(DebugMACDStrategy, fast_period=12, slow_period=26, signal_period=9)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    print("开始运行回测...")
    print("=" * 100)
    results = cerebro.run(preload=False)
    strat = results[0]

    final_value = cerebro.broker.getvalue()

    print("=" * 100)
    print(f"bar_num: {strat.bar_num}")
    print(f"buy_count: {strat.buy_count}")
    print(f"sell_count: {strat.sell_count}")
    print(f"final_value: {final_value:.2f}")


if __name__ == "__main__":
    main()
