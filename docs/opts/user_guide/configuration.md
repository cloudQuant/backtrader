# 回测配置指南

本指南详细介绍如何配置 Backtrader 的回测环境，包括经纪商设置、交易成本、数据处理等。

## 基本配置

### 1. Cerebro 配置

```python
# 创建回测引擎
cerebro = bt.Cerebro(
    stdstats=True,          # 是否显示标准统计指标
    oldbuysell=False,       # 是否使用旧版买卖信号显示
    oldtrades=False,        # 是否使用旧版交易显示
    exactbars=False,        # 是否使用精确的bar计数
    optreturn=True,         # 优化模式下是否返回策略实例
    optdatas=True,          # 优化模式下是否优化数据预加载
    preload=True,          # 是否预加载数据
    runonce=True,          # 是否一次性运行所有数据
    maxcpus=None,          # 最大CPU核心数
    writer=False,          # 是否启用交易记录器
    tradehistory=False,    # 是否记录详细交易历史
    oldsync=False,         # 是否使用旧版数据同步
    tz=None,              # 时区设置
    cheat_on_open=False,  # 是否在开盘时作弊
)
```

### 2. 经纪商配置

```python
# 设置经纪商
cerebro.broker.setcash(100000.0)  # 设置初始资金
cerebro.broker.setcommission(commission=0.001)  # 设置佣金
cerebro.broker.set_slippage_perc(0.001)  # 设置滑点

# 详细佣金设置
cerebro.broker.setcommission(
    commission=0.001,     # 佣金率
    margin=2000,          # 保证金要求
    mult=10,              # 合约乘数
    commtype=bt.CommInfoBase.COMM_PERC,  # 佣金类型（百分比）
    percabs=True,         # 是否使用绝对百分比
    leverage=1.0,         # 杠杆率
)
```

### 3. 数据配置

```python
# 数据预处理设置
data = bt.feeds.PandasData(
    dataname=df,
    fromdate=datetime.datetime(2020, 1, 1),
    todate=datetime.datetime(2023, 12, 31),
    timeframe=bt.TimeFrame.Days,
    compression=1,
    sessionstart=datetime.time(9, 30),
    sessionend=datetime.time(15, 0),
    tz=pytz.timezone('Asia/Shanghai'),
)

# 数据重采样
cerebro.resampledata(
    data,
    timeframe=bt.TimeFrame.Weeks,
    compression=1,
    bar2edge=True,
    adjbartime=True,
    rightedge=True,
)
```

## 高级配置

### 1. 订单类型配置

```python
# 设置订单有效期
cerebro.broker.set_ordertimeout(ordertimeout=None)  # None表示永不过期

# 设置订单类型
cerebro.broker.set_ordertype(ordertype=bt.Order.Market)  # 市价单
cerebro.broker.set_ordertype(ordertype=bt.Order.Limit)   # 限价单
cerebro.broker.set_ordertype(ordertype=bt.Order.Stop)    # 止损单
cerebro.broker.set_ordertype(ordertype=bt.Order.StopLimit)  # 止损限价单
```

### 2. 风险控制配置

```python
# 设置风险控制参数
class RiskManager(bt.Sizer):
    params = (
        ('risk_perc', 0.02),  # 每笔交易风险比例
        ('max_pos', 5),       # 最大持仓数量
    )
    
    def _getsizing(self, comminfo, cash, data, isbuy):
        if len(self.strategy.positions) >= self.p.max_pos:
            return 0
            
        risk_amount = cash * self.p.risk_perc
        price = data.close[0]
        size = risk_amount / price
        
        return int(size)

# 添加风险管理器
cerebro.addsizer(RiskManager)
```

### 3. 性能优化配置

```python
# 启用多核处理
cerebro.run(
    maxcpus=4,           # 使用4个CPU核心
    optreturn=False,     # 不返回策略实例
    optdatas=True,       # 优化数据预加载
    preload=True,        # 预加载数据
    runonce=True,        # 一次性运行
)

# 内存优化
class MemoryOptimizedStrategy(bt.Strategy):
    params = (('lookback', 20),)
    
    def __init__(self):
        self.data_close = self.data.close
        self.sma = bt.indicators.SMA(period=self.p.lookback)
        
    def next(self):
        if len(self.data) > self.p.lookback:
            # 使用缓存的数据
            if self.data_close[0] > self.sma[0]:
                self.buy()
```

### 4. 日志配置

```python
import logging

# 配置日志
logging.basicConfig(
    filename='backtest.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class LoggedStrategy(bt.Strategy):
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        
    def next(self):
        self.logger.info(f'当前价格: {self.data.close[0]}')
        
    def notify_order(self, order):
        if order.status == order.Completed:
            self.logger.info(
                f'订单执行: {order.executed.price}, 数量: {order.executed.size}'
            )
```

## 自定义配置

### 1. 自定义经纪商

```python
class CustomBroker(bt.brokers.BackBroker):
    params = (
        ('commission', 0.001),
        ('slip_perc', 0.001),
        ('slip_fixed', 0.00),
        ('slip_open', False),
        ('slip_match', True),
        ('slip_limit', True),
        ('slip_out', False),
    )
    
    def __init__(self):
        super(CustomBroker, self).__init__()
        
    def _slip_price(self, price, slip):
        if not self.p.slip_match:
            return price
            
        if self.p.slip_limit and isinstance(slip, float):
            return price * (1.0 + slip)
            
        return price + slip
```

### 2. 自定义数据源配置

```python
class CustomDataFeed(bt.feeds.GenericCSVData):
    params = (
        ('dtformat', '%Y-%m-%d'),
        ('tmformat', '%H:%M:%S'),
        ('datetime', 0),
        ('time', -1),
        ('open', 1),
        ('high', 2),
        ('low', 3),
        ('close', 4),
        ('volume', 5),
        ('openinterest', -1),
        ('reverse', False),
    )
    
    def _loadline(self, linetokens):
        # 自定义数据加载逻辑
        return super(CustomDataFeed, self)._loadline(linetokens)
```

### 3. 自定义指标配置

```python
class CustomIndicator(bt.Indicator):
    params = (
        ('period', 20),
        ('movav', bt.indicators.MovAv.Simple),
        ('subplot', True),
        ('plotname', None),
        ('plotabove', False),
        ('plotlinelabels', True),
        ('plotforce', False),
        ('plotmaster', None),
    )
    
    plotinfo = dict(
        plot=True,
        subplot=True,
        plotname='Custom Indicator'
    )
    
    plotlines = dict(
        line=dict(
            _name='CustomLine',
            color='blue',
            ls='-',
            width=1.0
        )
    )
```

## 环境配置

### 1. 回测环境

```python
# 设置回测环境
class BacktestEnv:
    def __init__(self):
        self.cerebro = bt.Cerebro()
        self._configure_broker()
        self._configure_data()
        self._configure_analyzers()
        
    def _configure_broker(self):
        self.cerebro.broker.setcash(100000.0)
        self.cerebro.broker.setcommission(commission=0.001)
        
    def _configure_data(self):
        self.data = bt.feeds.YahooFinanceData(
            dataname='AAPL',
            fromdate=datetime.datetime(2020, 1, 1),
            todate=datetime.datetime(2023, 12, 31)
        )
        self.cerebro.adddata(self.data)
        
    def _configure_analyzers(self):
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio)
        self.cerebro.addanalyzer(bt.analyzers.DrawDown)
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer)
```

### 2. 实盘环境

```python
# 设置实盘环境
class LiveEnv:
    def __init__(self):
        self.cerebro = bt.Cerebro()
        self._configure_live_broker()
        self._configure_live_data()
        self._configure_risk_management()
        
    def _configure_live_broker(self):
        self.broker = CustomBroker()
        self.cerebro.setbroker(self.broker)
        
    def _configure_live_data(self):
        self.data = CustomDataFeed()
        self.cerebro.adddata(self.data)
        
    def _configure_risk_management(self):
        self.cerebro.addsizer(RiskManager)
```

## 最佳实践

### 1. 配置检查

```python
def validate_config(cerebro):
    """验证配置是否合理"""
    # 检查资金设置
    if cerebro.broker.getcash() < 10000:
        raise ValueError("初始资金过低")
        
    # 检查佣金设置
    if cerebro.broker.getcommissioninfo(None).commission > 0.01:
        raise ValueError("佣金设置过高")
        
    # 检查数据设置
    for data in cerebro.datas:
        if data.params.timeframe < bt.TimeFrame.Minutes:
            raise ValueError("时间周期过小")
```

### 2. 性能优化

```python
def optimize_performance(cerebro):
    """优化回测性能"""
    # 启用预加载
    cerebro.preload(True)
    
    # 启用一次性运行
    cerebro.runonce(True)
    
    # 设置最大CPU核心数
    cerebro.maxcpus = multiprocessing.cpu_count() - 1
```

### 3. 错误处理

```python
def safe_run(cerebro):
    """安全运行回测"""
    try:
        validate_config(cerebro)
        optimize_performance(cerebro)
        results = cerebro.run()
        return results
    except Exception as e:
        logging.error(f"回测运行错误: {e}")
        return None
```

## 常见问题

1. **内存使用过高**
   - 减少数据预加载
   - 使用数据过滤
   - 优化指标计算

2. **回测速度慢**
   - 启用多核处理
   - 减少数据频率
   - 优化策略逻辑

3. **配置冲突**
   - 检查参数兼容性
   - 验证数据同步
   - 确认订单设置

## 下一步

- 学习[策略开发](./strategies.md)
- 了解[数据处理](./data_feeds.md)
- 探索[指标系统](./indicators.md)
- 研究[参数优化](./optimization.md)
