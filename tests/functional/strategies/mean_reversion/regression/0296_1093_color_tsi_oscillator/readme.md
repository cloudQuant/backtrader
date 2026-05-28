# 1093 Exp_ColorTSI-Oscillator

## 策略概述

该示例是 MT5 EA `1093_Exp_ColorTSI-Oscillator` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `ColorTSI-Oscillator` 的主线与触发线，并在颜色翻转对应的交叉出现时执行开平仓。

## 原始信号逻辑

EA 从指标读取两个缓冲区：

- `buffer0`: `TSI` 主线
- `buffer1`: `Trigger` 触发线

交易条件：

- 若上一根 `TSI > Trigger`，且当前根 `TSI <= Trigger`，则触发买入信号并平空
- 若上一根 `TSI < Trigger`，且当前根 `TSI >= Trigger`，则触发卖出信号并平多

## 指标迁移说明

`ColorTSI-Oscillator` 先对价格动量 `dprice` 与其绝对值做两级平滑，再计算：

`TSI = 100 * smooth2(dprice) / smooth2(abs(dprice))`

触发线则是 `TSI` 向后平移 `TriggerShift` 根。

## 主要参数

- `first_method`
- `first_length`
- `second_method`
- `second_length`
- `ipc`
- `trigger_shift`
- `signal_bar`
- `stop_loss`
- `take_profit`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`40`
- 净收益：`-2021.50`
- 胜率：`55.00%`
- 最大回撤：`2.54%`
