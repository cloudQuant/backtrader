# 0712 up3x1_premium_v2M

## 策略概述

该策略是对 MT5 EA `0712_up3x1_premium_v2M` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 当前周期两条 EMA 交叉与 K 线结构判定
- 日线 EMA 提供额外过滤
- 单仓开平
- 亏损后按 `DecreaseFactor` 调整手数
- EMA 收敛离场 + trailing stop

## 核心逻辑

1. 读取当前周期两条 EMA 和日线 EMA。
2. 根据 EMA 交叉、实体较大的 K 线以及日线条件判断入场。
3. 开仓后使用固定 `SL/TP`。
4. 当两条 EMA 再次收敛时提前离场；盈利时启动 trailing。

## 迁移说明

- 原 EA 虽包含 `hedging only` 检查，但实际交易模型是单仓开平，不依赖锁仓结构。
- 迁移版保留其主要信号与持仓管理逻辑。

## 主要参数

- `maximum_risk`
- `decrease_factor`
- `take_profit`
- `stop_loss`
- `trailing_stop`
- `ma_period_one`
- `ma_period_two`
- `ma_period_day`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
