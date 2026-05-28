# 0726 ZeroLagEA-AIP v0.0.4

## 策略概述

该策略是对 MT5 EA `0726_ZeroLagEA-AIP_v0.0.4` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 使用 `ZeroLag MACD` 主线与信号线判断方向
- 仅在指定交易时段内开仓
- `UseFreshMACDSig=1` 时只接收刚发生的交叉
- 到达禁入时段或 `KillDay/KillHour` 强制清仓

## 指标重建说明

迁移版按零滞后 MACD 的常见实现重建：

- 对快慢 EMA 各做一次 EMA-of-EMA 修正
- 使用 `ZLEMA = 2 * EMA - EMA(EMA)`
- `MACD = ZLFast - ZLSlow`
- `signal` 用 `MACD` 的 EMA 近似

## 核心逻辑

1. 新 bar 到来时读取 `MACD` 与 `signal`。
2. `signal < macd` 视为多头方向，`signal > macd` 视为空头方向。
3. 若启用 `UseFreshMACDSig`，则必须是本 bar 新发生交叉。
4. 超出允许时段则不再开仓，并在限制时点清仓。

## 主要参数

- `fast_ema`
- `slow_ema`
- `use_fresh_macd_sig`
- `start_hour`
- `end_hour`
- `kill_day`
- `kill_hour`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
