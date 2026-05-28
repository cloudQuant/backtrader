# 0756 GO

## 策略概述

该策略是对 MT5 EA `0756_GO` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 用四条不同价格源的 MA 生成单一方向值 `GO`
- `GO > 0` 时只保留/增加多头，`GO < 0` 时只保留/增加空头
- 若出现反向 `GO`，先平掉对侧持仓
- 同向仓位最多累加到 `MaxPositions`

## 核心逻辑

1. 分别对 `open/high/low/close` 计算同参数 MA。
2. 按原公式计算
   `GO=((close-open)+(high-open)+(low-open)+(close-low)+(close-high))*volume`。
3. 当 `GO < 0` 时先关闭所有多单；当 `GO > 0` 时先关闭所有空单。
4. 若当前 bar 尚未入场且仓位层数小于 `MaxPositions`，则按 `GO` 方向继续开同向仓。
5. 手数按原 EA 的 `LotsOptimized()` 近似：`balance * Risk / 100000`，资金不足时回退到可用资金近似。

## 主要参数

- `risk`
- `max_positions`
- `ma_method`
- `ma_period`

## 对齐说明

- 原 EA 说明里提到“仅在对冲账户交易”；当前 Backtrader 版本用同向分层仓位近似对冲账户下的多笔同向持仓。
- 原 EA 没有单笔 `SL/TP`，当前迁移也保持无固定止盈止损，只靠 `GO` 反向时清仓。
- 由于 Backtrader 是净头寸模型，层数通过策略内计数近似，而不是逐 ticket 独立管理。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
