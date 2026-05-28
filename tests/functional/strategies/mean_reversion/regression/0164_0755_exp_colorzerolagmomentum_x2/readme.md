# 0755 Exp_ColorZerolagMomentum_X2

## 策略概述

该策略是对 MT5 EA `0755_Exp_ColorZerolagMomentum_X2` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主结构：

- 慢周期 `ColorZerolagMomentum` 主线/信号线判定趋势方向
- 快周期 `ColorZerolagMomentum` 主线/信号线交叉决定入场
- 交易使用固定 `SL/TP`
- 趋势离场和快线离场开关均保留

## 核心逻辑

1. 在慢周期 `H6` 与快周期 `M30` 上分别计算 `ColorZerolagMomentum`。
2. 指标主线由 5 组 `Momentum * Factor` 加权求和组成。
3. 指标信号线按原始递推思路对主线做平滑。
4. 慢周期 `main > signal` 视为多头趋势，`main < signal` 视为空头趋势。
5. 仅当快周期交叉方向与慢趋势一致时才开仓；反向时按开关条件平仓。

## 主要参数

- `smoothing`
- `factor1..factor5`
- `momentum_period1..momentum_period5`
- `slow_tf_minutes`
- `fast_tf_minutes`
- `stop_loss`
- `take_profit`

## 对齐说明

- 原 EA 将 `ColorZerolagMomentum` 与 `ColorZerolagMomentum_HTF` 作为资源嵌入；当前迁移在 Python 中直接重建指标，不依赖编译文件。
- 源码里 `Osc3 = Factor2 * Momentum3` 这一细节已按原实现保留，而不是按参数名自动改写成 `Factor3`。
- 交易流程保持与其他 `X2` 系列一致：慢趋势过滤 + 快趋势翻转入场。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
