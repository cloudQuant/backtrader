#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DOGS/USDT 现货数据加载测试.

这个脚本用于测试 DOGS/USDT 现货数据是否能正确加载。
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
import backtrader as bt
from backtrader.brokers.ccxtbroker import *
from backtrader.feeds.ccxtfeed import *
from backtrader.stores.ccxtstore import *
from backtrader.ccxt import load_ccxt_config_from_env


def test_dogs_usdt_data():
    """测试 DOGS/USDT 现货数据加载"""

    # 加载环境变量
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    print("=" * 80)
    print("DOGS/USDT 现货数据加载测试")
    print("=" * 80)

    # 加载 OKX 配置
    try:
        config = load_ccxt_config_from_env('okx')
        print("[OK] API配置加载成功")
    except ValueError as e:
        print(f"[FAIL] API配置失败: {e}")
        return False

    # 创建 Cerebro
    cerebro = bt.Cerebro()

    # 创建 store
    store = CCXTStore(
        exchange='okx',
        currency='USDT',
        config=config,
        retries=5,
        debug=False
    )

    # 获取现货数据
    print("\n正在加载 DOGS/USDT 现货数据...")
    data = store.getdata(
        dataname='DOGS/USDT',
        name='DOGS/USDT',
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        fromdate=datetime.utcnow() - timedelta(minutes=200),
        todate=datetime.utcnow(),
        backfill_start=True,
        historical=False,
        ohlcv_limit=100,
        drop_newest=False,
        debug=False
    )

    cerebro.adddata(data)

    # 创建简单的数据检查策略
    class TestDataStrategy(bt.Strategy):
        def __init__(self):
            self.bar_count = 0
            self.data_start = None

        def start(self):
            self.data_start = datetime.now()
            print(f"数据开始时间: {self.data_start}")

        def next(self):
            self.bar_count += 1

            # 每10根打印一次
            if self.bar_count % 10 == 0:
                print(f"已接收 {self.bar_count} 根K线")

            # 显示前3根和每30根的详细信息
            if self.bar_count <= 3 or self.bar_count % 30 == 0:
                print(f"\n--- Bar #{self.bar_count} ---")
                print(f"时间: {self.data.datetime.datetime(0)}")
                print(f"开盘: ${self.data.open[0]:.6f}")
                print(f"最高: ${self.data.high[0]:.6f}")
                print(f"最低: ${self.data.low[0]:.6f}")
                print(f"收盘: ${self.data.close[0]:.6f}")
                print(f"成交量: {self.data.volume[0]:.0f}")

            # 收集65根后停止
            if self.bar_count >= 65:
                print(f"\n数据收集完成！共 {self.bar_count} 根K线")
                elapsed = (datetime.now() - self.data_start).total_seconds()
                print(f"耗时: {elapsed:.2f} 秒")
                self.stop()

    cerebro.addstrategy(TestDataStrategy)

    print("\n开始加载数据...")
    try:
        cerebro.run()
        print("\n[OK] 数据加载测试完成！")
        return True
    except Exception as e:
        print(f"\n[FAIL] 数据加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_dogs_usdt_data()
    print("\n" + "=" * 80)
    if success:
        print("[SUCCESS] 可以正常运行策略了！")
        print("\n运行命令:")
        print("python examples/backtrader_ccxt_okx_dogs_bollinger.py")
    else:
        print("[ERROR] 数据加载失败，请检查：")
        print("1. API 配置是否正确")
        print("2. 网络连接是否正常")
        print("3. DOGS/USDT 交易对是否可用")
    print("=" * 80)
