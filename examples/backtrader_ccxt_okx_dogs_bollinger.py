#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OKX DOGS/USDT 现货布林带突破策略.

策略说明：
1. 使用60周期、2倍标准差的布林带
2. 交易对：DOGS/USDT 现货
3. 每次下单金额：0.4 USDT
4. 1分钟K线

交易逻辑（现货做多交易）：
- 价格突破上轨 → 开多仓（买入）
- 价格跌破下轨 → 平多仓（卖出）
- 使用ATR进行动态止损

注意：现货交易只能做多，不能做空。
"""

import os
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

import backtrader as bt
from backtrader import Order
from backtrader.brokers.ccxtbroker import *
from backtrader.feeds.ccxtfeed import *
from backtrader.stores.ccxtstore import *
from backtrader.ccxt import load_ccxt_config_from_env


class BollingerBandsStrategy(bt.Strategy):
    """布林带突破策略（现货做多）。

    参数:
        period: 布林带周期，默认60
        devfactor: 标准差倍数，默认2
        order_size: 每次下单金额（USDT），默认0.4
        atr_period: ATR周期，默认14
        atr_mult: ATR止损倍数，默认2
        position_size_pct: 仓位比例，默认1.0（满仓）
        log_bars: 是否输出每个bar的详细信息，默认True
    """

    params = (
        ('period', 60),           # 布林带周期
        ('devfactor', 2.0),       # 标准差倍数
        ('order_size', 0.4),      # 每次下单金额（USDT）
        ('atr_period', 14),       # ATR周期
        ('atr_mult', 2.0),        # ATR止损倍数
        ('position_size_pct', 1.0),  # 仓位比例
        ('log_bars', True),       # 是否输出bar信息
    )

    def __init__(self):
        """初始化策略指标和状态"""
        # 布林带指标
        self.bollinger = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )

        # ATR指标（用于动态止损）
        self.atr = bt.indicators.ATR(
            self.data,
            period=self.p.atr_period
        )

        # 移动平均线（中轨）
        self.mid = self.bollinger.mid

        # 上下轨
        self.top = self.bollinger.top
        self.bot = self.bollinger.bot

        # 交易状态（现货只有做多）
        self.order = None
        self.stop_price = None  # 止损价
        self.entry_price = None      # 入场价格

        # 交易统计
        self.trade_count = 0
        self.last_bar_logged = 0

        # 实时交易标志：历史数据用于初始化指标，不触发交易
        self.is_live_mode = False  # 是否进入实时模式
        self.live_bar_count = 0    # 实时K线计数
        self.historical_bar_count = 0  # 历史K线计数

    def log(self, msg, with_date=True):
        """日志输出"""
        if with_date:
            timestamp = time.time()
            dt = datetime.fromtimestamp(timestamp)
            msg = f'{dt.strftime("%Y-%m-%d %H:%M:%S")} {msg}'
        print(msg)

    def notify_data(self, data, status, *args, **kwargs):
        """监听数据状态变化

        当数据源状态变化时，backtrader会调用此方法
        - DELAYED: 正在回填历史数据
        - LIVE: 已进入实时模式
        - DISCONNECTED: 数据断开
        """
        if status == data.DELAYED and not self.is_live_mode:
            self.log('[DATA] 正在加载历史数据...', with_date=True)

        elif status == data.LIVE:
            if not self.is_live_mode:
                self.is_live_mode = True
                self.log('=' * 80, with_date=True)
                self.log('[LIVE] 历史数据加载完成，进入实时交易模式！', with_date=True)
                self.log(f'[LIVE] 当前持仓: {self.getposition().size}', with_date=True)
                self.log('=' * 80, with_date=True)
            else:
                # 确保保持实时模式
                self.is_live_mode = True

        elif status == data.DISCONNECTED:
            self.log('[DATA] 数据源已断开 - 策略可能停止', with_date=True)
            self.log(f'[DATA] 断开时的持仓: {self.getposition().size}', with_date=True)

    def log_historical_bar(self, bar_num, bar_time, price, upper, lower, middle):
        """输出历史数据加载进度"""
        mode_str = "HIST" if not self.is_live_mode else "LIVE"
        print(f"[{mode_str}] #{bar_num:3d} | {bar_time} | Price: ${price:.6f} | "
              f"Upper: ${upper:.6f} | Mid: ${middle:.6f} | Lower: ${lower:.6f}")

    def log_bar_info(self):
        """输出当前bar的详细信息"""
        if not self.p.log_bars:
            return

        # 避免重复输出同一根bar
        if len(self.data) == self.last_bar_logged:
            return

        self.last_bar_logged = len(self.data)

        # 获取bar信息
        bar_time = self.data.datetime.datetime(0)
        current_price = self.data.close[0]
        upper_band = self.top[0]
        lower_band = self.bot[0]
        middle_band = self.mid[0]
        atr_value = self.atr[0]

        # 获取持仓信息
        position_size = self.getposition().size
        position_price = self.getposition().price if position_size != 0 else 0

        # 计算带宽（上下轨距离/中轨）
        bandwidth = (upper_band - lower_band) / middle_band * 100 if middle_band > 0 else 0

        # 计算价格在布林带中的位置
        if upper_band != lower_band:
            bb_position = (current_price - lower_band) / (upper_band - lower_band) * 100
        else:
            bb_position = 50

        print(f"\n{'='*100}")
        mode_str = "LIVE" if self.is_live_mode else "HIST"
        print(f"Bar #{len(self.data)} [{mode_str}] | Time: {bar_time}")
        print(f"{'='*100}")
        print(f"Price Information:")
        print(f"  Open:   ${self.data.open[0]:.6f}")
        print(f"  High:   ${self.data.high[0]:.6f}")
        print(f"  Low:    ${self.data.low[0]:.6f}")
        print(f"  Close:  ${current_price:.6f}")
        print(f"  Volume: {self.data.volume[0]:.0f}")

        print(f"\nBollinger Bands (Period={self.p.period}, Std={self.p.devfactor}):")
        print(f"  Upper Band: ${upper_band:.6f}")
        print(f"  Middle Band: ${middle_band:.6f}")
        print(f"  Lower Band: ${lower_band:.6f}")
        print(f"  Bandwidth: {bandwidth:.2f}%")
        print(f"  BB Position: {bb_position:.1f}% ({'Oversold' if bb_position < 20 else 'Overbought' if bb_position > 80 else 'Neutral'})")

        print(f"\nATR (Period={self.p.atr_period}):")
        print(f"  ATR Value: {atr_value:.6f}")
        print(f"  ATR % of Price: {atr_value/current_price*100:.2f}%")

        print(f"\nPosition Information:")
        print(f"  Position Size: {position_size:.2f}")
        if position_size != 0:
            print(f"  Entry Price: ${position_price:.6f}")
            unrealized_pnl = (current_price - position_price) * position_size
            print(f"  Unrealized P&L: ${unrealized_pnl:.4f} USDT")
            if self.stop_price:
                stop_distance = (current_price - self.stop_price) / current_price * 100
                print(f"  Stop Loss: ${self.stop_price:.6f} (Distance: {stop_distance:.2f}%)")
        else:
            print(f"  Entry Price: N/A (No position)")
            print(f"  Stop Price: N/A (No position)")

        # 信号提示（现货只有做多）
        signals = []
        if position_size == 0:
            if current_price > upper_band:
                signals.append("BUY SIGNAL (Break above upper band)")
        elif position_size > 0:
            if current_price > upper_band:
                signals.append("HOLD LONG (Above upper band)")
            elif current_price < lower_band:
                signals.append("CLOSE LONG SIGNAL (Below lower band)")
            elif self.stop_price and current_price <= self.stop_price:
                signals.append("STOP LOSS SIGNAL")

        if signals:
            print(f"\nTrading Signals:")
            for signal in signals:
                print(f"  >>> {signal}")

        print(f"{'='*100}\n")

    def calculate_order_size(self, price):
        """计算下单数量，确保取整

        合约交易通常有最小数量限制，需要取整
        """
        # 计算理论数量
        theoretical_size = self.p.order_size / price

        # 获取市场信息中的最小数量限制
        min_amount = 1.0  # 默认最小1个单位

        # 向上取整到最小单位的整数倍
        size = int(theoretical_size)
        if size < min_amount:
            size = int(min_amount)

        # 确保至少为1
        if size < 1:
            size = 1

        return size

    def next(self):
        """每根K线调用"""
        try:
            self._next_impl()
        except Exception as e:
            self.log(f'[ERROR] next() 发生异常: {e}', with_date=True)
            self.log(f'[ERROR] 异常详情: {traceback.format_exc()}', with_date=True)

    def _next_impl(self):
        """next() 的实际实现"""
        # 统计K线数量
        if self.is_live_mode:
            self.live_bar_count += 1
        else:
            self.historical_bar_count += 1

        # 历史数据：每10根输出一次简化信息
        if not self.is_live_mode and self.historical_bar_count % 10 == 0:
            bar_time = self.data.datetime.datetime(0)
            current_price = self.data.close[0]
            upper_band = self.top[0]
            lower_band = self.bot[0]
            middle_band = self.mid[0]
            self.log_historical_bar(self.historical_bar_count, bar_time, current_price,
                                    upper_band, lower_band, middle_band)

        # 实时数据：每60根或前3根输出进度
        if self.is_live_mode:
            if self.live_bar_count % 60 == 0 or self.live_bar_count <= 3:
                self.log(f'[LIVE] 实时K线 #{self.live_bar_count}, 总K线数: {len(self.data)}', with_date=True)

        # 输出详细bar信息（仅在实时模式或前3根/最后3根历史数据时）
        if self.is_live_mode or len(self.data) <= 3 or (not self.is_live_mode and self.historical_bar_count > self.p.period - 3):
            self.log_bar_info()

        # 确保没有待处理订单
        if self.order:
            return

        # 确保有足够的数据（至少period+1根）
        if len(self.data) < self.p.period + 1:
            return

        # === 历史数据不触发交易信号 ===
        # 只有在收到 LIVE 通知后，才允许触发交易信号
        if not self.is_live_mode:
            return

        # 获取当前价格和指标值
        current_price = self.data.close[0]
        upper_band = self.top[0]
        lower_band = self.bot[0]
        middle_band = self.mid[0]
        atr_value = self.atr[0]

        # 检查指标值是否有效
        if any(x is None for x in [current_price, upper_band, lower_band, middle_band, atr_value]):
            return

        # 获取当前仓位
        position_size = self.getposition().size

        # 计算下单数量（取整）
        size = self.calculate_order_size(current_price)

        # === 现货做多交易逻辑 ===

        # 1. 检查止损（优先执行）
        if position_size > 0 and self.stop_price is not None:
            if current_price <= self.stop_price:
                self.log(f'[STOP LOSS] 止损触发: 当前=${current_price:.6f}, 止损=${self.stop_price:.6f}')
                self.order = self.sell(size=position_size)
                self.stop_price = None
                self.entry_price = None
                self.trade_count += 1
                return

        # 2. 无仓位时的开仓逻辑
        if position_size == 0:
            # 突破上轨 → 开多仓
            if current_price > upper_band:
                self.log(f'[LONG ENTRY] 突破上轨开多: 价格=${current_price:.6f}, 上轨=${upper_band:.6f}, 数量={size}')
                self.order = self.buy(size=size)
                self.entry_price = current_price
                self.stop_price = current_price - (atr_value * self.p.atr_mult)
                self.log(f'[ORDER] 开多订单已提交，等待交易所确认...', with_date=True)
                return

        # 3. 持有多仓时的逻辑
        elif position_size > 0:
            # 跌破下轨 → 平多仓
            if current_price < lower_band:
                self.log(f'[LONG EXIT] 跌破下轨平多: 价格=${current_price:.6f}, 下轨=${lower_band:.6f}, 数量={position_size}')
                self.order = self.sell(size=position_size)
                self.stop_price = None
                self.entry_price = None
                self.trade_count += 1
                return

            # 持仓日志（每30根bar输出一次）
            if len(self.data) % 30 == 0:
                pnl = (current_price - self.entry_price) * position_size
                self.log(f'[LONG HOLD] 持有多仓: 入场=${self.entry_price:.6f}, 当前=${current_price:.6f}, 浮盈=${pnl:.4f}')

    def notify_order(self, order):
        """订单状态通知"""
        try:
            self._notify_order_impl(order)
        except Exception as e:
            self.log(f'[ERROR] notify_order() 发生异常: {e}', with_date=True)
            self.log(f'[ERROR] 异常详情: {traceback.format_exc()}', with_date=True)
            # 重置订单，防止阻塞后续交易
            self.order = None

    def _notify_order_impl(self, order):
        """notify_order() 的实际实现"""
        # 订单状态映射
        status_names = {
            order.Created: 'Created',
            order.Submitted: 'Submitted',
            order.Accepted: 'Accepted',
            order.Partial: 'Partial',
            order.Completed: 'Completed',
            order.Canceled: 'Canceled',
            order.Rejected: 'Rejected',
            order.Margin: 'Margin',
            order.Expired: 'Expired',
        }

        status_name = status_names.get(order.status, f'Unknown({order.status})')

        if order.status in [order.Submitted, order.Accepted, order.Partial]:
            self.log(f'[ORDER] 订单状态: {status_name} - 等待成交', with_date=True)
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'[ORDER EXECUTED] 买入: 价格=${order.executed.price:.6f}, '
                        f'数量={order.executed.size:.0f}, '
                        f'金额=${order.executed.value:.2f} USDT', with_date=True)
            else:
                self.log(f'[ORDER EXECUTED] 卖出: 价格=${order.executed.price:.6f}, '
                        f'数量={order.executed.size:.0f}, '
                        f'金额=${order.executed.value:.2f} USDT', with_date=True)
            # 显示当前资金
            self.log(f'[BALANCE] 当前资金: ${self.broker.getvalue():.2f} USDT', with_date=True)

        elif order.status in [order.Canceled]:
            self.log('[ORDER] 订单取消', with_date=True)
        elif order.status in [order.Rejected]:
            self.log(f'[ORDER] 订单拒绝: {order}', with_date=True)
            self.log(f'[ORDER] 拒绝详情 - Status: {status_name}, Size: {order.size}, Price: {order.price}', with_date=True)
        elif order.status in [order.Margin]:
            self.log('[ORDER] 订单保证金不足', with_date=True)

        # 重置订单
        self.order = None

    def notify_trade(self, trade):
        """交易完成通知"""
        try:
            if trade.isclosed:
                self.log(f'[TRADE CLOSED] 交易关闭: 毛利润=${trade.pnl:.4f} USDT, '
                        f'净利润=${trade.pnlcomm:.4f} USDT', with_date=True)
            elif trade.justopened:
                self.log(f'[TRADE OPENED] 新交易开仓: {trade.gettradename()}', with_date=True)
        except Exception as e:
            self.log(f'[ERROR] notify_trade() 发生异常: {e}', with_date=True)

    def stop(self):
        """策略停止时调用"""
        self.log('=' * 80, with_date=True)
        self.log('策略停止', with_date=True)
        self.log(f'最终资金: {self.broker.getvalue():.2f} USDT', with_date=True)
        self.log(f'总收益: {self.broker.getvalue() - self.broker.startingcash:.2f} USDT', with_date=True)
        self.log(f'历史K线数: {self.historical_bar_count}', with_date=True)
        self.log(f'实时K线数: {self.live_bar_count}', with_date=True)
        self.log(f'总交易次数: {self.trade_count}', with_date=True)
        self.log('=' * 80, with_date=True)


def run_strategy():
    """运行策略"""

    # 加载环境变量
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)

    # 加载 OKX 配置
    try:
        config = load_ccxt_config_from_env('okx', enable_rate_limit=True)
    except ValueError as e:
        print(f"错误: {e}")
        print("\n请在 .env 文件中配置 OKX API 凭证：")
        print("OKX_API_KEY=your_api_key")
        print("OKX_SECRET=your_secret")
        print("OKX_PASSWORD=your_password")
        return

    # 创建 Cerebro 引擎
    cerebro = bt.Cerebro()

    # 添加策略
    cerebro.addstrategy(
        BollingerBandsStrategy,
        period=60,              # 60周期布林带
        devfactor=2.0,          # 2倍标准差
        order_size=0.4,         # 每次0.4 USDT
        atr_period=14,          # ATR周期
        atr_mult=2.0,           # 止损倍数
    )

    # 设置初始资金（小资金测试）
    cerebro.broker.setcash(10.0)  # 10 USDT

    # 创建 OKX Store（现货交易）
    store = CCXTStore(
        exchange='okx',
        currency='USDT',
        config=config,
        retries=5,
        debug=False
    )

    # 获取 broker
    broker = store.getbroker()
    cerebro.setbroker(broker)

    # 获取现货数据（DOGS/USDT）
    data = store.getdata(
        dataname='DOGS/USDT',           # 现货交易对
        name='DOGS/USDT',
        timeframe=bt.TimeFrame.Minutes,  # 1分钟
        compression=1,
        fromdate=datetime.utcnow() - timedelta(minutes=200),  # 历史数据起始时间
        backfill_start=True,                 # 启用历史数据回填
        historical=False,                    # False=历史数据后继续实时模式
        ohlcv_limit=100,
        drop_newest=False,
        debug=False
    )

    cerebro.adddata(data)

    # 打印初始信息
    print('=' * 80)
    print('OKX DOGS/USDT 现货布林带突破策略')
    print('=' * 80)
    print(f'初始资金: {cerebro.broker.getvalue():.2f} USDT')
    print(f'每次下单: 0.4 USDT')
    print(f'交易对: DOGS/USDT 现货')
    print(f'时间周期: 1分钟')
    print(f'布林带参数: 60周期, 2倍标准差')
    print(f'ATR止损: 14周期, 2倍ATR')
    print(f'交易模式: 现货做多（无做空）')
    print('=' * 80)
    print()

    # 运行策略
    try:
        print("\n开始运行策略...")
        print(f"正在加载历史数据（需要至少 {60+10} 根K线初始化指标）...")
        print("历史数据加载进度会每10根K线显示一次")
        print("历史数据加载完成后，将开始监控实时交易信号")
        print("按 Ctrl+C 可随时停止策略\n")

        results = cerebro.run()

        # 策略运行完成
        if results and len(results) > 0:
            strat = results[0]
            print('\n' + '=' * 80)
            print('策略运行总结')
            print('=' * 80)
            print(f'历史K线数: {strat.historical_bar_count}')
            print(f'实时K线数: {strat.live_bar_count}')
            print(f'总交易次数: {strat.trade_count}')
            print(f'最终资金: {cerebro.broker.getvalue():.2f} USDT')
            print('=' * 80)

    except KeyboardInterrupt:
        print("\n\n策略被用户中断")
    except Exception as e:
        print(f"\n错误: {e}")
        traceback.print_exc()


if __name__ == '__main__':
    run_strategy()
