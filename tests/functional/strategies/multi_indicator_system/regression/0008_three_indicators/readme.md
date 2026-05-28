# 0186 三个指标

## 策略概述

该样例是对 MT5 EA `0186_三个指标` 的 Backtrader 迁移版。
EA 在每根新 bar 到来时，分别计算 `candle`、`MACD`、`Stochastic`、`RSI` 四个离散信号，并将其组合成多空判断；若已有反向仓位，则先平仓并立即反手。

## 迁移思路

1. 使用统一的 `XAUUSD_M15` 数据进行验证
2. 保留源码中的 `work timeframe` 概念，在样例参数中单独配置
3. 复刻四个离散子信号：
   - `candle`: 当前工作周期的开盘价高于上一根开盘价记为 `1`，低于记为 `-1`
   - `MACD`: 主线相对上一根下降记为 `1`，上升记为 `-1`
   - `Stochastic`: 信号线低于 `50` 记为 `1`，高于 `50` 记为 `-1`
   - `RSI`: 指标值低于 `50` 记为 `1`，高于 `50` 记为 `-1`
4. 多头条件：四个子信号都不小于 `0`
5. 空头条件：四个子信号都不大于 `0`
6. 若已有反向仓位，则使用 `order_target_size` 近似源码中的“平仓后立即反手”

## 主要参数

- `work_timeframe`
- `lots`
- `macd_fast_period`
- `macd_slow_period`
- `macd_signal_period`
- `macd_applied_price`
- `sto_k_period`
- `sto_d_period`
- `sto_slowing`
- `sto_ma_method`
- `sto_price_field`
- `rsi_period`
- `rsi_applied_price`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 原 EA 默认 `work timeframe = M1`，但当前项目统一验证数据为 `XAUUSD_M15`，因此样例默认使用 `15min` 工作周期；如果后续补齐更细粒度数据，可再把 `work_timeframe` 切回 `1min`
- 源码在反向信号时先 `PositionClose`，再 `Sleep(30000)` 后开反向仓；当前 Backtrader 版本用一次 `order_target_size` 近似同 bar 反手
- 当前回测结果：`31` 笔成交，净收益 `-120997.00`，胜率 `45.16%`，Profit Factor `0.26`，最大回撤 `143.33%`
