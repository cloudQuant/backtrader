# 0995 i_Trend

## 策略概述

该示例是 MT5 EA `Exp_i_Trend` 的 Backtrader 迁移版本。

原 EA 基于 `i_Trend` 指标两条线的颜色切换/交叉进行交易。在柱线收盘时，如果主线与信号线关系翻转，则生成开平仓信号。

## 指标重建

- `primary = selected_price - Bollinger(selected_band)`
- `signal = 2 * MA - high - low`
- 当 `primary` 与 `signal` 在已完成柱上发生交叉时触发交易
- 默认使用 `H4` 信号周期

## 交易逻辑

- 前一根已完成柱 `primary > signal`，最近一根已完成柱 `primary <= signal` 时做多并平空
- 前一根已完成柱 `primary < signal`，最近一根已完成柱 `primary >= signal` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_i_trend.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
