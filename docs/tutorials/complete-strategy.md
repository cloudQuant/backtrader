# 完整策略开发教程 / Complete Strategy Development Tutorial

> 从想法到实盘交易的完整工作流程 / Complete workflow from idea to live trading
>
> 更新日期 / Updated: 2026-03-01

---

## 目录 / Table of Contents

- [Part 1: 策略概念与设计](#part-1-策略概念与设计)
- [Part 2: 数据获取与准备](#part-2-数据获取与准备)
- [Part 3: 回测框架搭建](#part-3-回测框架搭建)
- [Part 4: 参数优化技术](#part-4-参数优化技术)
- [Part 5: 风险控制实现](#part-5-风险控制实现)
- [Part 6: 模拟交易](#part-6-模拟交易)
- [Part 7: 实盘部署](#part-7-实盘部署)
- [Part 8: 持续监控与维护](#part-8-持续监控与维护)

---

## Part 1: 策略概念与设计

### 1.1 策略开发生命周期

```
策略构思
    理论验证
        数据准备
            回测实现
                参数优化
                    风险评估
                        模拟交易
                            实盘部署
                                监控维护
                                    迭代改进
```

### 1.2 策略设计框架

一个完整的交易策略应包含以下核心要素：

#### 市场假说 (Market Hypothesis)

```python
"""
策略名称: 动量突破策略 (Momentum Breakthrough Strategy)

市场假说:
1. 价格在突破关键阻力位后倾向于延续趋势
2. 成交量放大确认突破的有效性
3. 动量效应在中短期内持续存在

适用市场:
- 趋势性明显的市场
- 波动率适中的品种
- 流动性高的主流品种

不适用场景:
- 震荡行情
- 低流动性品种
- 极端波动时期
"""
```

#### 入场条件 (Entry Conditions)

```python
class EntryConditions:
    """入场条件定义"""

    @staticmethod
    def trend_breakout(close, resistance, volume, avg_volume):
        """趋势突破入场"""
        return close > resistance and volume > avg_volume * 1.5

    @staticmethod
    def momentum_confirmation(rsi, macd, signal):
        """动量确认"""
        return rsi < 70 and macd > signal

    @staticmethod
    def volatility_filter(atr, price, threshold=0.02):
        """波动率过滤"""
        return (atr / price) < threshold
```

#### 出场条件 (Exit Conditions)

```python
class ExitConditions:
    """出场条件定义"""

    @staticmethod
    def take_profit(entry_price, current_price, target_pct=0.03):
        """止盈"""
        return current_price >= entry_price * (1 + target_pct)

    @staticmethod
    def stop_loss(entry_price, current_price, loss_pct=0.02):
        """止损"""
        return current_price <= entry_price * (1 - loss_pct)

    @staticmethod
    def trend_reversal(close, ma_short, ma_long):
        """趋势反转"""
        return close < ma_short and ma_short < ma_long

    @staticmethod
    def time_exit(bars_held, max_bars=50):
        """时间出场"""
        return bars_held >= max_bars
```

#### 仓位管理 (Position Sizing)

```python
class PositionSizer:
    """仓位管理"""

    @staticmethod
    def fixed_amount(cash, price, fixed_value=10000):
        """固定金额"""
        shares = int(fixed_value / price)
        return shares

    @staticmethod
    def fixed_percentage(cash, price, pct=0.1):
        """固定百分比"""
        value = cash * pct
        shares = int(value / price)
        return shares

    @staticmethod
    def kelly_criterion(cash, price, win_rate, avg_win, avg_loss):
        """凯利公式"""
        win_loss_ratio = avg_win / abs(avg_loss)
        kelly_pct = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        kelly_pct = max(0, min(kelly_pct, 0.25))  # 限制最大25%
        return int(cash * kelly_pct / price)

    @staticmethod
    def volatility_based(cash, price, atr, risk_per_trade=0.02):
        """基于波动率的仓位"""
        risk_amount = cash * risk_per_trade
        stop_distance = atr * 2
        shares = int(risk_amount / stop_distance)
        return max(1, shares)
```

### 1.3 完整策略模板

```python
import backtrader as bt
from typing import Optional


class CompleteStrategy(bt.Strategy):
    """完整策略模板

    实现了入场、出场、仓位管理和风险控制的完整框架。
    可通过继承和重写方法来定制具体策略逻辑。
    """

    # 策略参数
    params = (
        # 入场参数
        ('entry_period', 20),
        ('entry_threshold', 2.0),

        # 出场参数
        ('take_profit_pct', 0.03),
        ('stop_loss_pct', 0.02),
        ('max_hold_bars', 50),

        # 仓位参数
        ('position_sizing', 'fixed_pct'),  # fixed_pct, kelly, volatility
        ('position_size', 0.1),

        # 风控参数
        ('max_drawdown_pct', 0.15),
        ('daily_loss_limit', 0.05),
        ('max_positions', 3),
    )

    def __init__(self):
        """初始化策略"""
        # 数据引用
        self.dataclose = self.datas[0].close
        self.datahigh = self.datas[0].high
        self.datalow = self.datas[0].low
        self.datavol = self.datas[0].volume

        # 指标计算
        self._init_indicators()

        # 交易状态
        self.order: Optional[bt.Order] = None
        self.entry_price: float = 0
        self.entry_bar: int = 0
        self.bars_held: int = 0

        # 统计数据
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        # 风险控制
        self.daily_pnl = 0
        self.peak_value = self.broker.getvalue()
        self.current_drawdown = 0

    def _init_indicators(self):
        """初始化技术指标"""
        # 趋势指标
        self.sma_fast = bt.indicators.SMA(self.dataclose, period=self.p.entry_period)
        self.sma_slow = bt.indicators.SMA(self.dataclose, period=self.p.entry_period * 2)

        # 波动率指标
        self.atr = bt.indicators.ATR(self.data, period=14)

        # 动量指标
        self.rsi = bt.indicators.RSI(self.dataclose, period=14)
        self.macd = bt.indicators.MACD(self.dataclose)

        # 成交量指标
        self.sma_vol = bt.indicators.SMA(self.datavol, period=20)

        # 突破检测
        self.crossover = bt.indicators.CrossOver(self.dataclose, self.sma_fast)

    def notify_order(self, order: bt.Order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.entry_bar = len(self)
                self.log(f'买入执行: 价格={order.executed.price:.2f}, '
                        f'数量={order.executed.size:.2f}')
            else:
                self._record_trade(order)
                self.log(f'卖出执行: 价格={order.executed.price:.2f}, '
                        f'数量={order.executed.size:.2f}')

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'订单失败: {order.getstatusname()}')

        self.order = None

    def _record_trade(self, order: bt.Order):
        """记录交易结果"""
        self.trade_count += 1
        pnl = order.executed.pnl

        if pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1

    def notify_trade(self, trade: bt.Trade):
        """交易完成通知"""
        if trade.isclosed:
            self.log(f'交易完成: 利润={trade.pnl:.2f}, 手续费={trade.commission:.2f}')

    def next(self):
        """主交易逻辑"""
        # 更新风险指标
        self._update_risk_metrics()

        # 风险检查
        if not self._risk_check():
            return

        # 处理现有持仓
        if self.position:
            self._manage_position()
        else:
            self._check_entry()

    def _update_risk_metrics(self):
        """更新风险指标"""
        current_value = self.broker.getvalue()
        self.current_drawdown = (self.peak_value - current_value) / self.peak_value

        if current_value > self.peak_value:
            self.peak_value = current_value

    def _risk_check(self) -> bool:
        """风险检查"""
        # 检查最大回撤
        if self.current_drawdown > self.p.max_drawdown_pct:
            self.log(f'超过最大回撤限制: {self.current_drawdown:.2%}')
            if self.position:
                self.close()
            return False

        # 检查持仓数量限制
        if len(self) > 0 and self.position and self.broker.positions[self.datas[0]].size < 0:
            pass  # 可以添加更多逻辑

        return True

    def _check_entry(self):
        """检查入场条件"""
        # 等待指标就绪
        if len(self) < self.p.entry_period * 2:
            return

        # 避免重复下单
        if self.order:
            return

        # 入场条件
        if self._entry_signal():
            size = self._calculate_position_size()
            if size > 0:
                self.order = self.buy(size=size)

    def _entry_signal(self) -> bool:
        """生成入场信号"""
        # 默认: 金叉入场
        return self.crossover > 0 and self.rsi[0] < 70

    def _calculate_position_size(self) -> int:
        """计算仓位大小"""
        cash = self.broker.get_cash()
        price = self.dataclose[0]

        if self.p.position_sizing == 'fixed_pct':
            return PositionSizer.fixed_percentage(cash, price, self.p.position_size)
        elif self.p.position_sizing == 'volatility':
            return PositionSizer.volatility_based(cash, price, self.atr[0])
        else:
            return PositionSizer.fixed_percentage(cash, price, 0.1)

    def _manage_position(self):
        """管理现有持仓"""
        if self.order:
            return

        self.bars_held = len(self) - self.entry_bar

        # 止盈检查
        if ExitConditions.take_profit(
            self.entry_price, self.dataclose[0], self.p.take_profit_pct
        ):
            self.order = self.sell(size=self.position.size)
            self.log('止盈出场')
            return

        # 止损检查
        if ExitConditions.stop_loss(
            self.entry_price, self.dataclose[0], self.p.stop_loss_pct
        ):
            self.order = self.sell(size=self.position.size)
            self.log('止损出场')
            return

        # 时间出场
        if ExitConditions.time_exit(self.bars_held, self.p.max_hold_bars):
            self.order = self.sell(size=self.position.size)
            self.log('时间出场')
            return

        # 趋势反转出场
        if ExitConditions.trend_reversal(
            self.dataclose[0], self.sma_fast[0], self.sma_slow[0]
        ):
            self.order = self.sell(size=self.position.size)
            self.log('趋势反转出场')
            return

    def stop(self):
        """策略结束时调用"""
        self.log('=' * 50)
        self.log('策略结束统计:')
        self.log(f'  总交易次数: {self.trade_count}')
        self.log(f'  盈利次数: {self.win_count}')
        self.log(f'  亏损次数: {self.loss_count}')
        if self.trade_count > 0:
            self.log(f'  胜率: {self.win_count/self.trade_count:.2%}')
        self.log('=' * 50)

    def log(self, txt: str):
        """日志输出"""
        dt = self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} {txt}')
```

---

## Part 2: 数据获取与准备

### 2.1 数据源类型

Backtrader 支持多种数据源:

| 数据源类型 | 说明 | 适用场景 |
|-----------|------|---------|
| CSV 文件 | 本地历史数据 | 回测研究 |
| Pandas DataFrame | 内存数据 | 快速测试 |
| Yahoo Finance | 在线数据 | 股票回测 |
| CCXT | 加密货币交易所 | 数字货币 |
| Interactive Brokers | 实盘数据 | 股票/期货实盘 |
| CTP | 期货接口 | 国内期货实盘 |

### 2.2 CSV 数据加载

```python
import backtrader as bt
from datetime import datetime
from pathlib import Path


def load_csv_data(
    filepath: str,
    dtformat: str = '%Y-%m-%d',
    fromdate: Optional[datetime] = None,
    todate: Optional[datetime] = None,
) -> bt.feeds.GenericCSVData:
    """加载CSV格式数据

    Args:
        filepath: CSV文件路径
        dtformat: 日期格式
        fromdate: 起始日期
        todate: 结束日期

    Returns:
        Backtrader数据源对象
    """
    return bt.feeds.GenericCSVData(
        dataname=str(filepath),
        dtformat=dtformat,
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=fromdate,
        todate=todate,
    )


# 使用示例
data = load_csv_data(
    filepath='datas/orcl-1995-2014.txt',
    fromdate=datetime(2010, 1, 1),
    todate=datetime(2014, 12, 31),
)
```

### 2.3 Pandas 数据加载

```python
import pandas as pd
import backtrader as bt


def load_pandas_data(df: pd.DataFrame) -> bt.feeds.PandasData:
    """从Pandas DataFrame加载数据

    Args:
        df: 包含OHLCV数据的DataFrame

    Returns:
        Backtrader数据源对象
    """
    # 确保数据格式正确
    df = df.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')

    # 确保列名正确
    required_columns = ['open', 'high', 'low', 'close', 'volume']
    for col in required_columns:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    return bt.feeds.PandasData(dataname=df)


# 使用示例
def fetch_yahoo_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    """从Yahoo Finance获取数据"""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, end=end, interval='1d')
    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    return df


# df = fetch_yahoo_data('AAPL', '2020-01-01', '2024-01-01')
# data = load_pandas_data(df)
```

### 2.4 CCXT 加密货币数据

```python
import backtrader as bt
from datetime import datetime


def setup_ccxt_store(
    exchange: str = 'binance',
    api_key: str = None,
    secret: str = None,
    currency: str = 'USDT',
) -> bt.stores.CCXTStore:
    """配置CCXT交易所连接

    Args:
        exchange: 交易所ID
        api_key: API密钥
        secret: API密钥
        currency: 基础货币

    Returns:
        CCXTStore对象
    """
    config = {
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
    }

    return bt.stores.CCXTStore(
        exchange=exchange,
        currency=currency,
        config=config,
    )


def load_ccxt_live_data(
    store: bt.stores.CCXTStore,
    symbol: str,
    timeframe: bt.TimeFrame = bt.TimeFrame.Minutes,
    compression: int = 15,
    use_websocket: bool = True,
) -> bt.feeds.CCXTFeed:
    """加载CCXT实时数据

    Args:
        store: CCXTStore对象
        symbol: 交易对
        timeframe: 时间周期
        compression: 压缩周期数
        use_websocket: 是否使用WebSocket

    Returns:
        CCXT数据源对象
    """
    return store.getdata(
        dataname=symbol,
        timeframe=timeframe,
        compression=compression,
        use_websocket=use_websocket,
        ohlcv_limit=100,
        drop_newest=True,
        backfill_start=True,
    )


# 使用示例
def setup_live_trading(symbol: str = 'BTC/USDT'):
    """设置实盘交易环境"""
    # 创建Store
    store = setup_ccxt_store(
        exchange='binance',
        api_key='YOUR_API_KEY',
        secret='YOUR_SECRET',
    )

    # 获取数据源
    data = load_ccxt_live_data(store, symbol)

    # 获取Broker
    broker = store.getbroker(use_threaded_order_manager=True)

    return store, data, broker
```

### 2.5 数据预处理

```python
import backtrader as bt
import pandas as pd


class DataPreprocessor:
    """数据预处理工具"""

    @staticmethod
    def clean_data(df: pd.DataFrame) -> pd.DataFrame:
        """清理数据"""
        # 删除重复行
        df = df.drop_duplicates(subset=['datetime'])

        # 删除空值
        df = df.dropna()

        # 确保价格数据合理
        df = df[df['high'] >= df['low']]
        df = df[df['high'] >= df['close']]
        df = df[df['high'] >= df['open']]
        df = df[df['low'] <= df['close']]
        df = df[df['low'] <= df['open']]

        # 确保成交量为正
        df = df[df['volume'] > 0]

        return df

    @staticmethod
    def resample_data(
        df: pd.DataFrame,
        timeframe: str = '1D'
    ) -> pd.DataFrame:
        """重采样数据到指定时间周期

        Args:
            df: 原始数据
            timeframe: 目标周期 (如 '1H', '1D', '1W')

        Returns:
            重采样后的数据
        """
        df = df.copy()
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.set_index('datetime')

        resampled = df.resample(timeframe).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
        }).dropna()

        return resampled.reset_index()

    @staticmethod
    def add_features(df: pd.DataFrame) -> pd.DataFrame:
        """添加技术指标特征

        Args:
            df: 原始OHLCV数据

        Returns:
            添加了特征的数据
        """
        df = df.copy()

        # 价格变化
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))

        # 波动率
        df['volatility'] = df['returns'].rolling(20).std()

        # 价格区间
        df['range'] = (df['high'] - df['low']) / df['close']

        # 成交量变化
        df['volume_change'] = df['volume'].pct_change()

        return df

    @staticmethod
    def validate_data(data: bt.DataBase) -> bool:
        """验证Backtrader数据源

        Args:
            data: Backtrader数据源

        Returns:
            验证是否通过
        """
        # 检查数据长度
        if len(data) < 100:
            print('警告: 数据长度不足100个bar')
            return False

        # 检查数据连续性
        # (实际应用中可根据需要添加更复杂的检查)

        return True
```

### 2.6 多数据源组合

```python
def setup_multiple_data(symbols: list[str]) -> list[bt.DataBase]:
    """设置多个数据源

    用于多品种交易策略

    Args:
        symbols: 交易对列表

    Returns:
        数据源列表
    """
    data_feeds = []

    for symbol in symbols:
        # 这里可以是任何数据源
        data = bt.feeds.GenericCSVData(
            dataname=f'datas/{symbol}.csv',
            dtformat='%Y-%m-%d',
        )
        data._name = symbol  # 设置数据源名称
        data_feeds.append(data)

    return data_feeds


# 多数据源策略示例
class MultiDataStrategy(bt.Strategy):
    """多数据源策略"""

    def __init__(self):
        # 为每个数据源创建指标
        for data in self.datas:
            data.sma = bt.indicators.SMA(data.close, period=20)
            data.rsi = bt.indicators.RSI(data.close, period=14)

    def next(self):
        # 检查所有数据源的信号
        signals = []
        for data in self.datas:
            if data.close[0] > data.sma[0] and data.rsi[0] < 70:
                signals.append((data._name, 1))  # 看多信号
            elif data.close[0] < data.sma[0] and data.rsi[0] > 30:
                signals.append((data._name, -1))  # 看空信号

        # 组合信号决策
        if len(signals) >= len(self.datas) * 0.6:  # 60%以上数据源有信号
            print(f'综合信号: {signals}')
```

---

## Part 3: 回测框架搭建

### 3.1 基础回测设置

```python
import backtrader as bt
from datetime import datetime


class BacktestEngine:
    """回测引擎

    封装了完整的回测流程，包括数据加载、策略配置、性能分析等
    """

    def __init__(self, initial_cash: float = 100000):
        """初始化回测引擎

        Args:
            initial_cash: 初始资金
        """
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_cash)
        self.initial_cash = initial_cash
        self.results = None

    def add_data(self, data: bt.DataBase, name: str = None):
        """添加数据源

        Args:
            data: 数据源对象
            name: 数据源名称
        """
        if name:
            data._name = name
        self.cerebro.adddata(data)

    def add_strategy(self, strategy_class, **kwargs):
        """添加策略

        Args:
            strategy_class: 策略类
            **kwargs: 策略参数
        """
        self.cerebro.addstrategy(strategy_class, **kwargs)

    def set_commission(self, commission: float = 0.001):
        """设置手续费

        Args:
            commission: 手续费率 (默认0.1%)
        """
        self.cerebro.broker.setcommission(commission=commission)

    def set_slippage(self, slippage: float = 0.0001):
        """设置滑点

        Args:
            slippage: 滑点率 (默认0.01%)
        """
        self.cerebro.broker.set_slippage_perc(slippage)

    def add_analyzers(self):
        """添加性能分析器"""
        # 收益分析
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

        # 夏普比率
        self.cerebro.addanalyzer(
            bt.analyzers.SharpeRatio,
            _name='sharpe',
            timeframe=bt.TimeFrame.Days,
            annualize=True,
            riskfreerate=0.0,
        )

        # 回撤分析
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

        # 交易分析
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

        # 交易时间分析
        self.cerebro.addanalyzer(bt.analyzers.TimeDrawDown, _name='time_drawdown')

    def run(self):
        """运行回测"""
        self.add_analyzers()
        self.results = self.cerebro.run()
        return self.results[0]

    def get_analysis(self) -> dict:
        """获取分析结果

        Returns:
            包含所有性能指标的字典
        """
        if not self.results:
            raise ValueError('请先运行回测')

        strat = self.results[0]

        # 获取分析器结果
        ret_analyzer = strat.analyzers.returns.get_analysis()
        sharpe_analyzer = strat.analyzers.sharpe.get_analysis()
        drawdown_analyzer = strat.analyzers.drawdown.get_analysis()
        trades_analyzer = strat.analyzers.trades.get_analysis()

        # 计算最终收益
        final_value = self.cerebro.broker.getvalue()
        total_return = (final_value - self.initial_cash) / self.initial_cash

        return {
            'initial_cash': self.initial_cash,
            'final_value': final_value,
            'total_return': total_return,
            'annual_return': ret_analyzer.get('rnorm', 0),
            'sharpe_ratio': sharpe_analyzer.get('sharperatio', None),
            'max_drawdown': drawdown_analyzer['max']['drawdown'],
            'max_drawdown_len': drawdown_analyzer['max']['len'],
            'total_trades': trades_analyzer.get('total', {}).get('total', 0),
            'won_trades': trades_analyzer.get('won', {}).get('total', 0),
            'lost_trades': trades_analyzer.get('lost', {}).get('total', 0),
            'win_rate': (
                trades_analyzer.get('won', {}).get('total', 0) /
                trades_analyzer.get('total', {}).get('total', 1)
                if trades_analyzer.get('total', {}).get('total', 0) > 0
                else 0
            ),
        }

    def print_results(self):
        """打印回测结果"""
        analysis = self.get_analysis()

        print('=' * 60)
        print('回测结果 / Backtest Results')
        print('=' * 60)
        print(f'初始资金 / Initial Cash: {analysis["initial_cash"]:,.2f}')
        print(f'最终资金 / Final Value: {analysis["final_value"]:,.2f}')
        print(f'总收益率 / Total Return: {analysis["total_return"]:.2%}')
        print(f'年化收益率 / Annual Return: {analysis["annual_return"]:.2%}')
        print(f'夏普比率 / Sharpe Ratio: {analysis["sharpe_ratio"]:.2f}' if analysis["sharpe_ratio"] else '夏普比率 / Sharpe Ratio: N/A')
        print(f'最大回撤 / Max Drawdown: {analysis["max_drawdown"]:.2%}')
        print(f'最大回撤长度 / Max DD Length: {analysis["max_drawdown_len"]}')
        print('-' * 60)
        print(f'总交易次数 / Total Trades: {analysis["total_trades"]}')
        print(f'盈利次数 / Won Trades: {analysis["won_trades"]}')
        print(f'亏损次数 / Lost Trades: {analysis["lost_trades"]}')
        print(f'胜率 / Win Rate: {analysis["win_rate"]:.2%}')
        print('=' * 60)


# 使用示例
def run_basic_backtest(data_path: str):
    """运行基础回测示例"""
    # 创建引擎
    engine = BacktestEngine(initial_cash=100000)

    # 加载数据
    data = bt.feeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d',
        fromdate=datetime(2010, 1, 1),
        todate=datetime(2014, 12, 31),
    )
    engine.add_data(data)

    # 添加策略
    engine.add_strategy(
        CompleteStrategy,
        entry_period=20,
        take_profit_pct=0.03,
        stop_loss_pct=0.02,
    )

    # 设置交易成本
    engine.set_commission(0.001)
    engine.set_slippage(0.0001)

    # 运行回测
    engine.run()

    # 打印结果
    engine.print_results()

    return engine
```

### 3.2 可视化功能

```python
import matplotlib.pyplot as plt
import pandas as pd


class BacktestVisualizer:
    """回测结果可视化"""

    @staticmethod
    def plot_equity_curve(cerebro: bt.Cerebro, save_path: str = None):
        """绘制资金曲线

        Args:
            cerebro: Backtrader Cerebro实例
            save_path: 保存路径 (可选)
        """
        fig = cerebro.plot(style='candlestick', barup='r', bardown='g')[0][0]

        if save_path:
            fig.savefig(save_path, dpi=300, bbox_inches='tight')

        plt.show()

    @staticmethod
    def plot_returns_distribution(analysis: dict):
        """绘制收益分布

        Args:
            analysis: 分析结果字典
        """
        # 这里需要从交易记录中提取每笔交易的收益
        # 简化示例
        returns = [0.01, -0.005, 0.02, -0.01, 0.015, 0.03, -0.02]

        plt.figure(figsize=(10, 6))
        plt.hist(returns, bins=20, edgecolor='black')
        plt.axvline(0, color='red', linestyle='--')
        plt.xlabel('Returns')
        plt.ylabel('Frequency')
        plt.title('Returns Distribution')
        plt.grid(True, alpha=0.3)
        plt.show()

    @staticmethod
    def plot_drawdown(time_drawdown: dict):
        """绘制回撤曲线

        Args:
            time_drawdown: 时间回撤数据
        """
        df = pd.DataFrame.from_dict(time_drawdown, orient='index')
        df.index = pd.to_datetime(df.index)

        plt.figure(figsize=(12, 6))
        plt.fill_between(df.index, df[0], 0, alpha=0.3, color='red')
        plt.plot(df.index, df[0], color='red', linewidth=2)
        plt.xlabel('Date')
        plt.ylabel('Drawdown')
        plt.title('Drawdown Over Time')
        plt.grid(True, alpha=0.3)
        plt.show()

    @staticmethod
    def plot_monthly_returns(returns_data: dict):
        """绘制月度收益热力图

        Args:
            returns_data: TimeReturn分析结果
        """
        df = pd.DataFrame.from_dict(returns_data, orient='index')
        df.index = pd.to_datetime(df.index)
        df['year'] = df.index.year
        df['month'] = df.index.month
        df['returns'] = df[0]

        pivot = df.pivot(index='year', columns='month', values='returns')

        plt.figure(figsize=(12, 8))
        plt.imshow(pivot.values, cmap='RdYlGn', aspect='auto')
        plt.colorbar(label='Returns')
        plt.xticks(range(12), ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])
        plt.yticks(range(len(pivot.index)), pivot.index)
        plt.title('Monthly Returns Heatmap')
        plt.show()


# 使用Plotly进行交互式绘图
def plot_interactive_results(cerebro: bt.Cerebro):
    """使用Plotly绘制交互式图表"""
    try:
        # 使用backtrader的Plotly支持
        import backtrader.plot.plot_plotly as plt_plotly

        figs = cerebro.plot(style='plotly')
        for fig in figs:
            fig.show()
    except ImportError:
        print('Plotly not available, falling back to matplotlib')
        cerebro.plot()
```

### 3.3 性能报告生成

```python
import json
from datetime import datetime


class PerformanceReport:
    """性能报告生成器"""

    def __init__(self, analysis: dict, strategy_params: dict):
        """初始化报告

        Args:
            analysis: 回测分析结果
            strategy_params: 策略参数
        """
        self.analysis = analysis
        self.strategy_params = strategy_params
        self.report_time = datetime.now()

    def generate_text_report(self) -> str:
        """生成文本报告"""
        report = []
        report.append('=' * 60)
        report.append('策略回测报告 / Strategy Backtest Report')
        report.append('=' * 60)
        report.append(f'报告时间 / Report Time: {self.report_time}')
        report.append('')
        report.append('策略参数 / Strategy Parameters:')
        for k, v in self.strategy_params.items():
            report.append(f'  {k}: {v}')
        report.append('')
        report.append('性能指标 / Performance Metrics:')
        report.append(f'  总收益率 / Total Return: {self.analysis["total_return"]:.2%}')
        report.append(f'  年化收益率 / Annual Return: {self.analysis["annual_return"]:.2%}')
        report.append(f'  夏普比率 / Sharpe Ratio: {self.analysis["sharpe_ratio"]:.2f}')
        report.append(f'  最大回撤 / Max Drawdown: {self.analysis["max_drawdown"]:.2%}')
        report.append('')
        report.append('交易统计 / Trading Statistics:')
        report.append(f'  总交易次数 / Total Trades: {self.analysis["total_trades"]}')
        report.append(f'  盈利次数 / Won Trades: {self.analysis["won_trades"]}')
        report.append(f'  亏损次数 / Lost Trades: {self.analysis["lost_trades"]}')
        report.append(f'  胜率 / Win Rate: {self.analysis["win_rate"]:.2%}')
        report.append('=' * 60)

        return '\n'.join(report)

    def generate_html_report(self, filepath: str):
        """生成HTML报告

        Args:
            filepath: 保存路径
        """
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>策略回测报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        .metrics {{ margin: 20px 0; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        .positive {{ color: green; }}
        .negative {{ color: red; }}
    </style>
</head>
<body>
    <h1>策略回测报告 / Strategy Backtest Report</h1>
    <p>报告时间: {self.report_time}</p>

    <h2>策略参数</h2>
    <table>
        <tr><th>参数</th><th>值</th></tr>
"""

        for k, v in self.strategy_params.items():
            html += f"        <tr><td>{k}</td><td>{v}</td></tr>\n"

        html += """    </table>

    <h2>性能指标</h2>
    <table>
        <tr><th>指标</th><th>值</th></tr>
"""

        metrics = [
            ('总收益率', f'{self.analysis["total_return"]:.2%}'),
            ('年化收益率', f'{self.analysis["annual_return"]:.2%}'),
            ('夏普比率', f'{self.analysis["sharpe_ratio"]:.2f}'),
            ('最大回撤', f'{self.analysis["max_drawdown"]:.2%}'),
            ('总交易次数', f'{self.analysis["total_trades"]}'),
            ('胜率', f'{self.analysis["win_rate"]:.2%}'),
        ]

        for name, value in metrics:
            value_class = 'positive' if any(x in name for x in ['收益', '夏普', '胜率']) else ''
            if '回撤' in name:
                value_class = 'negative'
            html += f'        <tr><td>{name}</td><td class="{value_class}">{value}</td></tr>\n'

        html += """    </table>
</body>
</html>"""

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)

    def save_json(self, filepath: str):
        """保存JSON格式结果

        Args:
            filepath: 保存路径
        """
        result = {
            'report_time': self.report_time.isoformat(),
            'strategy_params': self.strategy_params,
            'analysis': self.analysis,
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    def generate_summary(self) -> dict:
        """生成摘要信息"""
        return {
            'is_profitable': self.analysis['total_return'] > 0,
            'sharpe_acceptable': (self.analysis['sharpe_ratio'] or 0) > 1.0,
            'drawdown_acceptable': self.analysis['max_drawdown'] < 0.2,
            'trades_sufficient': self.analysis['total_trades'] >= 30,
            'overall_score': self._calculate_score(),
        }

    def _calculate_score(self) -> float:
        """计算综合评分 (0-100)"""
        score = 0

        # 收益率评分 (30分)
        score += min(30, max(0, self.analysis['annual_return'] * 100))

        # 夏普比率评分 (30分)
        sharpe = self.analysis['sharpe_ratio'] or 0
        score += min(30, max(0, sharpe * 10))

        # 回撤评分 (20分)
        score += min(20, max(0, (1 - self.analysis['max_drawdown']) * 20))

        # 胜率评分 (20分)
        score += min(20, max(0, self.analysis['win_rate'] * 20))

        return round(score, 2)
```

---

## Part 4: 参数优化技术

### 4.1 参数空间定义

```python
from typing import Dict, List, Tuple, Any
import itertools


class ParameterSpace:
    """参数空间定义

    用于定义策略参数的搜索范围
    """

    def __init__(self):
        self.params: Dict[str, List[Any]] = {}

    def add_param(self, name: str, values: List[Any]):
        """添加参数

        Args:
            name: 参数名
            values: 参数值列表
        """
        self.params[name] = values

    def add_range(self, name: str, start: int, end: int, step: int = 1):
        """添加参数范围

        Args:
            name: 参数名
            start: 起始值
            end: 结束值 (不包含)
            step: 步长
        """
        self.params[name] = list(range(start, end, step))

    def generate_combinations(self) -> List[Dict[str, Any]]:
        """生成所有参数组合

        Returns:
            参数组合列表
        """
        keys = list(self.params.keys())
        values = list(self.params.values())

        combinations = []
        for combo in itertools.product(*values):
            param_dict = dict(zip(keys, combo))
            combinations.append(param_dict)

        return combinations

    def random_sample(self, n: int) -> List[Dict[str, Any]]:
        """随机采样参数组合

        Args:
            n: 采样数量

        Returns:
            随机参数组合列表
        """
        import random

        combinations = self.generate_combinations()
        return random.sample(combinations, min(n, len(combinations)))


# 使用示例
def create_parameter_space() -> ParameterSpace:
    """创建参数空间"""
    space = ParameterSpace()

    # 趋势参数
    space.add_range('fast_period', 5, 20, 5)
    space.add_range('slow_period', 20, 60, 10)

    # 动量参数
    space.add_param('rsi_period', [7, 14, 21])
    space.add_param('rsi_overbought', [70, 75, 80])
    space.add_param('rsi_oversold', [20, 25, 30])

    # 仓位参数
    space.add_param('position_size', [0.05, 0.1, 0.15, 0.2])

    # 风控参数
    space.add_param('stop_loss_pct', [0.01, 0.02, 0.03])
    space.add_param('take_profit_pct', [0.02, 0.03, 0.05])

    return space
```

### 4.2 网格搜索优化

```python
import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


class GridSearchOptimizer:
    """网格搜索优化器

    遍历所有参数组合进行回测，找到最优参数
    """

    def __init__(
        self,
        strategy_class,
        data: bt.DataBase,
        initial_cash: float = 100000,
        metric: str = 'sharpe_ratio',
    ):
        """初始化优化器

        Args:
            strategy_class: 策略类
            data: 数据源
            initial_cash: 初始资金
            metric: 优化目标指标
        """
        self.strategy_class = strategy_class
        self.data = data
        self.initial_cash = initial_cash
        self.metric = metric
        self.results = []

    def _run_single_backtest(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """运行单次回测

        Args:
            params: 策略参数

        Returns:
            回测结果
        """
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(self.initial_cash)

        # 克隆数据
        data_copy = bt.feeds.GenericCSVData(
            dataname=getattr(self.data, 'dataname', ''),
        )
        cerebro.adddata(data_copy)

        # 添加策略
        cerebro.addstrategy(self.strategy_class, **params)

        # 添加分析器
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

        # 设置手续费
        cerebro.broker.setcommission(commission=0.001)

        # 运行
        try:
            results = cerebro.run(runonce=True)
            strat = results[0]

            # 提取结果
            ret = strat.analyzers.returns.get_analysis()
            sharpe = strat.analyzers.sharpe.get_analysis()
            drawdown = strat.analyzers.drawdown.get_analysis()
            trades = strat.analyzers.trades.get_analysis()

            result = {
                'params': params,
                'total_return': ret.get('rtot', 0),
                'annual_return': ret.get('rnorm', 0),
                'sharpe_ratio': sharpe.get('sharperatio', None),
                'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
                'total_trades': trades.get('total', {}).get('total', 0),
            }

            return result

        except Exception as e:
            return {
                'params': params,
                'error': str(e),
                'sharpe_ratio': -999,
            }

    def optimize(
        self,
        param_space: ParameterSpace,
        parallel: bool = True,
        max_workers: int = None,
    ) -> pd.DataFrame:
        """执行优化

        Args:
            param_space: 参数空间
            parallel: 是否并行执行
            max_workers: 最大工作进程数

        Returns:
            结果DataFrame
        """
        combinations = param_space.generate_combinations()
        total = len(combinations)

        print(f'开始优化: {total} 个参数组合')

        if parallel:
            results = self._parallel_optimize(combinations, max_workers)
        else:
            results = []
            for i, params in enumerate(combinations):
                print(f'进度: {i+1}/{total}')
                result = self._run_single_backtest(params)
                results.append(result)

        self.results = results
        df = pd.DataFrame(results)

        # 按目标指标排序
        df = df.sort_values(by=self.metric, ascending=False)

        return df

    def _parallel_optimize(
        self,
        combinations: List[Dict[str, Any]],
        max_workers: int = None,
    ) -> List[Dict[str, Any]]:
        """并行执行优化

        Args:
            combinations: 参数组合列表
            max_workers: 最大工作进程数

        Returns:
            结果列表
        """
        results = []

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._run_single_backtest, params): params
                for params in combinations
            }

            for i, future in enumerate(as_completed(futures)):
                print(f'完成: {i+1}/{len(combinations)}')
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    print(f'回测失败: {e}')

        return results

    def get_best_params(self, n: int = 1) -> List[Dict[str, Any]]:
        """获取最优参数

        Args:
            n: 返回前n个最优参数

        Returns:
            最优参数列表
        """
        df = pd.DataFrame(self.results)
        df = df.sort_values(by=self.metric, ascending=False)
        return df.head(n).to_dict('records')


# 使用示例
def run_grid_search():
    """运行网格搜索优化"""
    # 加载数据
    data = bt.feeds.GenericCSVData(
        dataname='datas/orcl-1995-2014.txt',
        dtformat='%Y-%m-%d',
        fromdate=datetime(2010, 1, 1),
        todate=datetime(2012, 12, 31),
    )

    # 创建参数空间
    space = ParameterSpace()
    space.add_range('fast_period', 5, 15, 5)
    space.add_range('slow_period', 20, 40, 10)
    space.add_param('rsi_period', [14])

    # 创建优化器
    optimizer = GridSearchOptimizer(
        strategy_class=CompleteStrategy,
        data=data,
        metric='sharpe_ratio',
    )

    # 执行优化
    results_df = optimizer.optimize(space, parallel=False)

    print('=' * 60)
    print('优化结果 / Optimization Results')
    print('=' * 60)
    print(results_df.head(10))

    # 获取最优参数
    best = optimizer.get_best_params(1)[0]
    print(f'\n最优参数: {best["params"]}')
    print(f'夏普比率: {best["sharpe_ratio"]:.2f}')
    print(f'年化收益: {best["annual_return"]:.2%}')
    print(f'最大回撤: {best["max_drawdown"]:.2%}')

    return results_df
```

### 4.3 遗传算法优化

```python
import random
from deap import base, creator, tools, algorithms


class GeneticOptimizer:
    """遗传算法优化器

    使用遗传算法进行参数优化，适合参数空间较大的情况
    """

    def __init__(
        self,
        strategy_class,
        data: bt.DataBase,
        param_ranges: Dict[str, Tuple[int, int]],
        initial_cash: float = 100000,
    ):
        """初始化遗传优化器

        Args:
            strategy_class: 策略类
            data: 数据源
            param_ranges: 参数范围字典 {name: (min, max)}
            initial_cash: 初始资金
        """
        self.strategy_class = strategy_class
        self.data = data
        self.param_ranges = param_ranges
        self.initial_cash = initial_cash

        # 设置遗传算法
        self._setup_ga()

    def _setup_ga(self):
        """设置遗传算法"""
        # 创建适应度和个体类
        creator.create('FitnessMax', base.Fitness, weights=(1.0,))
        creator.create('Individual', list, fitness=creator.FitnessMax)

        self.toolbox = base.Toolbox()

        # 注册基因生成器
        param_names = list(self.param_ranges.keys())
        for name, (min_val, max_val) in self.param_ranges.items():
            self.toolbox.register(
                f'attr_{name}',
                random.randint,
                min_val,
                max_val,
            )

        # 注册个体和种群
        self.toolbox.register(
            'individual',
            tools.initCycle,
            creator.Individual,
            *[getattr(self.toolbox, f'attr_{name}') for name in param_names],
            n=1,
        )
        self.toolbox.register('population', tools.initRepeat, list, self.toolbox.individual)

        # 注册遗传操作
        self.toolbox.register('mate', tools.cxTwoPoint)
        self.toolbox.register('mutate', tools.mutFlipBit, indpb=0.05)
        self.toolbox.register('select', tools.selTournament, tournsize=3)

        # 注册评估函数
        self.toolbox.register('evaluate', self._evaluate)

    def _evaluate(self, individual: list) -> tuple:
        """评估个体适应度

        Args:
            individual: 参数列表

        Returns:
            (适应度值,)
        """
        # 转换为参数字典
        params = dict(zip(self.param_ranges.keys(), individual))

        # 运行回测
        cerebro = bt.Cerebro()
        cerebro.broker.setcash(self.initial_cash)
        cerebro.addstrategy(self.strategy_class, **params)
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')

        try:
            results = cerebro.run(runonce=True)
            sharpe = results[0].analyzers.sharpe.get_analysis().get('sharperatio', -999)
            return (sharpe or -999,)
        except Exception:
            return (-999,)

    def optimize(
        self,
        population_size: int = 50,
        generations: int = 10,
        cx_prob: float = 0.5,
        mut_prob: float = 0.2,
    ) -> Dict[str, Any]:
        """执行优化

        Args:
            population_size: 种群大小
            generations: 迭代代数
            cx_prob: 交叉概率
            mut_prob: 变异概率

        Returns:
            最优参数字典
        """
        # 创建初始种群
        population = self.toolbox.population(n=population_size)

        # 运行遗传算法
        result, log = algorithms.eaSimple(
            population,
            self.toolbox,
            cxpb=cx_prob,
            mutpb=mut_prob,
            ngen=generations,
            verbose=True,
        )

        # 获取最优个体
        best_ind = tools.selBest(result, 1)[0]
        best_params = dict(zip(self.param_ranges.keys(), best_ind))

        return {
            'params': best_params,
            'fitness': best_ind.fitness.values[0],
            'log': log,
        }


# 使用示例
def run_genetic_optimization():
    """运行遗传算法优化"""
    data = bt.feeds.GenericCSVData(
        dataname='datas/orcl-1995-2014.txt',
        dtformat='%Y-%m-%d',
        fromdate=datetime(2010, 1, 1),
        todate=datetime(2012, 12, 31),
    )

    # 定义参数范围
    param_ranges = {
        'fast_period': (5, 20),
        'slow_period': (20, 60),
        'rsi_period': (7, 21),
    }

    # 创建优化器
    optimizer = GeneticOptimizer(
        strategy_class=CompleteStrategy,
        data=data,
        param_ranges=param_ranges,
    )

    # 执行优化
    result = optimizer.optimize(
        population_size=30,
        generations=5,
    )

    print('=' * 60)
    print('遗传算法优化结果')
    print('=' * 60)
    print(f'最优参数: {result["params"]}')
    print(f'适应度: {result["fitness"]:.2f}')

    return result
```

### 4.4 避免过拟合

```python
class OverfittingDetector:
    """过拟合检测器

    检测策略是否过拟合
    """

    @staticmethod
    def train_test_split(
        data: bt.DataBase,
        train_ratio: float = 0.7,
    ) -> tuple:
        """分割训练集和测试集

        Args:
            data: 数据源
            train_ratio: 训练集比例

        Returns:
            (训练数据, 测试数据)
        """
        total_bars = len(data)
        train_size = int(total_bars * train_ratio)

        # 获取时间范围
        fromdate = data.fromdate
        todate = data.todate

        # 计算分割点
        time_span = (todate - fromdate).total_seconds()
        split_time = fromdate + pd.Timedelta(seconds=time_span * train_ratio)

        # 创建两个数据源
        train_data = bt.feeds.GenericCSVData(
            dataname=data.dataname,
            fromdate=fromdate,
            todate=split_time,
        )

        test_data = bt.feeds.GenericCSVData(
            dataname=data.dataname,
            fromdate=split_time,
            todate=todate,
        )

        return train_data, test_data

    @staticmethod
    def walk_forward_analysis(
        strategy_class,
        data: bt.DataBase,
        param_space: ParameterSpace,
        window_size: int = 252,
        step_size: int = 63,
    ) -> pd.DataFrame:
        """行走 forward 分析

        Args:
            strategy_class: 策略类
            data: 数据源
            param_space: 参数空间
            window_size: 训练窗口大小 (bar数)
            step_size: 步长 (bar数)

        Returns:
            分析结果DataFrame
        """
        results = []

        for start in range(0, len(data) - window_size - step_size, step_size):
            end = start + window_size
            test_end = min(end + step_size, len(data))

            # 训练期优化参数
            train_data = data[start:end]
            test_data = data[end:test_end]

            # 在训练期找到最优参数
            best_params = _optimize_on_train_data(
                strategy_class,
                train_data,
                param_space,
            )

            # 在测试期验证
            test_result = _validate_on_test_data(
                strategy_class,
                test_data,
                best_params,
            )

            results.append({
                'train_start': start,
                'train_end': end,
                'test_start': end,
                'test_end': test_end,
                'params': best_params,
                'test_return': test_result['total_return'],
                'test_sharpe': test_result['sharpe_ratio'],
            })

        return pd.DataFrame(results)

    @staticmethod
    def calculate_overfitting_score(
        train_metrics: dict,
        test_metrics: dict,
    ) -> float:
        """计算过拟合分数

        分数越高表示过拟合越严重

        Args:
            train_metrics: 训练集指标
            test_metrics: 测试集指标

        Returns:
            过拟合分数 (0-1)
        """
        # 计算各项指标的差异
        return_diff = abs(train_metrics['annual_return'] - test_metrics['annual_return'])
        sharpe_diff = abs((train_metrics['sharpe_ratio'] or 0) - (test_metrics['sharpe_ratio'] or 0))
        dd_diff = abs(train_metrics['max_drawdown'] - test_metrics['max_drawdown'])

        # 归一化差异
        score = (
            min(return_diff, 0.5) / 0.5 * 0.4 +
            min(sharpe_diff, 2.0) / 2.0 * 0.3 +
            min(dd_diff, 0.2) / 0.2 * 0.3
        )

        return score
```

---

## Part 5: 风险控制实现

### 5.1 止损止盈系统

```python
class RiskManager:
    """风险管理器

    实现各种风险控制功能
    """

    def __init__(self, strategy: bt.Strategy):
        """初始化风险管理器

        Args:
            strategy: 策略实例
        """
        self.strategy = strategy
        self.entry_price = 0
        self.entry_bar = 0
        self.highest_price = 0
        self.lowest_price = 0

    def update_entry_info(self, price: float, bar: int):
        """更新入场信息

        Args:
            price: 入场价格
            bar: 入场bar索引
        """
        self.entry_price = price
        self.entry_bar = bar
        self.highest_price = price
        self.lowest_price = price

    def update_extremes(self, price: float, position_type: str):
        """更新极值价格

        Args:
            price: 当前价格
            position_type: 持仓类型 ('long' or 'short')
        """
        if position_type == 'long':
            self.highest_price = max(self.highest_price, price)
        else:
            self.lowest_price = min(self.lowest_price, price)

    def check_stop_loss(
        self,
        current_price: float,
        stop_loss_pct: float,
        position_type: str = 'long',
    ) -> bool:
        """检查止损

        Args:
            current_price: 当前价格
            stop_loss_pct: 止损百分比
            position_type: 持仓类型

        Returns:
            是否触发止损
        """
        if position_type == 'long':
            loss_pct = (self.entry_price - current_price) / self.entry_price
            return loss_pct >= stop_loss_pct
        else:
            loss_pct = (current_price - self.entry_price) / self.entry_price
            return loss_pct >= stop_loss_pct

    def check_take_profit(
        self,
        current_price: float,
        take_profit_pct: float,
        position_type: str = 'long',
    ) -> bool:
        """检查止盈

        Args:
            current_price: 当前价格
            take_profit_pct: 止盈百分比
            position_type: 持仓类型

        Returns:
            是否触发止盈
        """
        if position_type == 'long':
            profit_pct = (current_price - self.entry_price) / self.entry_price
            return profit_pct >= take_profit_pct
        else:
            profit_pct = (self.entry_price - current_price) / self.entry_price
            return profit_pct >= take_profit_pct

    def check_trailing_stop(
        self,
        current_price: float,
        trailing_pct: float,
        position_type: str = 'long',
    ) -> bool:
        """检查移动止损

        Args:
            current_price: 当前价格
            trailing_pct: 移动止损百分比
            position_type: 持仓类型

        Returns:
            是否触发移动止损
        """
        if position_type == 'long':
            stop_price = self.highest_price * (1 - trailing_pct)
            return current_price < stop_price
        else:
            stop_price = self.lowest_price * (1 + trailing_pct)
            return current_price > stop_price


# 集成风险管理的策略示例
class RiskManagedStrategy(bt.Strategy):
    """带风险管理的策略"""

    params = (
        ('stop_loss_pct', 0.02),
        ('take_profit_pct', 0.05),
        ('trailing_stop_pct', 0.03),
        ('max_drawdown_pct', 0.15),
    )

    def __init__(self):
        super().__init__()
        self.risk_manager = RiskManager(self)
        self.peak_value = self.broker.getvalue()
        self.current_dd = 0

    def next(self):
        # 更新回撤
        self._update_drawdown()

        # 检查最大回撤限制
        if self.current_dd > self.p.max_drawdown_pct:
            if self.position:
                self.close()
            return

        # 管理现有持仓
        if self.position:
            self._manage_risk()

    def _update_drawdown(self):
        """更新回撤"""
        current_value = self.broker.getvalue()
        if current_value > self.peak_value:
            self.peak_value = current_value
        self.current_dd = (self.peak_value - current_value) / self.peak_value

    def _manage_risk(self):
        """管理持仓风险"""
        price = self.data.close[0]

        # 更新极值
        position_type = 'long' if self.position.size > 0 else 'short'
        self.risk_manager.update_extremes(price, position_type)

        # 检查止损
        if self.risk_manager.check_stop_loss(
            price,
            self.p.stop_loss_pct,
            position_type,
        ):
            self.close()
            self.log('止损出场')
            return

        # 检查止盈
        if self.risk_manager.check_take_profit(
            price,
            self.p.take_profit_pct,
            position_type,
        ):
            self.close()
            self.log('止盈出场')
            return

        # 检查移动止损
        if self.risk_manager.check_trailing_stop(
            price,
            self.p.trailing_stop_pct,
            position_type,
        ):
            self.close()
            self.log('移动止损出场')
            return

    def notify_order(self, order):
        if order.status == order.Completed and order.isbuy():
            self.risk_manager.update_entry_info(
                order.executed.price,
                len(self),
            )
```

### 5.2 仓位管理

```python
class PositionSizer(bt.Sizer):
    """仓位管理器

    根据不同方法计算仓位大小
    """

    params = (
        ('method', 'fixed_pct'),  # fixed, fixed_pct, kelly, volatility, risk_parity
        ('fixed_amount', 10000),
        ('pct', 0.1),
        ('risk_per_trade', 0.02),
        ('atr_multiplier', 2),
    )

    def _sizing_fixed(self):
        """固定金额"""
        return int(self.p.fixed_amount / self.data.close[0])

    def _sizing_fixed_pct(self):
        """固定百分比"""
        cash = self.broker.get_cash()
        value = cash * self.p.pct
        return int(value / self.data.close[0])

    def _sizing_volatility(self):
        """基于波动率的仓位"""
        cash = self.broker.get_cash()
        risk_amount = cash * self.p.risk_per_trade

        # 获取ATR
        if hasattr(self.strategy, 'atr'):
            atr = self.strategy.atr[0]
        else:
            atr = self.data.high[0] - self.data.low[0]

        stop_distance = atr * self.p.atr_multiplier
        shares = int(risk_amount / stop_distance)

        return max(1, shares)

    def _sizing_kelly(self):
        """凯利公式仓位"""
        # 需要历史交易数据
        # 简化实现
        cash = self.broker.get_cash()
        return int(cash * 0.1 / self.data.close[0])

    def getsizing(self, data, isbuy):
        """计算仓位大小"""
        if self.p.method == 'fixed':
            return self._sizing_fixed()
        elif self.p.method == 'fixed_pct':
            return self._sizing_fixed_pct()
        elif self.p.method == 'volatility':
            return self._sizing_volatility()
        elif self.p.method == 'kelly':
            return self._sizing_kelly()
        else:
            return self._sizing_fixed_pct()


# 使用示例
def setup_position_sizing():
    """设置仓位管理"""
    cerebro = bt.Cerebro()

    # 添加仓位管理器
    cerebro.addsizer(
        PositionSizer,
        method='volatility',
        risk_per_trade=0.02,
        atr_multiplier=2,
    )

    return cerebro
```

### 5.3 多层风险控制

```python
class MultiLevelRiskControl:
    """多层风险控制系统

    实现策略级、组合级和账户级的风险控制
    """

    def __init__(self, cerebro):
        """初始化风险控制系统

        Args:
            cerebro: Cerebro实例
        """
        self.cerebro = cerebro
        self.strategy_level = StrategyRiskControl()
        self.portfolio_level = PortfolioRiskControl()
        self.account_level = AccountRiskControl()

    def check_all_levels(self, strategy: bt.Strategy) -> bool:
        """检查所有风险级别

        Args:
            strategy: 策略实例

        Returns:
            是否通过所有风险检查
        """
        # 策略级检查
        if not self.strategy_level.check(strategy):
            return False

        # 组合级检查
        if not self.portfolio_level.check(strategy):
            return False

        # 账户级检查
        if not self.account_level.check(strategy, self.cerebro.broker):
            return False

        return True


class StrategyRiskControl:
    """策略级风险控制"""

    def check(self, strategy: bt.Strategy) -> bool:
        """检查策略级风险"""
        # 检查单个持仓风险
        if strategy.position:
            position_value = abs(strategy.position.size * strategy.data.close[0])
            account_value = strategy.broker.getvalue()

            if position_value / account_value > 0.3:  # 单个持仓不超过30%
                return False

        return True


class PortfolioRiskControl:
    """组合级风险控制"""

    def __init__(self):
        self.max_positions = 5
        self.max_correlated_exposure = 0.5

    def check(self, strategy: bt.Strategy) -> bool:
        """检查组合级风险"""
        # 检查持仓数量
        # (需要从Broker获取所有持仓)
        return True


class AccountRiskControl:
    """账户级风险控制"""

    def __init__(self):
        self.max_drawdown = 0.2
        self.daily_loss_limit = 0.05
        self.total_exposure_limit = 1.0

    def check(self, strategy: bt.Strategy, broker) -> bool:
        """检查账户级风险"""
        # 检查总敞口
        total_value = broker.getvalue()
        cash = broker.get_cash()
        exposure = (total_value - cash) / total_value

        if exposure > self.total_exposure_limit:
            return False

        return True
```

---

## Part 6: 模拟交易

### 6.1 模拟交易环境搭建

```python
class PaperTradingEngine:
    """模拟交易引擎

    在接近实盘的环境下测试策略
    """

    def __init__(
        self,
        strategy_class,
        initial_cash: float = 100000,
        commission: float = 0.001,
    ):
        """初始化模拟交易引擎

        Args:
            strategy_class: 策略类
            initial_cash: 初始资金
            commission: 手续费率
        """
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_cash)
        self.cerebro.broker.setcommission(commission=commission)

        self.strategy_class = strategy_class
        self.initial_cash = initial_cash
        self.is_running = False

    def setup_live_data(
        self,
        store: bt.stores.CCXTStore,
        symbol: str,
        timeframe: bt.TimeFrame = bt.TimeFrame.Minutes,
        compression: int = 1,
    ):
        """设置实时数据源

        Args:
            store: CCXTStore实例
            symbol: 交易对
            timeframe: 时间周期
            compression: 压缩周期
        """
        data = store.getdata(
            dataname=symbol,
            timeframe=timeframe,
            compression=compression,
            use_websocket=True,
            drop_newest=True,
            backfill_start=True,
        )
        self.cerebro.adddata(data)

        # 设置模拟broker
        broker = store.getbroker(use_threaded_order_manager=True)
        self.cerebro.setbroker(broker)

    def setup_paper_broker(self):
        """设置模拟Broker"""
        # 使用模拟Broker而非实盘
        self.cerebro.setbroker(bt.brokers.BackBroker())

    def add_strategy(self, **kwargs):
        """添加策略

        Args:
            **kwargs: 策略参数
        """
        self.cerebro.addstrategy(self.strategy_class, **kwargs)

    def run(self):
        """运行模拟交易"""
        self.is_running = True
        try:
            self.cerebro.run()
        except KeyboardInterrupt:
            print('\n停止模拟交易')
        finally:
            self.is_running = False

    def get_performance(self) -> dict:
        """获取模拟交易绩效"""
        final_value = self.cerebro.broker.getvalue()
        total_return = (final_value - self.initial_cash) / self.initial_cash

        return {
            'initial_cash': self.initial_cash,
            'final_value': final_value,
            'total_return': total_return,
        }
```

### 6.2 模拟交易监控

```python
import time
from datetime import datetime


class PaperTradingMonitor:
    """模拟交易监控器

    实时监控模拟交易的状态和绩效
    """

    def __init__(self, cerebro, update_interval: int = 60):
        """初始化监控器

        Args:
            cerebro: Cerebro实例
            update_interval: 更新间隔(秒)
        """
        self.cerebro = cerebro
        self.update_interval = update_interval
        self.is_monitoring = False

    def start(self):
        """启动监控"""
        self.is_monitoring = True
        print('=' * 60)
        print('模拟交易监控启动')
        print('=' * 60)

        while self.is_monitoring:
            self._update_display()
            time.sleep(self.update_interval)

    def stop(self):
        """停止监控"""
        self.is_monitoring = False

    def _update_display(self):
        """更新显示"""
        broker = self.cerebro.broker

        print('\n' + '=' * 60)
        print(f'更新时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")')
        print('-' * 60)
        print(f'账户价值: {broker.getvalue():,.2f}')
        print(f'可用现金: {broker.get_cash():,.2f}')
        print(f'持仓数量: {broker.getposition(self.cerebro.datas[0]).size:.4f}')
        print(f'当前价格: {self.cerebro.datas[0].close[0]:,.2f}')
        print('=' * 60)


class PaperTradingLogger:
    """模拟交易日志记录器"""

    def __init__(self, log_dir: str = 'logs/paper_trading'):
        """初始化日志记录器

        Args:
            log_dir: 日志目录
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.trade_log = []
        self.equity_curve = []

    def log_trade(self, trade_info: dict):
        """记录交易

        Args:
            trade_info: 交易信息字典
        """
        trade_info['timestamp'] = datetime.now().isoformat()
        self.trade_log.append(trade_info)

    def log_equity(self, equity: float):
        """记录权益

        Args:
            equity: 当前权益
        """
        self.equity_curve.append({
            'timestamp': datetime.now().isoformat(),
            'equity': equity,
        })

    def save_logs(self):
        """保存日志"""
        # 保存交易日志
        trade_file = self.log_dir / f'trades_{datetime.now().strftime("%Y%m%d")}.json'
        with open(trade_file, 'w') as f:
            json.dump(self.trade_log, f, indent=2)

        # 保存权益曲线
        equity_file = self.log_dir / f'equity_{datetime.now().strftime("%Y%m%d")}.json'
        with open(equity_file, 'w') as f:
            json.dump(self.equity_curve, f, indent=2)
```

### 6.3 模拟转实盘评估

```python
class PaperToLiveEvaluator:
    """模拟转实盘评估器

    评估模拟交易结果是否适合转为实盘
    """

    def __init__(self, min_trades: int = 30, min_days: int = 30):
        """初始化评估器

        Args:
            min_trades: 最小交易次数
            min_days: 最小交易天数
        """
        self.min_trades = min_trades
        self.min_days = min_days

    def evaluate(self, paper_results: dict) -> dict:
        """评估模拟交易结果

        Args:
            paper_results: 模拟交易结果

        Returns:
            评估结果
        """
        evaluation = {
            'ready_for_live': False,
            'reasons': [],
            'recommendations': [],
        }

        # 检查交易次数
        if paper_results.get('total_trades', 0) < self.min_trades:
            evaluation['reasons'].append(
                f'交易次数不足: {paper_results.get("total_trades", 0)} < {self.min_trades}'
            )
        else:
            evaluation['recommendations'].append('交易次数达标')

        # 检查收益率
        if paper_results.get('total_return', 0) <= 0:
            evaluation['reasons'].append('模拟交易未实现盈利')
        else:
            evaluation['recommendations'].append('模拟交易盈利')

        # 检查夏普比率
        sharpe = paper_results.get('sharpe_ratio', 0)
        if sharpe and sharpe < 1.0:
            evaluation['reasons'].append(f'夏普比率过低: {sharpe:.2f} < 1.0')
        else:
            evaluation['recommendations'].append('风险调整后收益良好')

        # 检查最大回撤
        max_dd = paper_results.get('max_drawdown', 1)
        if max_dd > 0.2:
            evaluation['reasons'].append(f'最大回撤过大: {max_dd:.2%} > 20%')
        else:
            evaluation['recommendations'].append('回撤控制良好')

        # 综合判断
        if len(evaluation['reasons']) == 0:
            evaluation['ready_for_live'] = True

        return evaluation

    def print_evaluation(self, evaluation: dict):
        """打印评估结果

        Args:
            evaluation: 评估结果
        """
        print('=' * 60)
        print('模拟转实盘评估结果')
        print('=' * 60)
        print(f'状态: {"可以转实盘" if evaluation["ready_for_live"] else "不建议转实盘"}')
        print()

        if evaluation['reasons']:
            print('问题:')
            for reason in evaluation['reasons']:
                print(f'  - {reason}')
            print()

        if evaluation['recommendations']:
            print('建议:')
            for rec in evaluation['recommendations']:
                print(f'  + {rec}')

        print('=' * 60)
```

---

## Part 7: 实盘部署

### 7.1 实盘交易系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     实盘交易系统                             │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ 数据采集层   │ -> │ 策略执行层   │ -> │ 风险控制层   │     │
│  │ Data Feed   │    │  Strategy   │    │ Risk Mgmt   │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│         │                   │                   │           │
│         v                   v                   v           │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │  CCXTStore  │    │   Broker    │    │  Monitor    │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 实盘部署配置

```python
class LiveTradingConfig:
    """实盘交易配置

    集中管理实盘交易的所有配置
    """

    def __init__(self, config_file: str = None):
        """初始化配置

        Args:
            config_file: 配置文件路径
        """
        if config_file:
            self.load_from_file(config_file)
        else:
            self._set_default_config()

    def _set_default_config(self):
        """设置默认配置"""
        # 交易所配置
        self.exchange = 'binance'
        self.api_key = None
        self.secret = None
        self.currency = 'USDT'

        # 交易品种
        self.symbol = 'BTC/USDT'

        # 策略配置
        self.strategy_params = {
            'fast_period': 10,
            'slow_period': 30,
            'position_size': 0.1,
        }

        # 风控配置
        self.max_position = 0.001  # BTC
        self.daily_loss_limit = 0.05
        self.max_drawdown = 0.15

        # 日志配置
        self.log_level = 'INFO'
        self.log_file = 'logs/live_trading.log'

    def load_from_file(self, filepath: str):
        """从文件加载配置

        Args:
            filepath: 配置文件路径
        """
        import json

        with open(filepath, 'r') as f:
            config = json.load(f)

        for key, value in config.items():
            setattr(self, key, value)

    def save_to_file(self, filepath: str):
        """保存配置到文件

        Args:
            filepath: 配置文件路径
        """
        import json

        config = {
            'exchange': self.exchange,
            'api_key': self.api_key,
            'secret': self.secret,
            'currency': self.currency,
            'symbol': self.symbol,
            'strategy_params': self.strategy_params,
            'max_position': self.max_position,
            'daily_loss_limit': self.daily_loss_limit,
            'max_drawdown': self.max_drawdown,
        }

        with open(filepath, 'w') as f:
            json.dump(config, f, indent=2)


# 使用环境变量和配置文件的安全配置
def load_secure_config() -> LiveTradingConfig:
    """加载安全的配置

    优先从环境变量读取敏感信息
    """
    import os

    config = LiveTradingConfig()

    # 从环境变量读取API密钥
    config.api_key = os.getenv('EXCHANGE_API_KEY')
    config.secret = os.getenv('EXCHANGE_SECRET')

    if not config.api_key or not config.secret:
        raise ValueError('请设置环境变量 EXCHANGE_API_KEY 和 EXCHANGE_SECRET')

    return config
```

### 7.3 实盘交易引擎

```python
class LiveTradingEngine:
    """实盘交易引擎

    管理实盘交易的完整生命周期
    """

    def __init__(self, config: LiveTradingConfig):
        """初始化实盘交易引擎

        Args:
            config: 实盘交易配置
        """
        self.config = config
        self.cerebro = bt.Cerebro()

        # 状态管理
        self.is_running = False
        self.start_time = None

        # 监控和日志
        self.monitor = None
        self.logger = None

    def setup(self):
        """设置实盘环境"""
        # 创建Store
        self.store = bt.stores.CCXTStore(
            exchange=self.config.exchange,
            currency=self.config.currency,
            config={
                'apiKey': self.config.api_key,
                'secret': self.config.secret,
                'enableRateLimit': True,
            },
        )

        # 设置数据源
        self.data = self.store.getdata(
            dataname=self.config.symbol,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            use_websocket=True,
            drop_newest=True,
            backfill_start=True,
        )
        self.cerebro.adddata(self.data)

        # 设置Broker
        self.broker = self.store.getbroker(
            use_threaded_order_manager=True,
            max_retries=3,
        )
        self.cerebro.setbroker(self.broker)

        # 添加策略
        self.cerebro.addstrategy(**self.config.strategy_params)

    def add_monitoring(self):
        """添加监控"""
        self.monitor = LiveTradingMonitor(
            cerebro=self.cerebro,
            alert_callback=self._send_alert,
        )

    def add_logging(self):
        """添加日志"""
        self.logger = LiveTradingLogger(
            log_file=self.config.log_file,
            level=self.config.log_level,
        )

    def start(self):
        """启动实盘交易"""
        print('=' * 60)
        print('实盘交易启动')
        print('=' * 60)
        print(f'交易所: {self.config.exchange}')
        print(f'交易对: {self.config.symbol}')
        print(f'策略参数: {self.config.strategy_params}')
        print('=' * 60)

        self.is_running = True
        self.start_time = datetime.now()

        try:
            self.cerebro.run()
        except KeyboardInterrupt:
            print('\n用户停止交易')
        except Exception as e:
            print(f'\n交易异常: {e}')
            self._send_alert(f'交易异常: {e}')
        finally:
            self.stop()

    def stop(self):
        """停止实盘交易"""
        self.is_running = False

        # 平仓
        if self.broker.getposition(self.data):
            print('正在平仓...')
            self.close_position()

        # 生成报告
        self._generate_final_report()

    def close_position(self):
        """平仓"""
        position = self.broker.getposition(self.data)
        if position.size > 0:
            order = self.sell(size=abs(position.size))
        elif position.size < 0:
            order = self.buy(size=abs(position.size))

    def _send_alert(self, message: str):
        """发送告警

        Args:
            message: 告警消息
        """
        print(f'[ALERT] {message}')
        # 这里可以集成各种告警方式: 邮件、短信、钉钉、Telegram等

    def _generate_final_report(self):
        """生成最终报告"""
        if self.start_time:
            duration = datetime.now() - self.start_time
            print(f'运行时间: {duration}')

        print(f'最终资金: {self.broker.getvalue():,.2f}')
```

### 7.4 异常处理和恢复

```python
class LiveTradingErrorHandler:
    """实盘交易错误处理器

    处理各种异常情况并实现自动恢复
    """

    def __init__(self, engine: LiveTradingEngine):
        """初始化错误处理器

        Args:
            engine: 实盘交易引擎
        """
        self.engine = engine
        self.error_count = {}
        self.max_retries = 3

    def handle_order_error(self, order: bt.Order):
        """处理订单错误

        Args:
            order: 失败的订单
        """
        error_type = order.getstatusname()

        if error_type in ['Rejected', 'Margin']:
            # 资金不足或订单被拒绝
            print(f'订单被拒绝: {error_type}')
            self._send_alert(f'订单被拒绝: {error_type}')

        elif error_type == 'Canceled':
            # 订单取消
            print('订单已取消')

    def handle_network_error(self, error: Exception):
        """处理网络错误

        Args:
            error: 网络错误
        """
        error_key = 'network'
        self.error_count[error_key] = self.error_count.get(error_key, 0) + 1

        if self.error_count[error_key] <= self.max_retries:
            print(f'网络错误，尝试重连... ({self.error_count[error_key]}/{self.max_retries})')
            time.sleep(5)
        else:
            self._send_alert('网络连接失败，请手动检查')
            raise error

    def handle_data_error(self, error: Exception):
        """处理数据错误

        Args:
            error: 数据错误
        """
        print(f'数据错误: {error}')
        # 记录错误但继续运行
        # CCXT会自动尝试重连

    def _send_alert(self, message: str):
        """发送告警"""
        if self.engine.monitor:
            self.engine.monitor.send_alert(message)
```

---

## Part 8: 持续监控与维护

### 8.1 实时监控系统

```python
class LiveTradingMonitor:
    """实盘交易监控

    实时监控交易状态并发送告警
    """

    def __init__(
        self,
        cerebro,
        alert_callback=None,
        check_interval: int = 60,
    ):
        """初始化监控

        Args:
            cerebro: Cerebro实例
            alert_callback: 告警回调函数
            check_interval: 检查间隔(秒)
        """
        self.cerebro = cerebro
        self.alert_callback = alert_callback
        self.check_interval = check_interval
        self.is_monitoring = False

        # 监控阈值
        self.thresholds = {
            'min_balance': 1000,
            'max_position_pct': 0.95,
            'max_drawdown': 0.2,
            'idle_time': 3600,  # 1小时无交易
        }

        # 状态追踪
        self.last_trade_time = datetime.now()
        self.peak_value = cerebro.broker.getvalue()

    def start(self):
        """启动监控"""
        self.is_monitoring = True
        while self.is_monitoring:
            self._check_all()
            time.sleep(self.check_interval)

    def stop(self):
        """停止监控"""
        self.is_monitoring = False

    def _check_all(self):
        """检查所有监控项"""
        self._check_balance()
        self._check_position()
        self._check_drawdown()
        self._check_idle()

    def _check_balance(self):
        """检查账户余额"""
        balance = self.cerebro.broker.get_cash()
        if balance < self.thresholds['min_balance']:
            self.send_alert(f'余额过低: {balance:.2f}')

    def _check_position(self):
        """检查持仓"""
        position = self.cerebro.broker.getposition(self.cerebro.datas[0])
        if position:
            total_value = self.cerebro.broker.getvalue()
            position_value = abs(position.size * self.cerebro.datas[0].close[0])
            position_pct = position_value / total_value

            if position_pct > self.thresholds['max_position_pct']:
                self.send_alert(f'持仓比例过高: {position_pct:.2%}')

    def _check_drawdown(self):
        """检查回撤"""
        current_value = self.cerebro.broker.getvalue()
        if current_value > self.peak_value:
            self.peak_value = current_value

        drawdown = (self.peak_value - current_value) / self.peak_value
        if drawdown > self.thresholds['max_drawdown']:
            self.send_alert(f'回撤过大: {drawdown:.2%}')

    def _check_idle(self):
        """检查空闲时间"""
        idle_time = (datetime.now() - self.last_trade_time).total_seconds()
        if idle_time > self.thresholds['idle_time']:
            self.send_alert(f'长时间无交易: {idle_time/3600:.1f}小时')

    def update_trade_time(self):
        """更新最后交易时间"""
        self.last_trade_time = datetime.now()

    def send_alert(self, message: str):
        """发送告警

        Args:
            message: 告警消息
        """
        print(f'[MONITOR] {message}')
        if self.alert_callback:
            self.alert_callback(message)
```

### 8.2 性能分析

```python
class PerformanceAnalyzer:
    """性能分析器

    分析实盘交易的表现
    """

    def __init__(self):
        """初始化分析器"""
        self.trades = []
        self.equity_curve = []

    def add_trade(self, trade_info: dict):
        """添加交易记录

        Args:
            trade_info: 交易信息
        """
        self.trades.append(trade_info)

    def add_equity_point(self, equity: float, timestamp: datetime = None):
        """添加权益点

        Args:
            equity: 权益值
            timestamp: 时间戳
        """
        self.equity_curve.append({
            'timestamp': timestamp or datetime.now(),
            'equity': equity,
        })

    def calculate_metrics(self) -> dict:
        """计算性能指标

        Returns:
            性能指标字典
        """
        if not self.trades:
            return {}

        # 基本统计
        pnls = [t.get('pnl', 0) for t in self.trades]
        winning_trades = [p for p in pnls if p > 0]
        losing_trades = [p for p in pnls if p < 0]

        metrics = {
            'total_trades': len(self.trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(self.trades) if self.trades else 0,
            'total_pnl': sum(pnls),
            'avg_win': sum(winning_trades) / len(winning_trades) if winning_trades else 0,
            'avg_loss': sum(losing_trades) / len(losing_trades) if losing_trades else 0,
            'profit_factor': (
                sum(winning_trades) / abs(sum(losing_trades))
                if losing_trades else float('inf')
            ),
        }

        # 计算收益率和回撤
        if len(self.equity_curve) > 1:
            equity_values = [e['equity'] for e in self.equity_curve]
            initial = equity_values[0]

            returns = pd.Series(equity_values).pct_change().dropna()

            metrics.update({
                'total_return': (equity_values[-1] - initial) / initial,
                'volatility': returns.std() * np.sqrt(252) if len(returns) > 0 else 0,
                'sharpe_ratio': (
                    returns.mean() / returns.std() * np.sqrt(252)
                    if len(returns) > 0 and returns.std() > 0 else 0
                ),
                'max_drawdown': self._calculate_max_drawdown(equity_values),
            })

        return metrics

    def _calculate_max_drawdown(self, equity_values: list) -> float:
        """计算最大回撤

        Args:
            equity_values: 权益值列表

        Returns:
            最大回撤
        """
        if not equity_values:
            return 0

        peak = equity_values[0]
        max_dd = 0

        for value in equity_values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def generate_report(self) -> str:
        """生成分析报告

        Returns:
            报告文本
        """
        metrics = self.calculate_metrics()

        lines = []
        lines.append('=' * 60)
        lines.append('实盘交易分析报告')
        lines.append('=' * 60)

        if not metrics:
            lines.append('暂无交易数据')
            return '\n'.join(lines)

        lines.append('交易统计:')
        lines.append(f'  总交易次数: {metrics["total_trades"]}')
        lines.append(f'  盈利次数: {metrics["winning_trades"]}')
        lines.append(f'  亏损次数: {metrics["losing_trades"]}')
        lines.append(f'  胜率: {metrics["win_rate"]:.2%}')

        if 'total_return' in metrics:
            lines.append('')
            lines.append('收益指标:')
            lines.append(f'  总收益率: {metrics["total_return"]:.2%}')
            lines.append(f'  波动率: {metrics["volatility"]:.2%}')
            lines.append(f'  夏普比率: {metrics["sharpe_ratio"]:.2f}')
            lines.append(f'  最大回撤: {metrics["max_drawdown"]:.2%}')

        lines.append('')
        lines.append('盈亏分析:')
        lines.append(f'  平均盈利: {metrics["avg_win"]:.2f}')
        lines.append(f'  平均亏损: {metrics["avg_loss"]:.2f}')
        lines.append(f'  盈亏比: {metrics["profit_factor"]:.2f}')

        lines.append('=' * 60)

        return '\n'.join(lines)
```

### 8.3 策略迭代改进

```python
class StrategyIteration:
    """策略迭代改进

    基于实盘数据持续改进策略
    """

    def __init__(self, initial_params: dict):
        """初始化迭代器

        Args:
            initial_params: 初始参数
        """
        self.params_history = [initial_params]
        self.performance_history = []
        self.current_version = 1

    def evaluate_current_performance(self, metrics: dict) -> dict:
        """评估当前表现

        Args:
            metrics: 性能指标

        Returns:
            评估结果
        """
        evaluation = {
            'needs_reoptimization': False,
            'reasons': [],
            'suggestions': [],
        }

        # 检查胜率
        win_rate = metrics.get('win_rate', 0)
        if win_rate < 0.4:
            evaluation['needs_reoptimization'] = True
            evaluation['reasons'].append(f'胜率过低: {win_rate:.2%}')
            evaluation['suggestions'].append('考虑调整入场条件')

        # 检查夏普比率
        sharpe = metrics.get('sharpe_ratio', 0)
        if sharpe < 0.5:
            evaluation['needs_reoptimization'] = True
            evaluation['reasons'].append(f'夏普比率过低: {sharpe:.2f}')
            evaluation['suggestions'].append('优化风险调整后收益')

        # 检查回撤
        max_dd = metrics.get('max_drawdown', 0)
        if max_dd > 0.15:
            evaluation['needs_reoptimization'] = True
            evaluation['reasons'].append(f'回撤过大: {max_dd:.2%}')
            evaluation['suggestions'].append('收紧止损')

        return evaluation

    def suggest_param_adjustments(
        self,
        evaluation: dict,
        current_params: dict,
    ) -> dict:
        """建议参数调整

        Args:
            evaluation: 评估结果
            current_params: 当前参数

        Returns:
            建议的新参数
        """
        suggestions = current_params.copy()

        for reason in evaluation['reasons']:
            if '胜率' in reason:
                # 调整入场参数
                suggestions['rsi_overbought'] = current_params.get('rsi_overbought', 70) - 5
                suggestions['rsi_oversold'] = current_params.get('rsi_oversold', 30) + 5

            elif '回撤' in reason:
                # 收紧止损
                suggestions['stop_loss_pct'] = current_params.get('stop_loss_pct', 0.02) * 0.8

        return suggestions

    def create_new_version(self, new_params: dict) -> int:
        """创建新版本

        Args:
            new_params: 新参数

        Returns:
            新版本号
        """
        self.params_history.append(new_params)
        self.current_version += 1
        return self.current_version

    def compare_versions(self) -> pd.DataFrame:
        """比较各版本表现

        Returns:
            比较结果DataFrame
        """
        return pd.DataFrame(self.performance_history)
```

---

## 附录: 完整示例策略

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
完整示例: 双均线突破策略

这是一个从回测到实盘的完整示例策略。
"""
import backtrader as bt
from datetime import datetime


class DualMAStrategy(bt.Strategy):
    """双均线突破策略

    使用快慢均线交叉产生交易信号，
    配合RSI过滤和止损止盈。
    """

    params = (
        # 均线参数
        ('fast_period', 10),
        ('slow_period', 30),

        # RSI参数
        ('rsi_period', 14),
        ('rsi_overbought', 70),
        ('rsi_oversold', 30),

        # 出场参数
        ('take_profit_pct', 0.03),
        ('stop_loss_pct', 0.02),

        # 仓位参数
        ('position_size', 0.1),
    )

    def __init__(self):
        # 指标
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

        # 交易状态
        self.order = None
        self.entry_price = 0

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.log(f'买入 @ {order.executed.price:.2f}')
            else:
                pnl = order.executed.pnl
                self.log(f'卖出 @ {order.executed.price:.2f}, 利润: {pnl:.2f}')

        self.order = None

    def next(self):
        # 等待指标就绪
        if len(self) < self.p.slow_period:
            return

        # 有待处理订单
        if self.order:
            return

        # 管理现有持仓
        if self.position:
            self._manage_position()
        else:
            self._check_entry()

    def _check_entry(self):
        """检查入场条件"""
        # 金叉且RSI不超买
        if self.crossover > 0 and self.rsi[0] < self.p.rsi_overbought:
            size = self._calculate_size()
            self.order = self.buy(size=size)

    def _manage_position(self):
        """管理持仓"""
        current_price = self.data.close[0]

        # 止盈
        if current_price >= self.entry_price * (1 + self.p.take_profit_pct):
            self.order = self.sell(size=self.position.size)
            self.log('止盈')
            return

        # 止损
        if current_price <= self.entry_price * (1 - self.p.stop_loss_pct):
            self.order = self.sell(size=self.position.size)
            self.log('止损')
            return

        # 死叉出场
        if self.crossover < 0:
            self.order = self.sell(size=self.position.size)
            self.log('趋势反转出场')

    def _calculate_size(self):
        """计算仓位"""
        cash = self.broker.get_cash()
        value = cash * self.p.position_size
        return int(value / self.data.close[0])

    def log(self, txt):
        dt = self.data.datetime.date(0)
        print(f'{dt} {txt}')


# 运行回测
def run_backtest():
    """运行回测"""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    # 添加数据
    data = bt.feeds.GenericCSVData(
        dataname='datas/orcl-1995-2014.txt',
        dtformat='%Y-%m-%d',
        fromdate=datetime(2010, 1, 1),
        todate=datetime(2014, 12, 31),
    )
    cerebro.adddata(data)

    # 添加策略
    cerebro.addstrategy(DualMAStrategy)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # 运行
    results = cerebro.run()
    strat = results[0]

    # 打印结果
    print('=' * 60)
    print('回测结果')
    print('=' * 60)
    print(f'初始资金: {100000:,.2f}')
    print(f'最终资金: {cerebro.broker.getvalue():,.2f}')

    ret = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    print(f'总收益率: {ret.get("rtot", 0):.2%}')
    print(f'年化收益率: {ret.get("rnorm", 0):.2%}')
    print(f'夏普比率: {sharpe.get("sharperatio", 0):.2f}')
    print(f'最大回撤: {drawdown["max"]["drawdown"]:.2%}')
    print(f'总交易次数: {trades.get("total", {}).get("total", 0)}')
    print('=' * 60)


if __name__ == '__main__':
    run_backtest()
```

---

## 常见问题与解决方案

### 问题1: 策略不交易

**可能原因:**
- 指标未就绪 (minperiod)
- 交易条件过于严格
- 资金不足
- 数据问题

**解决方案:**
```python
def next(self):
    # 添加日志
    self.log(f'Close: {self.data.close[0]:.2f}')
    self.log(f'Fast MA: {self.fast_ma[0]:.2f}')
    self.log(f'Slow MA: {self.slow_ma[0]:.2f}')
    self.log(f'Cash: {self.broker.get_cash():.2f}')

    # 检查指标
    if len(self) < self.p.slow_period:
        return

    # 检查资金
    if self.broker.get_cash() < 1000:
        return
```

### 问题2: 回测与实盘差异大

**可能原因:**
- 未考虑手续费和滑点
- 数据质量问题
- 过拟合
- 实盘执行延迟

**解决方案:**
```python
# 设置合理的交易成本
cerebro.broker.setcommission(commission=0.001)  # 0.1% 手续费
cerebro.broker.set_slippage_perc(0.0005)       # 0.05% 滑点

# 使用样本外数据验证
train_data, test_data = OverfittingDetector.train_test_split(data)
```

### 问题3: 参数优化过拟合

**解决方案:**
```python
# 使用交叉验证
cv_results = OverfittingDetector.walk_forward_analysis(
    strategy_class,
    data,
    param_space,
)

# 检查训练集和测试集表现
score = OverfittingDetector.calculate_overfitting_score(
    train_metrics,
    test_metrics,
)
```

---

## 总结

本教程涵盖了从策略开发到实盘交易的完整流程:

1. **策略设计**: 明确市场假说、入场/出场条件、仓位管理
2. **数据准备**: 选择合适的数据源并进行预处理
3. **回测验证**: 使用Backtrader进行历史回测
4. **参数优化**: 网格搜索、遗传算法等方法
5. **风险控制**: 止损止盈、仓位管理、多层风控
6. **模拟交易**: 在接近实盘的环境中验证
7. **实盘部署**: 谨慎转入实盘交易
8. **持续监控**: 实时监控并持续改进

记住: 没有圣杯策略，关键在于持续学习和改进。

## 参考资料

- [Backtrader官方文档](https://www.backtrader.com/docu/)
- [CCXT文档](https://docs.ccxt.com/)
- [量化交易最佳实践](https://github.com/quantopian/zipline)

---

*最后更新: 2026-03-01*
