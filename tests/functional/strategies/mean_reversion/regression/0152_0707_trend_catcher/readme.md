# 0707 Trend_Catcher

## 策略概述

该策略是对 MT5 EA `0707_Trend_Catcher` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 三条 EMA 识别趋势方向
- `Parabolic SAR` 翻转给出入场触发
- 自动或固定 `SL/TP`
- break-even 与第二段 trailing
- 风险百分比手数与可选 martingale 放大

## 核心逻辑

1. `SAR` 翻转并与三均线方向一致时入场。
2. 若启用 `Reverse_Sig_Open`，则将方向反转。
3. `SL/TP` 可按 SAR 距离自动估算，也可固定值。
4. 盈利达到第一阈值后推到保本上方，再达到第二阈值后启动 trailing。

## 迁移说明

- 原 EA 使用 `MoneyFixedRisk.mqh` 进行风险手数计算；迁移版做了等价近似。
- 保留了核心趋势过滤、风险控制与 BE/Trailing 结构。

## 主要参数

- `period_ma_slow`
- `period_ma_fast`
- `period_ma_fast2`
- `step_sar`
- `max_sar`
- `auto_sl`
- `auto_tp`
- `risk`
- `martin`
- `koef`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
