# 0771 Exp_Bezier_ReOpen

## 策略概述

该策略是对 MT5 EA `0771_Exp_Bezier_ReOpen` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 使用本地可重建的 `Bezier` 平滑曲线转折信号作为首单开平仓依据
- 在已有同向仓位盈利达到固定 `PriceStep` 后做顺势加仓
- 每一层仓位单独记录固定 `StopLoss / TakeProfit`
- 使用 `PosTotal` 限制最大加仓层数

## 核心逻辑

1. 将 `M15` 数据重采样为指标周期 `H4`，按原指标公式计算 `Bezier` 曲线。
2. 若最近三个已完成指标值满足 `old > mid < recent`，判定为向上拐点，生成做多信号并关闭空头。
3. 若最近三个已完成指标值满足 `old < mid > recent`，判定为向下拐点，生成做空信号并关闭多头。
4. 若已有多头层，且当前价格相对最近一层入场价盈利超过 `PriceStep * point`，继续加多。
5. 若已有空头层，且当前价格相对最近一层入场价盈利超过 `PriceStep * point`，继续加空。
6. 每一层使用自身入场价计算固定 `SL/TP`，在 bar 级回测中按柱高低点近似触发减仓/平仓。

## 主要参数

- `indicator_minutes`
- `bperiod`
- `t`
- `ipc`
- `signal_bar`
- `price_step`
- `pos_total`
- `stop_loss_points`
- `take_profit_points`
- `size`

## 对齐说明

- 原 EA 依赖的 `Bezier` 指标源码 `bezier.mq5` 在仓库中可见，因此当前版本按本地源码重建指标，而不是臆造外部 `.ex5` 结果。
- 原 EA 通过注释字符串保存“加仓次数/最近成交价/最近手数”；当前版本用 `layers` 结构维护同等分层状态。
- 原 EA 通过 `TradeAlgorithms.mqh` 在 MT5 净持仓模型上实现反向平仓与同向加仓；当前版本在 Backtrader 中用分层账本近似。
- 当前实现固定使用 `size=0.1` 近似 `MMMode=LOT` 默认语义，尚未复刻动态资金管理分支。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 由于本轮仍按无审批命令方式推进，尚未补做本地回测校验，因此建议台账先保留为 `实施中`，待后续补充结果后再改为 `已完成`。
