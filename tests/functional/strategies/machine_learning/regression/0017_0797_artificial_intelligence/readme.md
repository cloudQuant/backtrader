# 0797 Artificial Intelligence

## 策略概述

该策略是对 MT5 EA `0797_人工智能(Artificial_Intelligence)` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，并在回测内重采样到 `M30`，保留了原 EA 的核心结构：

- 使用 `Acceleration/Deceleration Oscillator` 的多个滞后值构造固定权重感知器
- 感知器输出为正时做多，为负时做空
- 固定止损
- 盈利后移动止损
- 感知器翻转时反手

## 核心逻辑

1. 计算 `AC` 指标
2. 读取 `AC[0]`、`AC[7]`、`AC[14]`、`AC[21]`
3. 用 `(x1-100, x2-100, x3-100, x4-100)` 作为固定权重做线性组合
4. 当感知器输出大于 0 时做多，否则做空
5. 持仓盈利后，如果感知器翻转则反手，否则把止损推进到 `close -/+ stop_loss * point`

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `x1`
- `x2`
- `x3`
- `x4`
- `stop_loss`
- `lots`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M15.csv`

运行命令：

```bash
python run.py
```

如果需要绘图：

```bash
python run.py --plot
```

## 当前回测结果

当前参数下的回测结果：

- Trades: `70`
- Net P&L: `72,004.00`
- Win Rate: `52.86%`
- Profit Factor: `1.29`
- Max Drawdown: `58.35%`

## 对齐说明

- 原 EA 文档默认测试周期为 `M30`，当前版本通过 `XAUUSD M15` 重采样到 `M30` 近似实现
- 原 EA 所谓“人工智能”本质上是固定权重单层感知器，不依赖外部模型文件
- 原 EA 使用 `PositionCloseBy` 完成反手；当前版本在 Backtrader 净头寸模型下用平仓后反向开仓近似实现
