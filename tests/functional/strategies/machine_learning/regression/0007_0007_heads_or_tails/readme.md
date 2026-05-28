# 0007 Heads or Tails

## 策略概述

该策略是对 MT5 EA `0007_交易策略正面或反面_(Heads_or_Tails)` 的 backtrader 迁移版本。
它本质上是一个随机入场实验策略：

- 无持仓时随机决定开多或开空
- 使用固定止损和固定止盈
- 不依赖技术指标

## 核心逻辑

1. 当没有持仓时，使用伪随机数在多/空之间二选一
2. 按固定手数开仓
3. 开仓后设置固定止损与固定止盈
4. 平仓后继续下一轮随机方向选择

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `iLots`
- `iTakeProfit`
- `iStopLoss`
- `random_seed`
- `point`
- `price_digits`
- `volume_step`
- `volume_min`
- `volume_max`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M5.csv`

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 当前版本保留了“无信号分析、仅随机方向开仓”的原始实验逻辑
- 为了保证可复现性，使用 `random_seed` 固定随机序列
- 需注意：原 EA 的默认手数归整公式在 `iLots=0.01` 且 `volume_step=0.01` 时会得到有效手数 `0.0`
- 因此当前默认配置下，策略可以运行，但不会实际开仓；这与原始公式行为保持一致
