# 0966 DigitalF-T01

## 策略概述

该示例是 MT5 EA `Exp_DigitalF-T01` 的 Backtrader 迁移版本。

原 EA 基于 `DigitalF-T01` 数字滤波器与触发线交叉开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 按源码重建 24 项固定系数数字滤波器 `DigBuffer`
- 按源码使用信号周期内的参考 `close` 与 `halfchannel` 构造 `TriggerBuffer`
- 默认使用 `H3` 信号周期

## 交易逻辑

- 上一根 `digital > trigger` 且当前 `digital < trigger` 时做多并平空
- 上一根 `digital < trigger` 且当前 `digital > trigger` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_digitalf_t01.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
