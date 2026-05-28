# 0946 ColorMETRO Stochastic

## 策略概述

该示例是 MT5 EA `Exp_ColorMETRO_Stochastic` 的 Backtrader 迁移版本。

原 EA 基于 `ColorMETRO_Stochastic` 快慢云层颜色切换开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 使用 `Stochastic` 的慢线 `%D` 作为基础序列
- 按源码保留快慢 `StepSize` 步进带递推逻辑
- 由 `fast_line` 与 `slow_line` 的相对位置表示云层方向
- 默认使用 `H8` 信号周期

## 交易逻辑

- `fast_line` 上穿 `slow_line` 时做多并平空
- `fast_line` 下穿 `slow_line` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_colormetro_stochastic.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
