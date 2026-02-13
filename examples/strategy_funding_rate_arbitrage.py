#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""资金费率套利策略 - WebSocket 实时版.

策略说明：
1. 通过 WebSocket 实时获取资金费率
2. 当资金费率过高时（多头支付空头），做空合约套利
3. 当资金费率过低时（空头支付多头），做多合约套利
4. 资金费率数据已整合到每根 K 线中

数据来源：
- K线价格: WebSocket OHLCV 流
- 资金费率: WebSocket Funding Rate 流
- 标记价格: WebSocket Mark Price 流

使用方法：
    python strategy_funding_rate_arbitrage.py
"""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

import backtrader as bt
from backtrader import Order

# 导入带 WebSocket 资金费率的数据源
from backtrader.feeds.ccxtfeed_funding import CCXTFeedWithFunding, WebSocketRequiredError
from backtrader.stores.ccxtstore import CCXTStore
from backtrader.ccxt import load_ccxt_config_from_env


class FundingRateMonitor(bt.Strategy):
    """资金费率监控策略 - 实时打印费率信息."""

    params = (
        ('print_interval', 10),  # 每 N 根 K 线打印一次
    )

    def __init__(self):
        """初始化策略"""
        # 检查数据源
        if not hasattr(self.data, 'funding_rate'):
            raise ValueError("请使用 CCXTFeedWithFunding 数据源")

        self.bar_count = 0
        self.is_live = False

    def notify_data(self, data, status):
        """监听数据状态变化"""
        if status == data.LIVE and not self.is_live:
            self.is_live = True
            print('\n' + '=' * 70)
            print('[LIVE] 进入实时交易模式！')
            print('[LIVE] 资金费率通过 WebSocket 实时更新')
            print('=' * 70 + '\n')

    def next(self):
        """每根 K 线调用"""
        if not self.is_live:
            if self.bar_count % 100 == 0:
                print(f"[HIST] 正在加载历史数据... {self.bar_count} bars")
            self.bar_count += 1
            return

        self.bar_count += 1

        # 按间隔打印信息
        if self.bar_count % self.p.print_interval != 0:
            return

        # 获取数据
        price = self.data.close[0]
        funding = self.data.funding_rate[0]

        # 获取标记价格（如果可用）
        if hasattr(self.data, 'mark_price'):
            mark_price = self.data.mark_price[0]
            premium = (mark_price - price) / price * 100 if price > 0 else 0
        else:
            mark_price = price
            premium = 0

        # 获取预测费率
        if hasattr(self.data, 'predicted_funding_rate'):
            predicted = self.data.predicted_funding_rate[0]
        else:
            predicted = 0

        # 计算年化费率（每天 3 次，365 天）
        annual_rate = funding * 3 * 365 * 100

        # 判断信号
        signal = "中性"
        if funding > 0.0005:
            signal = "做空信号 (费率过高)"
        elif funding < -0.0005:
            signal = "做多信号 (费率过低)"

        # 输出
        bar_time = self.data.datetime.datetime(0)
        print(f"\n{'='*70}")
        print(f"[FUNDING] {bar_time}")
        print(f"{'='*70}")
        print(f"  价格:      ${price:.6f}")
        print(f"  标记价格:  ${mark_price:.6f} (溢价: {premium:+.4f}%)")
        print(f"  资金费率:  {funding:.8f} ({funding*100:.4f}%)")
        if predicted != 0:
            print(f"  预测费率:  {predicted:.8f} ({predicted*100:.4f}%)")
        print(f"  年化费率:  {annual_rate:.2f}%")
        print(f"  信号:      {signal}")
        print(f"{'='*70}\n")


class FundingArbitrage(bt.Strategy):
    """资金费率套利策略."""

    params = (
        ('funding_high', 0.0005),    # 0.05% 以上做空
        ('funding_low', -0.0005),    # -0.05% 以下做多
        ('exit_threshold', 0.0001),  # 回归到此值时平仓
        ('position_size', 1.0),      # 下单金额 (USDT)
    )

    def __init__(self):
        """初始化策略"""
        if not hasattr(self.data, 'funding_rate'):
            raise ValueError("请使用 CCXTFeedWithFunding 数据源")

        self.order = None
        self.entry_funding = None
        self.is_live = False

    def notify_data(self, data, status):
        """监听数据状态变化"""
        if status == data.LIVE and not self.is_live:
            self.is_live = True
            print('[LIVE] 进入实时模式！')

    def log(self, msg):
        """日志输出"""
        dt = datetime.now(timezone.utc).astimezone()
        print(f'{dt.strftime("%H:%M:%S")} {msg}')

    def next(self):
        """策略主逻辑"""
        if not self.is_live:
            return

        # 有待处理订单时等待
        if self.order:
            return

        funding = self.data.funding_rate[0]
        position = self.getposition()
        price = self.data.close[0]

        # 无持仓时的开仓逻辑
        if position.size == 0:
            # 高费率 = 多头支付空头 = 做空套利
            if funding > self.p.funding_high:
                size = int(self.p.position_size / price)
                if size < 1:
                    size = 1

                self.log(f'[SHORT ARB] 费率 {funding:.6f} > {self.p.funding_high:.6f}, 做空套利')
                self.log(f'[SHORT ARB] 价格 ${price:.6f}, 数量 {size}')
                self.order = self.sell(size=size)
                self.entry_funding = funding

            # 低费率 = 空头支付多头 = 做多套利
            elif funding < self.p.funding_low:
                size = int(self.p.position_size / price)
                if size < 1:
                    size = 1

                self.log(f'[LONG ARB] 费率 {funding:.6f} < {self.p.funding_low:.6f}, 做多套利')
                self.log(f'[LONG ARB] 价格 ${price:.6f}, 数量 {size}')
                self.order = self.buy(size=size)
                self.entry_funding = funding

        # 有持仓时的平仓逻辑
        else:
            # 费率回归时平仓
            if abs(funding) < self.p.exit_threshold:
                if position.size > 0:
                    self.log(f'[EXIT] 费率回归到 {funding:.6f}, 平多仓')
                    self.order = self.sell(size=position.size)
                else:
                    self.log(f'[EXIT] 费率回归到 {funding:.6f}, 平空仓')
                    self.order = self.buy(size=abs(position.size))

            # 费率反转时止损
            elif position.size > 0 and funding < self.p.funding_low:
                self.log(f'[STOP] 费率反转到 {funding:.6f}, 多头止损')
                self.order = self.sell(size=position.size)
            elif position.size < 0 and funding > self.p.funding_high:
                self.log(f'[STOP] 费率反转到 {funding:.6f}, 空头止损')
                self.order = self.buy(size=abs(position.size))

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f'[ORDER] 买入: ${order.executed.price:.6f} x {order.executed.size:.0f}')
            else:
                self.log(f'[ORDER] 卖出: ${order.executed.price:.6f} x {order.executed.size:.0f}')
        elif order.status in [order.Canceled, order.Rejected]:
            self.log(f'[ORDER] 订单 {order.getstatusname()}')

        self.order = None

    def notify_trade(self, trade):
        """交易完成通知"""
        if trade.isclosed:
            self.log(f'[TRADE] 利润: ${trade.pnlcomm:.4f} USDT')

    def stop(self):
        """策略停止"""
        print('\n' + '=' * 70)
        print('策略停止')
        print('=' * 70)


def run_strategy():
    """运行资金费率套利策略"""

    # 加载环境变量
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    # 选择交易所
    exchange = os.getenv('EXCHANGE', 'okx')

    try:
        # 网络配置选项（在 .env 文件中设置）:
        # OKX_USE_AWS=true  - 使用 AWS 节点
        # OKX_PROXY=http://127.0.0.1:7890  - 使用代理
        config = load_ccxt_config_from_env(exchange, enable_rate_limit=True)
    except ValueError as e:
        print(f"错误: {e}")
        print("\n请在 .env 文件中配置 API 凭证:")
        print(f"{exchange.upper()}_API_KEY=your_api_key")
        if exchange == 'okx':
            print(f"{exchange.upper()}_PASSWORD=your_password")
        print(f"{exchange.upper()}_SECRET=your_secret")
        return

    # 安装 ccxt.pro 检查
    try:
        import ccxt.pro as ccxtpro
        print(f"[OK] ccxt.pro 已安装 (版本: {ccxtpro.__version__})")
    except ImportError:
        print("[错误] 需要安装 ccxt.pro")
        print("请运行: pip install ccxtpro")
        return

    # 创建 Cerebro 引擎
    cerebro = bt.Cerebro()

    # 添加策略（选择一个）
    # 1. 监控策略 - 只打印费率信息
    cerebro.addstrategy(FundingRateMonitor, print_interval=10)

    # 2. 套利策略 - 实际交易
    # cerebro.addstrategy(
    #     FundingArbitrage,
    #     funding_high=0.0005,
    #     funding_low=-0.0005,
    #     position_size=1.0
    # )

    # 设置初始资金
    cerebro.broker.setcash(10.0)

    # 创建 Store
    store = CCXTStore(
        exchange=exchange,
        currency='USDT',
        config=config,
        retries=5,
        debug=False
    )

    # 获取 broker
    broker = store.getbroker()
    cerebro.setbroker(broker)

    # 使用带 WebSocket 资金费率的数据源
    try:
        data = CCXTFeedWithFunding(
            store=store,
            dataname='BTC/USDT:USDT',  # 永续合约
            name='BTC/USDT:USDT',
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            fromdate=datetime.now(timezone.utc) - timedelta(minutes=500),
            backfill_start=True,
            historical=False,
            # WebSocket 设置
            use_websocket=True,              # 启用 WebSocket（默认）
            include_funding=True,            # 启用资金费率
            funding_history_days=3,          # 历史数据天数
            debug=True  # 启用调试输出以便查看连接过程
        )
    except WebSocketRequiredError as e:
        print(f"[错误] {e}")
        return

    cerebro.adddata(data)

    # 打印初始信息
    print('=' * 70)
    print('资金费率套利策略 - WebSocket 实时版')
    print('=' * 70)
    print(f'交易所: {exchange}')
    print(f'交易对: BTC/USDT 永续合约')
    print(f'初始资金: {cerebro.broker.getvalue():.2f} USDT')
    print(f'数据源: WebSocket (OHLCV + Funding Rate + Mark Price)')
    print('=' * 70)
    print()

    # 运行策略
    try:
        print("启动策略...")
        print("正在加载历史数据...\n")
        results = cerebro.run()

        if results and len(results) > 0:
            print('\n' + '=' * 70)
            print('策略运行完成')
            print('=' * 70)

    except KeyboardInterrupt:
        print("\n\n策略被用户中断")
    except WebSocketRequiredError as e:
        print(f"\n[错误] WebSocket 连接失败: {e}")
        print("请确保:")
        print("1. 已安装 ccxt.pro: pip install ccxtpro")
        print("2. 网络连接正常")
        print("3. 交易所 API 密钥正确")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    run_strategy()
