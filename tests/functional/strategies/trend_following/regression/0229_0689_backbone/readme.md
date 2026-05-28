# 0689 骨干

## 策略概述

该策略是对 MT5 EA `0689_骨干` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 先根据价格相对近期极值的回撤/反弹，判定首个方向
- 随后按同方向逐层加仓，最多到 `ntmax`
- 每层都维护固定 `SL/TP`
- 盈利后对各层止损做 trailing 推进

## 核心逻辑

1. 当系统尚未持仓时，持续跟踪 `BidMax / AskMin`。
2. 若价格自高点回撤超过 `TrailingStop`，则把首个方向定为做空；若价格自低点反弹超过 `TrailingStop`，则把首个方向定为做多。
3. 首层开仓后，后续在同方向上继续分层加仓，直到达到 `ntmax`。
4. 每层用 `MaxRisk`、当前已开层数与 `StopLoss` 估算下一层的风险仓位。
5. 每层独立检查 `SL/TP`，并在浮盈时按 trailing 方式抬升/下压止损。

## 主要参数

- `max_risk`
- `ntmax`
- `take_profit`
- `stop_loss`
- `trailing_stop`
- `contract_size`
- `lot_step`
- `lot_min`
- `lot_max`

## 对齐说明

- 原 EA 允许同方向最多 `ntmax` 层仓位，因此当前版本采用 layer-based 近似，而不是单净头寸的一笔单模型。
- 原 `Vol()` 使用 `FreeMargin`、`MaxRisk`、`StopLoss` 和已有层数共同决定下一笔手数；当前迁移版本按同样思路做风险近似，但在 Backtrader 下以统一合约参数简化。
- 原 trailing 逻辑对每个持仓逐个修改止损；当前版本对每个 layer 单独保存 `stop_price` 与 `take_profit_price` 并独立检查触发。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
