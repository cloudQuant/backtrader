- --

title: CS (横截面) 模式指南
description: 多资产组合优化与横截面向量化

- --

# CS (横截面) 模式指南

CS (Cross-Section) 模式是专为多资产组合回测设计的性能优化功能。它通过在每个时间点同时处理多个资产,实现高效的横截面信号生成和组合优化。

## 什么是 CS 模式?

CS 模式通过**横截面向量化**实现组合级别的回测优化。与专注于单资产历史数据处理的 TS (时间序列) 模式不同,CS 模式专注于:

- **多资产比较**- 在每个时间点横向比较
- **横截面排名**和信号生成
- **多证券组合优化**
- **因子策略** (多因子选股等)

### 工作原理

在标准 backtrader 模式下处理多个数据源:

```python

# 标准模式: 顺序处理每个数据源

for data in datas:
    indicator.calculate(data)
    strategy.next(data)

```bash
在 CS 模式下,数据进行横截面处理:

```python

# CS 模式: 在每个时间点处理所有资产

for t in time:
    cross_section = get_all_assets_at_time(t)
    signals = calculate_cross_sectional_signals(cross_section)
    portfolio.rebalance(signals)

```bash

## 性能优势

| 操作 | 标准模式 | CS 模式 | 加速比 |

|------|----------|---------|--------|

| 10 资产排名 | 1x | 2-3x | 快 2-3 倍 |

| 50 资产因子评分 | 1x | 3-5x | 快 3-5 倍 |

| 100 资产组合调仓 | 1x | 5-8x | 快 5-8 倍 |

| 因子计算 (500 资产) | 基准 | 8-12x | 快 8-12 倍 |

- 实际性能取决于资产数量和策略复杂度*

## 何时使用 CS 模式

### 理想使用场景

1. **多资产组合**: 10 只以上证券的投资组合
2. **因子策略**: 动量、价值、质量因子
3. **排名/选股策略**: Top N / Bottom N 选择
4. **组合调仓**: 基于横截面信号的定期调仓
5. **配对交易**: 跨资产统计套利

### 不适合使用 CS 模式的场景

1. **单资产策略**: 只交易一只证券
2. **纯时间序列策略**: 不比较资产的策略
3. **高频交易**: 逐 tick 策略 (使用 tick 模式)
4. **复杂状态策略**: 每个资产有复杂独立状态

## 启用 CS 模式

### 方法 1: cerebro.run() 参数

```python
import backtrader as bt

cerebro = bt.Cerebro()

# 添加多个数据源

for symbol in ['AAPL', 'MSFT', 'GOOGL', ...]:
    data = bt.feeds.PandasData(dataname=load_data(symbol))
    cerebro.adddata(data, name=symbol)

cerebro.addstrategy(MultiAssetStrategy)

# 启用 CS 模式

cerebro.run(cs_mode=True)

```bash

### 方法 2: 环境变量

```bash

# 运行前设置环境变量

export BACKTRADER_CS_MODE=1

python my_portfolio_backtest.py

```bash

### 方法 3: 配置文件

```python

# backtrader_config.py

cs_mode = {
    'enabled': True,
    'use_cython': True,
}

```bash

## 代码示例

### 示例 1: 简单横截面排名

```python
import backtrader as bt
import pandas as pd

class CrossSectionalRanking(bt.Strategy):
    """按动量排名资产并交易表现最佳的资产。"""

    params = (
        ('lookback', 20),
        ('top_n', 5),
        ('rebalance_freq', 20),  # 每 20 根 K 线调仓
    )

    def __init__(self):
        self.counter = 0
        self.momentum_dict = {}

# 为每个资产计算动量 (跳过第一个数据如果是指数)
        for data in self.datas[1:]:

# 简单动量: 回溯期内的价格变化
            momentum = (data.close - data.close(-self.p.lookback)) / data.close(-self.p.lookback)
            self.momentum_dict[data._name] = momentum

    def next(self):
        self.counter += 1

# 仅定期调仓
        if self.counter % self.p.rebalance_freq != 0:
            return

# 获取所有资产的当前动量
        current_momentums = []
        for name, momentum_line in self.momentum_dict.items():
            if len(momentum_line) > 0:
                mom_value = momentum_line[0]
                if not pd.isna(mom_value):
                    current_momentums.append((name, mom_value))

# 按动量排序 (降序)
        current_momentums.sort(key=lambda x: x[1], reverse=True)

# 选择前 N 个
        top_assets = current_momentums[:self.p.top_n]

# 平掉所有现有仓位
        for data in self.datas[1:]:
            if self.getposition(data).size > 0:
                self.close(data)

# 在表现最佳的资产中开仓
        if top_assets:
            weight = 1.0 / len(top_assets)
            for name, _ in top_assets:
                data = self.getdatabyname(name)
                if len(data) > 0:
                    value = self.broker.getvalue() *weight
                    size = value / data.close[0]
                    self.buy(data=data, size=size)

# 加载多个资产

cerebro = bt.Cerebro()

# 首先添加指数数据 (用于日期对齐)

index_data = load_index_data()
cerebro.adddata(bt.feeds.PandasData(dataname=index_data), name='index')

# 添加资产数据

symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA', ...]
for symbol in symbols:
    df = pd.read_csv(f'{symbol}.csv', parse_dates=['datetime'], index_col='datetime')
    cerebro.adddata(bt.feeds.PandasData(dataname=df), name=symbol)

cerebro.addstrategy(CrossSectionalRanking, lookback=20, top_n=5)
cerebro.broker.setcash(1000000)

# 使用 CS 模式运行

result = cerebro.run(cs_mode=True)

```bash

### 示例 2: 多因子选股策略

```python
import backtrader as bt
import pandas as pd

class MultiFactorStrategy(bt.Strategy):
    """多因子策略与横截面排名。

    组合多个因子 (价值、动量、质量) 成为一个综合得分用于选股。
    """

    params = (
        ('value_weight', 0.4),
        ('momentum_weight', 0.3),
        ('quality_weight', 0.3),
        ('top_percent', 0.2),  # 前 20% 股票
        ('rebalance_monthly', True),
    )

    def __init__(self):
        self.last_month = None

# 存储每只股票的因子数据
        self.factors = {}
        for data in self.datas[1:]:  # 跳过指数
            self.factors[data._name] = {
                'data': data,
                'pe': data.close / (data.volume + 1),  # 简化的 PE 代理
                'momentum': (data.close - data.close(-20)) / data.close(-20),
                'volatility': bt.indicators.StandardDeviation(
                    data.close, period=20
                ) / data.close,
            }

    def next(self):
        current_date = self.datas[0].datetime.date(0)
        current_month = current_date.month

# 月度调仓检查
        if self.p.rebalance_monthly:
            if current_month == self.last_month:
                return
            self.last_month = current_month

# 计算横截面得分
        scores = []
        for name, factors in self.factors.items():
            if len(factors['data']) < 20:
                continue

# 获取因子值
            pe = factors['pe'][0]
            momentum = factors['momentum'][0]
            volatility = -factors['volatility'][0]  # 低波动更好

# 跳过无效值
            if pd.isna(pe) or pd.isna(momentum) or pd.isna(volatility):
                continue

# 计算综合得分
            score = (
                self.p.value_weight*(-pe if pe > 0 else 0) +  # 低 PE 更好
                self.p.momentum_weight*momentum +
                self.p.quality_weight*volatility
            )
            scores.append((name, score))

        if not scores:
            return

# 股票排名
        scores.sort(key=lambda x: x[1], reverse=True)

# 选择前百分位
        n_stocks = max(1, int(len(scores)*self.p.top_percent))
        selected = scores[:n_stocks]

# 组合调仓
        self._rebalance(selected)

    def _rebalance(self, selected_stocks):
        """调仓组合至等权重选中的股票。"""

# 平掉所有仓位
        for data in self.datas[1:]:
            if self.getposition(data).size > 0:
                self.close(data)

# 开新仓
        if selected_stocks:
            weight = 1.0 / len(selected_stocks)
            for name, score in selected_stocks:
                data = self.getdatabyname(name)
                value = self.broker.getvalue()*weight
                size = value / data.close[0]
                self.buy(data=data, size=size)

# 使用

cerebro = bt.Cerebro()
cerebro.broker.setcash(10000000)

# 添加数据源...

cerebro.addstrategy(MultiFactorStrategy)
result = cerebro.run(cs_mode=True)

```bash

### 示例 3: 可转债双低策略

```python
import backtrader as bt
import pandas as pd

class DoubleLowStrategy(bt.Strategy):
    """可转债双低策略。

    选择价格最低和转股溢价率最低的转债。
    这是一个经典的横截面策略。
    """

    params = (
        ('price_weight', 0.5),
        ('premium_weight', 0.5),
        ('hold_percent', 20),  # 持有前 20% 转债
    )

    def __init__(self):
        self.position_dict = {}
        self.stock_dict = {}

    def next(self):

# 跟踪可交易转债
        current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")
        self.stock_dict = {}

        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            if current_date == data_date:
                self.stock_dict[data._name] = 1

# 月度调仓
        pre_date = self.datas[0].datetime.date(-1).strftime("%Y-%m-%d")
        current_month = current_date[5:7]

        try:
            next_date = self.datas[0].datetime.date(1).strftime("%Y-%m-%d")
            next_month = next_date[5:7]
        except IndexError:
            next_month = current_month

        if current_month != next_month:

# 平掉现有仓位
            for name in list(self.position_dict.keys()):
                data = self.getdatabyname(name)
                if self.getposition(data).size > 0:
                    self.close(data)
                self.position_dict.pop(name, None)

# 计算横截面得分
            result = self._get_target_symbols()

# 开新仓
            if result:
                total_value = self.broker.getvalue()
                weight = 1.0 / len(result)

                for name, score in result:
                    data = self.getdatabyname(name)
                    value = total_value*weight
                    size = value / data.close[0]
                    order = self.buy(data=data, size=size)
                    self.position_dict[name] = order

    def _get_target_symbols(self):
        """使用横截面排名计算目标转债。"""
        data_name_list = []
        close_list = []
        premium_list = []

# 收集所有可交易转债的数据
        for asset in sorted(self.stock_dict):
            data = self.getdatabyname(asset)
            data_name_list.append(data._name)
            close_list.append(data.close[0])
            premium_list.append(data.convert_premium_rate[0])

# 创建 DataFrame 用于横截面分析
        df = pd.DataFrame({
            'data_name': data_name_list,
            'close': close_list,
            'premium': premium_list,
        })

# 横截面排名
        df['close_score'] = df['close'].rank(method='average')  # 低更好
        df['premium_score'] = df['premium'].rank(method='average')  # 低更好

# 综合得分
        df['total_score'] = (
            df['close_score']*self.p.price_weight +
            df['premium_score']*self.p.premium_weight
        )

# 按得分排序 (降序 - 更高得分意味着更低排名)
        df = df.sort_values(by=['total_score', 'data_name'],
                           ascending=[False, True])

# 选择前 N 个
        if self.p.hold_percent > 1:
            num = self.p.hold_percent
        else:
            num = int(self.p.hold_percent* len(df))

        result = [[row['data_name'], row['total_score']]
                  for _, row in df.head(num).iterrows()]

        return result

# 使用

cerebro = bt.Cerebro()
cerebro.broker.setcash(100000000)

# 添加指数和转债数据...

cerebro.addstrategy(DoubleLowStrategy)
result = cerebro.run(cs_mode=True)

```bash

## CS 模式 vs TS 模式

| 特性 | TS 模式 | CS 模式 |

|------|---------|---------|

| **目的**| 时间序列向量化 | 横截面优化 |

|**用例**| 单资产长历史 | 多资产组合 |

|**数据结构**| 2D (时间 x 特征) | 3D (时间 x 资产 x 特征) |

|**典型加速**| 3-5x | 2-3x |

|**内存使用**| 中等 | 较高 |

|**最适合**| 指标计算 | 组合优化 |

|**示例策略** | 均线交叉、趋势跟踪 | 因子投资、排名策略 |

## 性能基准

### 基准配置

| 参数 | 值 |

|------|-----|

| 资产数量 | 100 只股票 |

| 时间范围 | 5 年 (1250 个交易日) |

| 因子 | 动量、价值、质量 |

| 策略 | 月度调仓 |

| 硬件 | M1 Pro, 16GB RAM |

### 结果

| 模式 | 执行时间 | 资产/秒 |

|------|----------|---------|

| 标准模式 | 45.2s | 2,765 |

| CS 模式 (Python) | 18.5s | 6,756 |

| CS 模式 (Cython) | 12.3s | 10,162 |

### 基准测试你的策略

```python
import time
import backtrader as bt

# 标准模式

start = time.time()
result_standard = cerebro.run()
standard_time = time.time() - start

# CS 模式

start = time.time()
result_cs = cerebro.run(cs_mode=True)
cs_time = time.time() - start

print(f"标准模式: {standard_time:.2f}秒")
print(f"CS 模式: {cs_time:.2f}秒")
print(f"加速: {standard_time/cs_time:.2f}倍")

```bash

## 横截面信号生成

### 因子计算模式

```python
def calculate_cross_sectional_signals(self):
    """在当前时间点计算所有资产的信号。"""

# 模式 1: 简单排名
    signals = []
    for data in self.datas[1:]:
        score = self._calculate_factor_score(data)
        signals.append((data._name, score))

    signals.sort(key=lambda x: x[1], reverse=True)

# 模式 2: Z-score 标准化
    scores = [s[1] for s in signals]
    mean_score = sum(scores) / len(scores)
    std_score = (sum((s - mean_score)**2 for s in scores) / len(scores))**0.5

    normalized = [(name, (score - mean_score) / std_score)
                  for name, score in signals]

# 模式 3: 百分位排名
    sorted_scores = sorted(scores)
    percentile_signals = [
        (name, sorted_scores.index(score) / len(scores))
        for name, score in signals
    ]

    return percentile_signals

```bash

### 行业中性化

```python
def industry_neutralize(self, signals):
    """调整信号使其行业中性。"""

# 按行业分组 (假设数据有行业字段)
    industry_groups = {}
    for name, signal in signals:
        industry = self.getdatabyname(name).industry[0]
        if industry not in industry_groups:
            industry_groups[industry] = []
        industry_groups[industry].append((name, signal))

# 计算行业调整后的信号
    neutral_signals = []
    for industry, group in industry_groups.items():
        industry_mean = sum(s[1] for s in group) / len(group)
        for name, signal in group:
            neutral_signals.append((name, signal - industry_mean))

    return neutral_signals

```bash

## 限制和注意事项

### 1. 数据对齐

所有数据源必须正确对齐:

```python

# 好: 使用指数数据进行对齐

index_data = load_index_data()
cerebro.adddata(bt.feeds.PandasData(dataname=index_data), name='index')

for symbol in symbols:
    data = load_symbol_data(symbol)

# 确保所有数据具有相同的日期时间索引
    data = data.reindex(index_data.index)
    cerebro.adddata(bt.feeds.PandasData(dataname=data), name=symbol)

```bash

### 2. 缺失数据处理

```python
def next(self):

# 过滤数据不足的资产
    valid_assets = []
    for data in self.datas[1:]:

# 检查最小数据长度
        if len(data) < self.p.min_period:
            continue

# 检查 NaN 值
        if pd.isna(data.close[0]):
            continue
        valid_assets.append(data)

# 仅使用有效资产继续
    self._calculate_signals(valid_assets)

```bash

### 3. 内存使用

多资产的 CS 模式可能占用大量内存:

```python

# 控制内存使用

max_assets = 500  # 限制资产数量

min_history = 252  # 最少 1 年历史

# 添加前过滤资产

for symbol in symbols:
    df = load_data(symbol)
    if len(df) >= min_history:
        cerebro.adddata(bt.feeds.PandasData(dataname=df), name=symbol)
        if len(cerebro.datas) >= max_assets:
            break

```bash

### 4. 调仓频率

```python

# 日度调仓 (昂贵, 高换手率)

if self.counter % 1 == 0:
    self.rebalance()

# 周度调仓 (平衡)

if self.counter % 5 == 0:
    self.rebalance()

# 月度调仓 (因子策略常用)

if self._is_month_end():
    self.rebalance()

```bash

## 高级配置

### 微调 CS 模式

```python
cerebro.run(
    cs_mode=True,           # 启用 CS 模式
    cs_batch_size=1000,     # 批量处理 (可选)
    runonce=True,           # 使用 once() 方法
    preload=True,           # 预加载所有数据

)

```bash

### CS 模式与优化结合

```python

# 使用 CS 模式优化策略参数

cerebro.optstrategy(
    MultiFactorStrategy,
    value_weight=[0.2, 0.4, 0.6],
    momentum_weight=[0.2, 0.4, 0.6],
)

# 使用 CS 模式运行优化

results = cerebro.run(cs_mode=True, maxcpu=4)

```bash

## 最佳实践

1. **始终使用指数数据**进行日期对齐:

   ```python

# 第一个数据应该是指数/参考
   cerebro.adddata(index_feed, name='index')
   ```

2.**优雅地处理缺失数据**:

   ```python
   if pd.isna(data.close[0]) or len(data) < min_period:
       continue
   ```

1. **使用高效的数据结构** 进行横截面分析:

   ```python

# 使用 pandas DataFrame 进行高效操作
   df = pd.DataFrame({
       'name': names,
       'factor1': values1,
       'factor2': values2,
   })
   df['score'] = df['factor1'] *w1 + df['factor2']* w2
   ```

1. **优化前先分析性能**:

   ```python

# 验证 CS 模式确实对您的特定策略有帮助
   ```

1. **考虑交易成本**:

   ```python

# 高换手率策略在扣除成本后可能表现不佳
   cerebro.broker.setcommission(commission=0.001)
   ```

## 故障排除

### 问题: 结果与标准模式不同

如果结果不同:

1. **检查数据对齐**:

   ```python

# 确保所有数据源具有相同的日期时间索引
   ```

1. **验证因子计算**:

   ```python

# 打印中间值进行调试
   print(f"因子值: {factor_values}")
   ```

1. **检查排名逻辑**:

   ```python

# 验证排名稳定
   ```

### 问题: 没有性能提升

1. **验证 CS 模式已启用**:

   ```python
   print(f"CS 模式激活: {cerebro.p.cs_mode}")
   ```

1. **检查资产数量**:

   ```python

# CS 模式在 10+ 资产时表现最佳
   print(f"资产数量: {len(cerebro.datas)}")
   ```

1. **使用 Cython 扩展**:

   ```bash
   cd backtrader && python -W ignore compile_cython_numba_files.py
   ```

## 下一步

- [TS 模式指南](ts-mode.md) - 时间序列优化
- [性能优化](performance-optimization.md) - 通用优化技术
- [多策略指南](multi-strategy.md) - 运行多个策略
- [策略 API](/api/strategy.md) - 策略开发
