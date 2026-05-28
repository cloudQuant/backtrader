# 0952 MACDCandle

## 策略概述

该示例是 MT5 EA `Exp_MACDCandle` 的 Backtrader 迁移版本。

原 EA 基于 `MACDCandle` 指标颜色切换开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失外部平滑库
- 对 `open/high/low/close` 四个价格序列分别计算 `MACD`
- 默认使用 `signal` 线生成 MACD 蜡烛
- 当 `open < close` 记为颜色 `2`，`open > close` 记为颜色 `0`，相等记为颜色 `1`
- 默认使用 `H4` 信号周期

## 交易逻辑

- 颜色切换到 `2` 时做多并平空
- 颜色切换到 `0` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_macdcandle.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
