# 可转债双低因子多品种策略

## 策略简介

本策略采用"双低"选股思路，结合可转债的价格和转股溢价率两个因子进行综合评分。每月定期调仓，选择综合得分最优（价格低、溢价率低）的多个可转债进行等权重配置，实现分散投资。

## 策略原理

### 核心思想

双低策略是可转债市场经典的投资策略，核心思想是选择"价格低"和"溢价率低"的可转债：
- **价格低**：可转债价格越接近面值，下行空间有限，安全边际高
- **溢价率低**：转股溢价率越低，可转债跟随正股上涨的能力越强

### 因子计算

1. **价格因子得分**：按可转债价格从低到高排序，排名越靠前得分越高
2. **溢价率因子得分**：按转股溢价率从低到高排序，排名越靠前得分越高
3. **综合得分** = 价格因子得分 × 权重1 + 溢价率因子得分 × 权重2

### 调仓规则

1. **调仓频率**：每月第一个交易日调仓
2. **持仓数量**：可选择固定数量或按比例选择
3. **权重配置**：等权重配置每个选中的可转债
4. **数据对齐**：使用指数数据作为时间对齐基准

### 策略参数

| 参数名 | 类型 | 默认值 | 说明 |
|-------|-----|--------|------|
| first_factor_weight | float | 0.5 | 价格因子权重（0-1） |
| second_factor_weight | float | 0.5 | 溢价率因子权重（0-1） |
| hold_percent | int | 20 | 持有数量（>1）或百分比（<=1） |

## 适用场景

1. **市场环境**：适合可转债市场整体估值偏高的时期
2. **品种选择**：适用于流动性较好的主流可转债
3. **时间周期**：月度调仓，中长期持有策略
4. **风险偏好**：中等风险偏好，追求稳健收益

## 风险提示

1. **集中度风险**：等权重配置可能过于分散或过于集中
2. **调仓成本**：月度调仓产生较高的交易成本
3. **因子失效**：市场风格变化时双低因子可能失效
4. **流动性风险**：部分可转债流动性不足可能影响交易执行
5. **信用风险**：未考虑发行人信用状况

## 回测示例

```python
import backtrader as bt

# 加载策略
from strategies.multi_extend_data.strategy import BondConvertTwoFactor, ExtendPandasFeed

cerebro = bt.Cerebro()

# 加载指数数据（用于时间对齐）
index_data = load_index_data('bond_index_000000.csv')
index_feed = ExtendPandasFeed(dataname=index_data)
cerebro.adddata(index_feed, name="000000")

# 加载多个可转债数据
bonds = load_bond_data('bond_merged_all_data.csv')
for symbol, data in bonds.items():
    feed = ExtendPandasFeed(dataname=data)
    cerebro.adddata(feed, name=symbol)

# 添加策略
cerebro.addstrategy(BondConvertTwoFactor,
                    first_factor_weight=0.5,
                    second_factor_weight=0.5,
                    hold_percent=20)

# 运行回测
results = cerebro.run()
```

## 参考资料

1. 可转债双低策略原理
2. 因子投资基础理论
3. 多资产组合管理
