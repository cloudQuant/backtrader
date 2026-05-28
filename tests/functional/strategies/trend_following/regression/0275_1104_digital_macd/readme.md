# 1104 Digital MACD

## 策略概述

该示例是对 MT5 EA `1104_Exp_Digital_MACD` 的 Backtrader 迁移版本。
当前版本沿用仓库标准验证数据 `XAUUSD_M15.csv`，复刻原始 EA 的四种信号模式：`breakdown`、`MACDtwist`、`SIGNALtwist`、`MACDdisposition`。

## 核心逻辑

1. 使用原始 `Digital_MACD` 指标中的快慢数字滤波器系数构造 `MACD` 主线
2. 对主线做默认 `SMA(5)` 平滑，得到信号线
3. `breakdown`：主线穿越零轴时触发信号
4. `MACDtwist`：主线方向由跌转升 / 由升转跌时触发信号
5. `SIGNALtwist`：信号线方向改变时触发信号
6. `MACDdisposition`：主线与信号线交叉时触发信号
7. 下单后附加固定 `SL / TP`，反向信号先平仓再反手

## 主要参数

- `mode`
- `signal_bar`
- `signal_period`
- `stop_loss_points`
- `take_profit_points`
- `lot`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 迁移说明

- 原始 MT5 指标支持多种信号线平滑方法，当前迁移版本优先复刻默认 `SMA(5)` 路径
- 快线与慢线不使用标准 `EMA MACD`，而是直接复用了 `digital_macd.mq5` 里的数字滤波系数
- 如果后续需要扩展 `Signal_Method` 的全部平滑方法，可以在当前实现上继续补齐
