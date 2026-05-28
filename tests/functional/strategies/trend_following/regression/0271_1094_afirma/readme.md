# 1094 Exp_AFIRMA

## 策略概述

该示例是 MT5 EA `1094_Exp_AFIRMA` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `AFIRMA` 指标的 `ARMA` 线拐点，在方向变化时执行开平仓。

## 原始信号逻辑

EA 只读取指标的 `buffer1`，即 `ARMA` 线：

- 若 `Value[1] < Value[2]` 且 `Value[0] > Value[1]`，则视为买入拐点
- 若 `Value[1] > Value[2]` 且 `Value[0] < Value[1]`，则视为卖出拐点
- 出现买入拐点时，平空并可开多
- 出现卖出拐点时，平多并可开空

其中 `Value[0] / Value[1] / Value[2]` 分别对应 `SignalBar`、`SignalBar+1`、`SignalBar+2` 的 `ARMA` 值。

## 指标迁移说明

`AFIRMA` 指标输出两条线：

- `FIRMA`: 基于窗口函数的有限脉冲响应平滑线
- `ARMA`: 对最近 `n=(Taps-1)/2` 根 bar 做三次回归外推得到的线

由于原始指标具有一定重绘特性，这里采用按时间递推、并允许最近 `n` 根值被后续 bar 重算的方式近似复现 MT5 行为。

## 主要参数

- `periods`
- `taps`
- `window`
- `signal_bar`
- `stop_loss`
- `take_profit`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
