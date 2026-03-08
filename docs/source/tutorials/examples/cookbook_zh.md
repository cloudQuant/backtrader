---
title: 常用模式手册
description: 实用交易模式与实现

---
# 常用模式手册

本手册提供了 Backtrader 中常见交易模式的实用实现。每个模式都包含完整的可运行示例和详细说明。

## 目录

1. [止损与止盈](#止损与止盈)
2. [动态仓位管理](#动态仓位管理)
3. [多指标组合](#多指标组合)
4. [基于时间的交易过滤](#基于时间的交易过滤)
5. [事件驱动模式](#事件驱动模式)
6. [金字塔加仓](#金字塔加仓)
7. [追踪止损实现](#追踪止损实现)
8. [ bracket 订单](#bracket-订单)

---
## 止损与止盈

### 固定百分比止损

```python
import backtrader as bt

class FixedStopLoss(bt.Strategy):
    """
    带固定百分比止损的策略。

    参数:
        stop_loss_pct: 止损百分比 (默认: 2%)
    """

    params = (
        ('stop_loss_pct', 0.02),
    )

    def __init__(self):

# 跟踪入场价格用于计算止损
        self.entry_price = None
        self.order = None

    def next(self):
        if self.order:
            return  # 等待待处理订单

        if not self.position:

# 入场逻辑 - 当价格突破均线上方时买入
            if len(self.data) >= 20:
                if self.data.close[0] > self.data.close[-1]:
                    self.order = self.buy()
                    self.entry_price = self.data.close[0]
        else:

# 检查止损
            current_price = self.data.close[0]
            stop_price = self.entry_price *(1 - self.p.stop_loss_pct)

            if current_price <= stop_price:
                self.order = self.close()  # 触发止损

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
            if not self.position:
                self.entry_price = None

```

### 基于 ATR 的动态止损

```python
class ATRStopLoss(bt.Strategy):
    """
    使用 ATR（平均真实波幅）设置动态止损。

    使用平均真实波幅的倍数作为止损距离，
    使止损能够根据市场波动性自动调整。
    """

    params = (
        ('atr_period', 14),
        ('atr_multiplier', 2.0),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.entry_price = None
        self.stop_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# 简单入场: 价格上涨时买入
            if len(self.data) > self.p.atr_period:
                if self.data.close[0] > self.data.close[-1]:
                    self.order = self.buy()
                    self.entry_price = self.data.close[0]

# 设置初始止损
                    self.stop_price = self.entry_price - (self.atr[0]*self.p.atr_multiplier)
        else:

# 检查止损是否触发
            if self.data.close[0] <= self.stop_price:
                self.order = self.close()
            else:

# 移动止损: 价格有利变动时更新止损价
                new_stop = self.data.close[0] - (self.atr[0]*self.p.atr_multiplier)
                if new_stop > self.stop_price:
                    self.stop_price = new_stop

```

### 盈亏比止盈

```python
class RiskRewardStrategy(bt.Strategy):
    """
    使用固定盈亏比的止盈策略。

    每承担一单位风险，追求多单位的收益。
    """

    params = (
        ('stop_loss_pct', 0.02),
        ('risk_reward_ratio', 2.0),  # 2:1 收益风险比
    )

    def __init__(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# 入场条件
            if len(self.data) >= 20:
                sma = bt.indicators.SMA(self.data.close, period=20)
                if self.data.close[0] > sma[0] and self.data.close[-1] <= sma[-1]:
                    self.order = self.buy()
                    self.entry_price = self.data.close[0]

# 计算止损和止盈位
                    self.stop_price = self.entry_price*(1 - self.p.stop_loss_pct)
                    risk = self.entry_price - self.stop_price
                    self.target_price = self.entry_price + (risk*self.p.risk_reward_ratio)
        else:
            current_price = self.data.close[0]

# 检查止损
            if current_price <= self.stop_price:
                self.order = self.close()

# 检查止盈
            elif current_price >= self.target_price:
                self.order = self.close()

```

---
## 动态仓位管理

### 权益百分比仓位

```python
class PercentEquitySizer(bt.Sizer):
    """
    按固定权益百分比分配仓位。

    参数:
        percents: 每笔交易使用的权益百分比 (默认: 20)
    """

    params = (('percents', 20),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if isbuy:

# 基于权益百分比计算仓位
            position_value = self.broker.getvalue()*(self.p.percents / 100)
            size = position_value / data.close[0]
            return int(size)
        return self.broker.getposition(data).size

# 在策略中使用

class PercentEquityStrategy(bt.Strategy):
    params = (('trade_size', 20),)  # 每笔交易 20% 权益

    def __init__(self):
        self.setsizer(PercentEquitySizer(percents=self.p.trade_size))

```

### 波动率调整仓位

```python
class VolatilitySizer(bt.Sizer):
    """
    根据波动率调整仓位大小。

    使用 ATR 确定仓位 - 高波动时小仓位，低波动时大仓位。
    """

    params = (
        ('atr_period', 14),
        ('atr_multiplier', 2.0),
        ('risk_pct', 0.02),  # 每笔交易 2% 权益风险
    )

    def _getsizing(self, comminfo, cash, data, isbuy):
        if not isbuy:
            return self.broker.getposition(data).size

# 计算 ATR
        if len(data) < self.p.atr_period:
            return 0

        atr = bt.indicators.ATR(data, period=self.p.atr_period)
        current_atr = atr[0] if len(atr) > 0 else data.close[0]*0.02

# 基于风险计算仓位
        risk_amount = self.broker.getvalue()*self.p.risk_pct
        stop_distance = current_atr*self.p.atr_multiplier

        if stop_distance > 0:
            size = risk_amount / stop_distance
            return int(size)

        return 0

```

### 凯利公式仓位

```python
class KellySizer(bt.Sizer):
    """
    使用凯利公式进行仓位管理。

    凯利 % = (胜率%*盈亏比 - 败率%) / 盈亏比

    参数:
        win_rate: 历史胜率 (0-1)
        avg_win: 平均盈利金额
        avg_loss: 平均亏损金额 (正数)
        max_position_pct: 最大仓位占权益百分比
    """

    params = (
        ('win_rate', 0.55),
        ('avg_win', 100),
        ('avg_loss', 80),
        ('max_position_pct', 25),
    )

    def _getsizing(self, comminfo, cash, data, isbuy):
        if not isbuy:
            return self.broker.getposition(data).size

# 计算凯利百分比
        win_loss_ratio = self.p.avg_win / self.p.avg_loss
        kelly_pct = (self.p.win_rate*win_loss_ratio - (1 - self.p.win_rate)) / win_loss_ratio

# 使用分数凯利 (半凯利以提高安全性)
        kelly_pct = max(0, min(kelly_pct*0.5, self.p.max_position_pct / 100))

# 计算仓位
        position_value = self.broker.getvalue()*kelly_pct
        size = position_value / data.close[0]

        return int(size)

```

---
## 多指标组合

### 趋势 + 动量 + 波动率

```python
class TripleConfirmationStrategy(bt.Strategy):
    """
    结合趋势、动量和波动率指标。

    入场条件 (需全部满足):

    1. 趋势: 价格位于 200 周期均线上方
    2. 动量: RSI 低于 30 (超卖)
    3. 波动率: ATR 高于平均值 (波动率扩大)

    """

    params = (
        ('trend_period', 200),
        ('rsi_period', 14),
        ('rsi_threshold', 30),
        ('atr_period', 14),
    )

    def __init__(self):

# 趋势指标
        self.sma_trend = bt.indicators.SMA(self.data.close, period=self.p.trend_period)

# 动量指标
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

# 波动率指标
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.atr_sma = bt.indicators.SMA(self.atr, period=self.p.atr_period)

    def next(self):
        if len(self.data) < self.p.trend_period:
            return

        if not self.position:

# 检查三个条件
            trend_ok = self.data.close[0] > self.sma_trend[0]
            momentum_ok = self.rsi[0] < self.p.rsi_threshold
            volatility_ok = self.atr[0] > self.atr_sma[0]

            if trend_ok and momentum_ok and volatility_ok:
                self.buy()
        else:

# 当 RSI 超买时退出
            if self.rsi[0] > 70:
                self.sell()

```

### MACD + 随机指标确认

```python
class MACDStochasticStrategy(bt.Strategy):
    """
    结合 MACD 和随机指标进行入场确认。

    买入时:

    - MACD 线上穿信号线
    - 随机指标 %K 从 20 下方上穿 %D

    卖出时:

    - MACD 线下穿信号线
    - 随机指标 %K 从 80 上方下穿 %D

    """

    params = (
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
        ('stoch_period', 14),
        ('stoch_d_period', 3),
    )

    def __init__(self):

# MACD 指标
        self.macd = bt.indicators.MACD(self.data.close,
                                       period_me1=self.p.macd_fast,
                                       period_me2=self.p.macd_slow,
                                       period_signal=self.p.macd_signal)
        self.macd_cross = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

# 随机指标
        self.stoch = bt.indicators.Stochastic(self.data,
                                              period=self.p.stoch_period,
                                              period_dfast=self.p.stoch_d_period)
        self.stoch_cross = bt.indicators.CrossOver(self.stoch.percK,
                                                   self.stoch.percD)

    def next(self):
        if not self.position:

# 买入信号: MACD 金叉 + 随机指标超卖区金叉
            if (self.macd_cross[0] > 0 and
                self.stoch_cross[0] > 0 and
                self.stoch.percK[-1] < 20):
                self.buy()
        else:

# 卖出信号: MACD 死叉 + 随机指标超买区死叉
            if (self.macd_cross[0] < 0 and
                self.stoch_cross[0] < 0 and
                self.stoch.percK[-1] > 80):
                self.sell()

```

### 布林带 + RSI 均值回归

```python
class BBRSIReversalStrategy(bt.Strategy):
    """
    结合布林带和 RSI 的均值回归策略。

    买入时:

    - 价格触及布林带下轨
    - RSI 低于 30

    卖出时:

    - 价格触及布林带上轨
    - RSI 高于 70

    """

    params = (
        ('bb_period', 20),
        ('bb_dev', 2.0),
        ('rsi_period', 14),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close,
                                               period=self.p.bb_period,
                                               devfactor=self.p.bb_dev)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

    def next(self):
        if not self.position:

# 下轨买入且 RSI 确认
            if (self.data.close[0] <= self.bb.lines.bot[0] and
                self.rsi[0] < 30):
                self.buy()
        else:

# 上轨卖出且 RSI 确认
            if (self.data.close[0] >= self.bb.lines.top[0] and
                self.rsi[0] > 70):
                self.sell()

```

---
## 基于时间的交易过滤

### 交易时段过滤

```python
import datetime

class SessionFilterStrategy(bt.Strategy):
    """
    仅在一天中的特定时段交易。

    参数:
        start_hour: 交易开始时间 (24 小时制)
        end_hour: 交易结束时间 (24 小时制)
        exclude_first_bars: 跳过时段开始后的前 N 根 K 线
    """

    params = (
        ('start_hour', 10),
        ('end_hour', 15),
        ('exclude_first_bars', 5),
    )

    def __init__(self):
        self.bars_in_session = 0
        self.was_in_session = False

    def next(self):
        current_time = self.data.datetime.time(0)
        in_session = (self.p.start_hour <= current_time.hour < self.p.end_hour)

# 进入新时段时重置计数器
        if in_session and not self.was_in_session:
            self.bars_in_session = 0
        elif in_session:
            self.bars_in_session += 1

        self.was_in_session = in_session

# 跳过时段外或预热期
        if not in_session or self.bars_in_session < self.p.exclude_first_bars:
            return

# 交易逻辑
        if not self.position:
            self.buy()

```

### 星期几过滤

```python
class DayOfWeekStrategy(bt.Strategy):
    """
    仅在指定的星期几交易。

    参数:
        trade_days: 要交易的星期元组 (0=周一, 6=周日)
    """

    params = (
        ('trade_days', (0, 1, 2, 3, 4)),  # 周一到周五
    )

    def next(self):
        current_weekday = self.data.datetime.date(0).weekday()

# 仅在指定日期交易
        if current_weekday not in self.p.trade_days:
            return

# 交易逻辑
        if not self.position and len(self.data) >= 20:
            sma = bt.indicators.SMA(self.data.close, period=20)
            if self.data.close[0] > sma[0]:
                self.buy()

```

### 月份/季节性过滤

```python
class SeasonalStrategy(bt.Strategy):
    """
    实现季节性交易模式。

    示例: "五月卖出" - 避开夏季月份交易。
    """

    params = (
        ('avoid_months', (5, 6, 7, 8)),  # 五月到八月
    )

    def next(self):
        current_month = self.data.datetime.date(0).month

# 指定月份不交易
        if current_month in self.p.avoid_months:

# 平掉现有仓位
            if self.position:
                self.close()
            return

# 活跃月份的交易逻辑
        if not self.position and len(self.data) >= 20:
            if self.data.close[0] > self.data.close[-1]:
                self.buy()

```

### 收盘前平仓

```python
class EndOfDayExit(bt.Strategy):
    """
    在市场收盘前平掉所有仓位。

    适用于不想持有隔夜仓位的日内交易策略。
    """

    params = (
        ('exit_hour', 15),
        ('exit_minute', 30),
    )

    def __init__(self):
        self.exit_triggered = False

    def next(self):
        current_time = self.data.datetime.time(0)
        exit_time = datetime.time(self.p.exit_hour, self.p.exit_minute)

# 在指定时间平仓
        if current_time >= exit_time:
            if self.position and not self.exit_triggered:
                self.close()
                self.exit_triggered = True
        else:
            self.exit_triggered = False

# 收盘前的交易逻辑
        if current_time < exit_time and not self.position:
            if len(self.data) >= 20:
                if self.data.close[0] > self.data.close[-1]:
                    self.buy()

```

---
## 事件驱动模式

### 订单状态通知

```python
class OrderNotificationStrategy(bt.Strategy):
    """
    全面的订单跟踪和通知。

    处理所有订单状态: 已提交、已接受、部分成交、已成交、已取消、已拒绝。
    """

    def __init__(self):
        self.order = None
        self.pending_orders = {}  # 按引用跟踪订单

    def next(self):

# 仅在没有待处理订单时下单
        if self.order:
            return

        if not self.position:
            self.order = self.buy(size=100)

    def notify_order(self, order):
        """订单状态变化时调用。"""

# 订单仍在待处理
        if order.status in [order.Submitted, order.Accepted]:
            return

# 订单已成交
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f'买入成交: 价格 {order.executed.price:.2f}, '
                        f'成本 {order.executed.value:.2f}, '
                        f'手续费 {order.executed.comm:.2f}')
            else:
                self.log(f'卖出成交: 价格 {order.executed.price:.2f}, '
                        f'成本 {order.executed.value:.2f}, '
                        f'手续费 {order.executed.comm:.2f}')

# 订单已取消
        elif order.status == order.Cancelled:
            self.log(f'订单已取消: {order.getstatusname()}')

# 订单被拒绝
        elif order.status == order.Rejected:
            self.log(f'订单被拒绝: {order.getstatusname()}')

# 保证金不足
        elif order.status == order.Margin:
            self.log(f'保证金不足: {order.getstatusname()}')

# 重置订单引用
        self.order = None

    def log(self, txt):
        """日志辅助函数。"""
        dt = self.data.datetime.date(0)
        print(f'{dt.isoformat()}: {txt}')

```

### 交易通知

```python
class TradeNotificationStrategy(bt.Strategy):
    """
    跟踪已完成的交易及盈亏计算。
    """

    params = (
        ('print_log', True),
    )

    def notify_trade(self, trade):
        """
        交易完成 (平仓) 时调用。

        提供全面的交易统计数据。
        """
        if not trade.isclosed:
            return

# 计算交易指标
        pnl_net = trade.pnlnet  # 净利润 (扣除手续费后)
        pnl_comm = trade.commission  # 支付的手续费
        pnl_gross = trade.pnl  # 毛利润 (扣除手续费前)

        log_txt = (
            f'交易平仓 | '

            f'净盈亏: {pnl_net:.2f} | '

            f'毛盈亏: {pnl_gross:.2f} | '

            f'手续费: {pnl_comm:.2f}'
        )

        if self.p.print_log:
            self.log(log_txt)

    def log(self, txt):
        dt = self.data.datetime.date(0)
        print(f'{dt.isoformat()}: {txt}')

```

### 数据通知 (实盘交易)

```python
class DataNotificationStrategy(bt.Strategy):
    """
    处理实盘交易的数据源事件。

    用于检测连接问题、数据延迟等。
    """

    def __init__(self):
        self.last_data_time = None
        self.data_gap_detected = False

    def notify_data(self, data, status,*args, **kwargs):
        """数据源状态变化时调用。"""

# 数据是实时的
        if status == data.LIVE:
            self.log('数据源实时连接')

# 数据延迟
        elif status == data.DELAYED:
            self.log('数据源延迟')

# 数据连接断开
        elif status == data.DISCONNECTED:
            self.log('数据源断开 - 请检查连接')
            self.data_gap_detected = True

# 数据重新连接
        elif status == data.CONNECTED:
            if self.data_gap_detected:
                self.log('数据源重新连接')
                self.data_gap_detected = False

# 新数据到达
        if hasattr(data, 'datetime') and len(data) > 0:
            self.last_data_time = data.datetime.datetime(0)

    def log(self, txt):
        print(f'{self.data.datetime.datetime(0)}: {txt}')

```

### 资金价值通知

```python
class CashNotificationStrategy(bt.Strategy):
    """
    监控账户权益和现金变化。

    用于风险管理和绩效跟踪。
    """

    def __init__(self):
        self.starting_cash = self.broker.getcash()
        self.peak_equity = self.starting_cash
        self.drawdown = 0.0
        self.max_drawdown = 0.0

    def next(self):
        current_equity = self.broker.getvalue()

# 更新峰值权益
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

# 计算回撤
        if self.peak_equity > 0:
            self.drawdown = (self.peak_equity - current_equity) / self.peak_equity
            self.max_drawdown = max(self.max_drawdown, self.drawdown)

# 风险管理: 回撤超过阈值时停止交易
        if self.drawdown > 0.20:  # 20% 最大回撤
            if self.position:
                self.log(f'超过最大回撤: {self.drawdown:.1%}')
                self.close()

    def stop(self):
        """回测结束时调用。"""
        final_equity = self.broker.getvalue()
        total_return = (final_equity - self.starting_cash) / self.starting_cash

        print('=' *50)
        print('最终结果')
        print('='*50)
        print(f'初始资金: {self.starting_cash:.2f}')
        print(f'最终权益: {final_equity:.2f}')
        print(f'总收益率: {total_return:.2%}')
        print(f'最大回撤: {self.max_drawdown:.2%}')
        print('='*50)

    def log(self, txt):
        dt = self.data.datetime.date(0)
        print(f'{dt.isoformat()}: {txt}')

```

---
## 金字塔加仓

### 固定金字塔层级

```python
class PyramidStrategy(bt.Strategy):
    """
    金字塔加仓: 在盈利仓位上加仓。

    参数:
        pyramid_levels: 额外入场次数 (默认: 3)
        pyramid_distance: 加仓前的价格变动 % (默认: 2%)
        level_size: 每次加仓占初始仓位 % (默认: 50%)
    """

    params = (
        ('pyramid_levels', 3),
        ('pyramid_distance', 0.02),  # 2% 价格变动
        ('level_size', 0.5),  # 初始仓位的 50%
    )

    def __init__(self):
        self.entry_prices = []  # 跟踪入场价格
        self.current_level = 0
        self.initial_size = 0
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# 初始入场
            self.order = self.buy(size=100)
            self.initial_size = 100
            self.entry_prices.append(self.data.close[0])
            self.current_level = 0
        else:

# 检查是否可以加仓
            if (self.current_level < self.p.pyramid_levels and
                len(self.entry_prices) > 0):

                last_entry = self.entry_prices[-1]
                price_move_pct = (self.data.close[0] - last_entry) / last_entry

# 价格有利变动时加仓
                if price_move_pct >= self.p.pyramid_distance:
                    add_size = int(self.initial_size*self.p.level_size)
                    self.order = self.buy(size=add_size)
                    self.entry_prices.append(self.data.close[0])
                    self.current_level += 1

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```

### 基于 ATR 的金字塔加仓

```python
class ATRPyramidStrategy(bt.Strategy):
    """
    基于 ATR 倍数进行金字塔加仓。

    按初始入场起特定 ATR 间隔的倍数加仓。
    """

    params = (
        ('atr_period', 14),
        ('atr_multiplier', 1.5),  # 每 1.5 ATR 变动加仓
        ('max_levels', 4),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.entry_price = None
        self.pyramid_levels = 0
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# 初始入场
            if len(self.data) > self.p.atr_period:
                self.order = self.buy(size=100)
                self.entry_price = self.data.close[0]
                self.pyramid_levels = 0
        else:

# 检查是否可以金字塔
            if (self.pyramid_levels < self.p.max_levels and
                self.entry_price is not None):

                profit_distance = self.data.close[0] - self.entry_price
                atr_distance = self.atr[0]*self.p.atr_multiplier*(self.pyramid_levels + 1)

                if profit_distance >= atr_distance:
                    add_size = 100  # 固定加仓大小
                    self.order = self.buy(size=add_size)
                    self.pyramid_levels += 1

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```

### 斐波那契金字塔加仓

```python
class FibonacciPyramidStrategy(bt.Strategy):
    """
    在斐波那契回撤位金字塔加仓。

    在初始利润目标的 23.6%、38.2%、50% 和 61.8% 处加仓。
    """

    params = (
        ('profit_target', 0.10),  # 10% 利润目标
    )

# 斐波那契层级
    fib_levels = [0.236, 0.382, 0.50, 0.618]

    def __init__(self):
        self.entry_price = None
        self.target_price = None
        self.triggered_levels = []
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# 初始入场
            self.order = self.buy(size=100)
            self.entry_price = self.data.close[0]
            self.target_price = self.entry_price*(1 + self.p.profit_target)
            self.triggered_levels = []
        else:

# 检查每个斐波那契层级
            profit = self.data.close[0] - self.entry_price
            total_profit = self.target_price - self.entry_price

            for i, fib_level in enumerate(self.fib_levels):
                if i not in self.triggered_levels:
                    fib_price = self.entry_price + (total_profit*fib_level)

                    if self.data.close[0] >= fib_price:

# 在此层级加仓
                        add_size = int(100*(1 - fib_level))  # 高层级加仓更小
                        self.order = self.buy(size=add_size)
                        self.triggered_levels.append(i)
                        break

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```

---
## 追踪止损实现

### 百分比追踪止损

```python
class TrailingStopStrategy(bt.Strategy):
    """
    实现基于百分比的追踪止损。

    止损价格随价格有利变动而上移，但从不向下移动。
    """

    params = (
        ('trail_pct', 0.03),  # 3% 追踪止损
    )

    def __init__(self):
        self.entry_price = None
        self.stop_price = None
        self.highest_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# 入场逻辑
            if len(self.data) >= 20:
                if self.data.close[0] > self.data.close[-1]:
                    self.order = self.buy()
                    self.entry_price = self.data.close[0]
                    self.highest_price = self.entry_price

# 设置初始止损
                    self.stop_price = self.highest_price*(1 - self.p.trail_pct)
        else:

# 更新最高价
            self.highest_price = max(self.highest_price, self.data.close[0])

# 更新追踪止损
            new_stop = self.highest_price*(1 - self.p.trail_pct)
            if new_stop > self.stop_price:
                self.stop_price = new_stop

# 检查止损
            if self.data.close[0] <= self.stop_price:
                self.order = self.close()

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None
            if not self.position:
                self.entry_price = None
                self.stop_price = None
                self.highest_price = None

```

### ATR 追踪止损

```python
class ATRTrailingStopStrategy(bt.Strategy):
    """
    基于 ATR 的追踪止损，可适应波动率。

    使用吊灯退出原理: 止损设为入场以来最高价的
    ATR 倍数下方。
    """

    params = (
        ('atr_period', 22),
        ('atr_multiplier', 3.0),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.highest_high = bt.indicators.Highest(self.data.high,
                                                   period=self.p.atr_period)
        self.entry_price = None
        self.stop_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# 入场
            if len(self.data) > self.p.atr_period:
                self.order = self.buy()
                self.entry_price = self.data.close[0]
        else:

# 使用吊灯退出计算追踪止损
            self.stop_price = self.highest_high[0] - (self.atr[0]*self.p.atr_multiplier)

# 确保止损在当前价格下方 (多头仓位)
            if self.stop_price >= self.data.close[0]:
                self.stop_price = self.data.close[0]*0.99

# 检查止损
            if self.data.close[0] <= self.stop_price:
                self.order = self.close()

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```

### 水位追踪止损

```python
class HighWaterMarkTrailingStop(bt.Strategy):
    """
    基于入场以来最高收盘价的追踪止损。

    比百分比追踪更激进 - 仅在价格创新高时锁定利润。
    """

    params = (
        ('trail_pct', 0.05),  # 最高收盘价下方 5%
        ('min_profit_pct', 0.02),  # 必须达到 2% 利润后追踪才激活
    )

    def __init__(self):
        self.highest_close = None
        self.stop_price = None
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:

# 入场
            if len(self.data) >= 20:
                sma = bt.indicators.SMA(self.data.close, period=20)
                if self.data.close[0] > sma[0]:
                    self.order = self.buy()
                    self.highest_close = self.data.close[0]
                    self.stop_price = None  # 达到最小利润前无止损
        else:

# 更新最高收盘价
            self.highest_close = max(self.highest_close, self.data.close[0])

# 计算利润
            profit_pct = (self.data.close[0] - self.highest_close) / self.highest_close

# 仅在达到最小利润后设置追踪止损
            if profit_pct > -self.p.min_profit_pct:
                new_stop = self.highest_close*(1 - self.p.trail_pct)

# 仅在止损更高时更新 (追踪)
                if self.stop_price is None or new_stop > self.stop_price:
                    self.stop_price = new_stop

# 检查止损
                if self.data.close[0] <= self.stop_price:
                    self.order = self.close()

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None
            if not self.position:
                self.highest_close = None
                self.stop_price = None

```

### 抛物线 SAR 追踪止损

```python
class PSARTrailingStopStrategy(bt.Strategy):
    """
    使用抛物线 SAR 作为追踪止损。

    SAR 根据趋势强度自动调整其加速度。
    """

    def __init__(self):
        self.psar = bt.indicators.PSAR(self.data)
        self.in_position = False
        self.order = None

    def next(self):
        if self.order:
            return

# 入场: SAR 显示上升趋势时
        if not self.position:
            if len(self.psar) > 2:

# SAR 低于价格 = 上升趋势
                if self.psar.psar[0] < self.data.low[0]:
                    if self.psar.psar[-1] >= self.data.low[-1]:  # 之前在上方，现在在下方
                        self.order = self.buy()
                        self.in_position = True
        else:

# 出场: SAR 穿越到价格上方 (趋势反转)
            if self.psar.psar[0] > self.data.high[0]:
                self.order = self.close()
                self.in_position = False

    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None

```

---
## Bracket 订单

### OCO (二选一) Bracket

```python
class BracketOrderStrategy(bt.Strategy):
    """
    实现 bracket 订单: 入场、止损和止盈。

    当入场成交时，同时设置止损单和止盈单。
    其中一个成交时，另一个自动取消。
    """

    params = (
        ('stop_loss_pct', 0.02),
        ('take_profit_pct', 0.04),
    )

    def __init__(self):
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.entry_price = None

    def next(self):

# 仅在无待处理订单时放置 bracket
        if any([self.entry_order, self.stop_order, self.limit_order]):
            return

        if not self.position:

# 下入场单
            self.entry_order = self.buy()
            self.entry_price = self.data.close[0]

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order == self.entry_order:

# 入场单成交 - 放置 bracket
            if order.status == order.Completed:
                self.entry_order = None
                self.place_bracket()

        elif order in [self.stop_order, self.limit_order]:

# bracket 订单成交 - 取消另一个
            if order.status == order.Completed:
                self.cancel_bracket()
                self.stop_order = None
                self.limit_order = None

        elif order.status == order.Cancelled:

# 处理已取消的订单
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def place_bracket(self):
        """放置止损和止盈订单。"""
        if self.entry_price is None:
            return

# 计算止损和止盈价格
        stop_price = self.entry_price*(1 - self.p.stop_loss_pct)
        limit_price = self.entry_price*(1 + self.p.take_profit_pct)

# 放置 bracket 订单
        self.stop_order = self.sell(exectype=order.Stop, price=stop_price)
        self.limit_order = self.sell(exectype=order.Limit, price=limit_price)

    def cancel_bracket(self):
        """取消所有待处理的 bracket 订单。"""
        if self.stop_order:
            self.cancel(self.stop_order)
        if self.limit_order:
            self.cancel(self.limit_order)

```

### 多级 Bracket (分批平仓)

```python
class ScaleOutBracketStrategy(bt.Strategy):
    """
    在多个利润目标分批平仓。

    在不同价格水平平掉部分仓位。
    """

    params = (
        ('stop_loss_pct', 0.02),
        ('targets', ((0.02, 0.25), (0.04, 0.25), (0.06, 0.50))),  # (利润%, 平仓%)
    )

    def __init__(self):
        self.entry_order = None
        self.stop_order = None
        self.target_orders = []
        self.triggered_targets = []
        self.entry_price = None
        self.position_size = 0

    def next(self):
        if self.entry_order or self.stop_order or any(self.target_orders):
            return

        if not self.position:
            self.entry_order = self.buy(size=100)
            self.position_size = 100

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order == self.entry_order and order.status == order.Completed:
            self.entry_order = None
            self.entry_price = order.executed.price
            self.place_initial_orders()

        elif order == self.stop_order and order.status == order.Completed:
            self.stop_order = None
            self.cancel_all_targets()

        elif order in self.target_orders and order.status == order.Completed:
            self.target_orders.remove(order)

# 第一个目标触发后将止损移至盈亏平衡
            if len(self.triggered_targets) == 1:
                self.update_stop_to_breakeven()

# 跟踪哪些目标已触发
        for i, target_order in enumerate(self.target_orders):
            if target_order == order and i not in self.triggered_targets:
                self.triggered_targets.append(i)

# 如果有更多目标，放置下一个
                if len(self.triggered_targets) < len(self.p.targets):
                    self.place_next_target()

    def place_initial_orders(self):
        """放置初始止损和第一个目标。"""
        if self.entry_price is None:
            return

# 放置止损
        stop_price = self.entry_price*(1 - self.p.stop_loss_pct)
        self.stop_order = self.sell(size=self.position_size, exectype=order.Stop,
                                    price=stop_price)

# 放置第一个目标
        self.place_next_target()

    def place_next_target(self):
        """基于触发层级放置下一个目标订单。"""
        level = len(self.triggered_targets)
        if level >= len(self.p.targets):
            return

        target_pct, close_pct = self.p.targets[level]
        target_price = self.entry_price*(1 + target_pct)
        close_size = int(self.position_size*close_pct)

        target_order = self.sell(size=close_size, exectype=order.Limit,
                                 price=target_price)
        self.target_orders.append(target_order)

    def update_stop_to_breakeven(self):
        """第一个目标达成后将止损移至盈亏平衡。"""
        if self.stop_order:
            self.cancel(self.stop_order)

# 计算剩余仓位大小
        remaining_size = self.position_size
        for _, close_pct in self.p.targets:
            remaining_size = int(remaining_size*(1 - close_pct))
            break  # 只减去第一个目标

        breakeven_price = self.entry_price*1.001  # 小缓冲
        self.stop_order = self.sell(size=remaining_size, exectype=order.Stop,
                                    price=breakeven_price)

    def cancel_all_targets(self):
        """取消所有剩余目标订单。"""
        for order in self.target_orders:
            self.cancel(order)
        self.target_orders = []

```

### 动态 Bracket 与追踪

```python
class DynamicBracketStrategy(bt.Strategy):
    """
    带动态调整的 bracket 订单。

    - 止损随价格追踪
    - 止盈根据波动率调整

    """

    params = (
        ('atr_period', 14),
        ('stop_atr_mult', 2.0),
        ('target_atr_mult', 4.0),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.highest_high = bt.indicators.Highest(self.data.high, period=20)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.entry_price = None
        self.highest_price = None

    def next(self):
        if self.entry_order:
            return

        if not self.position:

# 入场
            if len(self.data) > self.p.atr_period:
                self.entry_order = self.buy()
        else:

# 更新追踪止损
            self.update_trailing_stop()

# 根据波动率更新止盈
            self.update_take_profit()

    def update_trailing_stop(self):
        """更新追踪止损订单。"""
        if self.entry_price is None or len(self.data) < 2:
            return

# 计算新止损价格
        new_stop = self.highest_price - (self.atr[0]*self.p.stop_atr_mult)

# 价格有利变动时取消现有止损并放置新止损
        if self.stop_order:
            current_stop = self.stop_order.created.price if hasattr(self.stop_order, 'created') else new_stop

            if new_stop > current_stop:
                self.cancel(self.stop_order)
                stop_size = self.position.size
                self.stop_order = self.sell(size=stop_size, exectype=order.Stop,
                                            price=new_stop)
        else:

# 放置初始止损
            stop_size = self.position.size
            self.stop_order = self.sell(size=stop_size, exectype=order.Stop,
                                        price=new_stop)

    def update_take_profit(self):
        """根据当前波动率更新止盈。"""
        if self.entry_price is None:
            return

# 基于 ATR 的动态目标
        target_price = self.entry_price + (self.atr[0]* self.p.target_atr_mult)

# 仅在没有限价单或需要移动时放置/更新
        if not self.limit_order:
            limit_size = self.position.size
            self.limit_order = self.sell(size=limit_size, exectype=order.Limit,
                                         price=target_price)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order == self.entry_order and order.status == order.Completed:
            self.entry_order = None
            self.entry_price = order.executed.price
            self.highest_price = order.executed.price

# 每根 K 线更新最高价
        if self.position:
            self.highest_price = max(self.highest_price, self.data.close[0])

# 处理已成交订单
        if order.status == order.Completed:
            if order == self.stop_order:
                self.stop_order = None
                if self.limit_order:
                    self.cancel(self.limit_order)
                    self.limit_order = None
            elif order == self.limit_order:
                self.limit_order = None
                if self.stop_order:
                    self.cancel(self.stop_order)
                    self.stop_order = None

```

---
## 使用示例

### 运行策略

```python
import backtrader as bt
import backtrader.feeds as btfeeds

# 创建 cerebro

cerebro = bt.Cerebro()

# 添加数据源

data = btfeeds.CSVData(
    dataname='your_data.csv',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=-1
)
cerebro.adddata(data)

# 添加策略并设置参数

cerebro.addstrategy(
    ATRStopLoss,
    atr_period=14,
    atr_multiplier=2.0
)

# 设置初始资金

cerebro.broker.setcash(10000.0)

# 设置手续费

cerebro.broker.setcommission(commission=0.001)  # 0.1%

# 添加分析器

cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

# 运行

results = cerebro.run()
strat = results[0]

# 打印结果

print(f'夏普比率: {strat.analyzers.sharpe.get_analysis()}')
print(f'回撤: {strat.analyzers.drawdown.get_analysis()}')
print(f'收益: {strat.analyzers.returns.get_analysis()}')

# 绘图

cerebro.plot()

```

---
## 下一步

- [指标参考](../user_guide/indicators.md) - 可用指标
- [策略指南](../user_guide/strategies.md) - 策略开发
- [分析器](../user_guide/analyzers.md) - 绩效评估
