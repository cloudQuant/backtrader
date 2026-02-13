#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速验证策略基本逻辑的测试脚本.

使用模拟数据测试策略信号生成，无需连接交易所。
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import backtrader as bt

# Add project path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'examples'))

# Import from examples directory
from backtrader_ccxt_okx_dogs_bollinger import BollingerBandsStrategy


class TestStrategy(BollingerBandsStrategy):
    """测试策略版本，添加更多调试信息"""

    def next(self):
        """每根K线调用"""
        # 确保没有待处理订单
        if self.order:
            return

        # 确保有足够的数据（至少period+1根）
        if len(self.data) < self.p.period + 1:
            return

        # 获取当前价格和指标值
        current_price = self.data.close[0]
        upper_band = self.top[0]
        lower_band = self.bot[0]
        atr_value = self.atr[0]

        # 检查指标值是否有效
        if any(x is None for x in [current_price, upper_band, lower_band, atr_value]):
            return

        # 获取当前仓位（现货）
        position_size = self.getposition().size

        # 计算下单数量（基于USDT金额）
        size = self.p.order_size / current_price

        # 每10根K线打印一次状态
        if len(self.data) % 10 == 0:
            print(f"\n[Bar {len(self.data)}]")
            print(f"  价格: ${current_price:.6f}")
            print(f"  上轨: ${upper_band:.6f}")
            print(f"  下轨: ${lower_band:.6f}")
            print(f"  ATR: {atr_value:.6f}")
            print(f"  持仓: {position_size:.2f}")

            if position_size > 0:
                print(f"  止损价: ${self.long_stop_price:.6f}")

        # === 现货多头逻辑 ===
        # 检查止损
        if position_size > 0 and self.long_stop_price is not None:
            if current_price <= self.long_stop_price:
                print(f"\n[信号] 触发止损: 当前=${current_price:.6f}, 止损=${self.long_stop_price:.6f}")
                self.order = self.sell(size=position_size)
                self.long_stop_price = None
                self.entry_price = None
                return

        # 突破上轨 → 买入
        if position_size == 0 and current_price > upper_band:
            print(f"\n[信号] 突破上轨 → 买入: 价格=${current_price:.6f}, 上轨=${upper_band:.6f}")
            self.order = self.buy(size=size)
            self.entry_price = current_price
            self.long_stop_price = current_price - (atr_value * self.p.atr_mult)

        # 跌破下轨 → 卖出
        elif position_size > 0 and current_price < lower_band:
            print(f"\n[信号] 跌破下轨 → 卖出: 价格=${current_price:.6f}, 下轨=${lower_band:.6f}")
            self.order = self.sell(size=position_size)
            self.long_stop_price = None
            self.entry_price = None


def generate_test_data():
    """生成测试数据"""
    print("=" * 80)
    print("生成测试数据")
    print("=" * 80)

    # 生成200根1分钟K线的模拟数据
    np.random.seed(42)

    # 基础价格 $0.00004 (DOGS 当前价格)
    base_price = 0.00004

    # 生成价格数据（随机游走）
    n = 200
    returns = np.random.normal(0.001, 0.02, n)  # 1% 波动率
    prices = [base_price]

    for ret in returns:
        prices.append(prices[-1] * (1 + ret))

    # 生成 OHLCV 数据
    data = []
    from datetime import datetime, timedelta
    start_time = datetime(2025, 1, 20, 0, 0, 0)

    for i in range(n):
        close = prices[i]
        # 添加一些随机波动
        high = close * (1 + abs(np.random.normal(0, 0.01)))
        low = close * (1 - abs(np.random.normal(0, 0.01)))
        open_price = low + (high - low) * np.random.random()
        volume = np.random.randint(1000000, 10000000)

        data.append({
            'datetime': start_time + timedelta(minutes=i),
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        })

    df = pd.DataFrame(data)
    print(f"生成了 {len(df)} 根K线数据")
    print(f"价格范围: ${df['close'].min():.6f} - ${df['close'].max():.6f}")
    print(f"平均价格: ${df['close'].mean():.6f}")

    return df


class TestFeed(bt.feeds.PandasData):
    """测试数据源"""
    params = (
        ('datetime', None),
        ('open', -1),
        ('high', -1),
        ('low', -1),
        ('close', -1),
        ('volume', -1),
        ('openinterest', -1),
    )


def run_test():
    """运行测试"""
    # 生成测试数据
    df = generate_test_data()

    # 创建 Cerebro
    cerebro = bt.Cerebro()

    # 添加策略
    cerebro.addstrategy(
        TestStrategy,
        period=60,
        devfactor=2.0,
        order_size=0.4,
        atr_period=14,
        atr_mult=2.0,
    )

    # 设置初始资金
    cerebro.broker.setcash(10.0)
    cerebro.broker.setcommission(commission=0.001)  # 0.1% 手续费

    # 添加数据
    data = TestFeed(dataname=df)
    cerebro.adddata(data)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # 运行
    print("\n" + "=" * 80)
    print("运行策略测试")
    print("=" * 80)
    print(f"初始资金: {cerebro.broker.getvalue():.2f} USDT")
    print()

    try:
        results = cerebro.run()
        strat = results[0]

        # 打印结果
        print("\n" + "=" * 80)
        print("测试结果")
        print("=" * 80)

        if hasattr(strat.analyzers, 'trades'):
            trades = strat.analyzers.trades.get_analysis()
            if 'total' in trades:
                total = trades['total']['total']
                print(f"总交易次数: {total}")

            if 'won' in trades:
                won = trades['won']['total']
                print(f"盈利次数: {won}")

            if 'lost' in trades:
                lost = trades['lost']['total']
                print(f"亏损次数: {lost}")

            if 'win' in trades:
                win_rate = trades['win']
                print(f"胜率: {win_rate:.2%}")

        if hasattr(strat.analyzers, 'returns'):
            returns = strat.analyzers.returns.get_analysis()
            if 'rtot' in returns:
                print(f"总收益率: {returns['rtot']:.2%}")

        final_value = cerebro.broker.getvalue()
        print(f"\n最终资金: {final_value:.2f} USDT")
        print(f"总收益: {final_value - 10.0:.2f} USDT")
        print(f"收益率: {(final_value - 10.0) / 10.0 * 100:.2f}%")

        print("\n" + "=" * 80)
        print("[OK] 策略测试完成！")
        print("=" * 80)

    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    run_test()
