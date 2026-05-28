# 0983 KalmanFilter

## 策略概述

该示例是 MT5 EA `Exp_KalmanFilter` 的 Backtrader 迁移版本。

原 EA 基于 `KalmanFilter` 指标颜色变化开平仓：颜色由 `Kalman` 速度符号或 `Trend` 斜率模式给出，默认使用 `Kalman` 模式，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，自带 `PriceSeries` 价格分支函数，不依赖缺失的 `SmoothAlgorithms.mqh`
- 核心递推保持原式：`distance = price - prev`、`error = prev + distance * sqrt(k / 100)`、`velocity += distance * k / 100`
- 主线输出为 `error + velocity + price_shift`
- 颜色缓冲区在 `Trend` 模式下按主线斜率着色，在 `Kalman` 模式下按速度正负着色
- 默认使用 `H3` 信号周期

## 交易逻辑

- 若上一根颜色为 `0` 且当前颜色变为 `1`，则做多并平空
- 若上一根颜色为 `1` 且当前颜色变为 `0`，则做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_kalmanfilter.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
