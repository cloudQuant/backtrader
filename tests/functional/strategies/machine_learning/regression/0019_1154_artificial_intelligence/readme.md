# 1154 ArtificialIntelligence

## 策略概述

该策略是对 MT5 EA `ArtificialIntelligence` 的 Backtrader 迁移版本。

原 EA 使用 `AC (Accelerator Oscillator)` 的 4 个不同滞后值作为输入，配合 4 个权重构成线性感知器；感知器输出大于 `0` 做多，小于 `0` 做空。

## 交易逻辑

- 读取 `AC[Shift]`、`AC[Shift+7]`、`AC[Shift+14]`、`AC[Shift+21]`
- 权重按 `xN - 100` 转换后与 4 个 `AC` 值相乘并求和
- 感知器输出 `perc > 0` 时做多，`perc < 0` 时做空
- 已持仓且浮盈超过阈值后：
  - 若出现反向信号，则按更大手数执行翻仓
  - 若未出现反向信号，则把止损推到开仓价

## 风控逻辑

- 开仓必须带固定 `StopLoss`
- 无固定 `TakeProfit`
- 盈利达到 `2 * StopLoss + spread` 近似阈值后，允许保本或翻仓

## 文件

- `strategy_artificial_intelligence.py` - 数据加载、AC 感知器与翻仓风控实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`stop_loss=850`、`shift=1`、`x1=135`、`x2=127`、`x3=16`、`x4=93`
- 信号次数：`0`
- 已平仓交易：`0`
- TradeAnalyzer 统计交易：`0`
- 胜率：`0.00%`
- 期初资金：`100000.00`
- 期末现金：`100000.00`
- 期末权益：`100000.00`
- 净收益：`0.00`
- 最大回撤：`0.00%`
- SQN：`0.00`

说明：本样本区间内未触发有效感知器入场信号，样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
