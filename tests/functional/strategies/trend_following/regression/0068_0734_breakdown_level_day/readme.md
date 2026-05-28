# 0734 BreakdownLevelDay

## 策略概述

该策略是对 MT5 EA `0734_BreakdownLevelDay` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 在指定时间放置日内突破双向 stop 方案
- `BuyStop` 高于参考日最高价 `Delta`
- `SellStop` 低于参考日最低价 `Delta`
- 一侧触发后撤销另一侧
- 支持 `NoLoss` 与 `Trailing`

## 核心逻辑

1. 在 `time_set` 时刻读取日线高低点。
2. 以 `Delta` 偏移生成上下突破价。
3. 等待价格触发任一方向。
4. 进场后按固定 `SL/TP`、可选保本和可选 trailing 管理持仓。
5. 一旦已有持仓或其中一侧被触发，另一侧待触发方案失效。

## 主要参数

- `time_set`
- `delta`
- `sl`
- `tp`
- `risk`
- `lot`
- `no_loss`
- `trailing`

## 对齐说明

- 原 EA 用真实挂单；迁移版用 bar 内突破模拟 stop 触发。
- 原版允许按 `risk` 计算手数；迁移版沿用相同思路做近似重建。
- 原 EA 的图形矩形仅用于可视化，迁移版不复刻图形对象。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
