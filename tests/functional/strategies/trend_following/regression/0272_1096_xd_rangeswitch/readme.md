# 1096 Exp_XD-RangeSwitch

## 策略概述

该示例是对 MT5 EA `1096_Exp_XD-RangeSwitch` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `XD-RangeSwitch` 指标的趋势线与箭头信号，并根据 `Direct` 参数决定顺势或反向交易。

## 原始信号逻辑

指标共有 4 个缓冲区：

1. `buffer0`: upper trend
2. `buffer1`: lower trend
3. `buffer2`: sell signal
4. `buffer3`: buy signal

EA 逻辑：

- `TrueDirect`: 顺势，买入使用 `buy signal`，卖出使用 `sell signal`
- `FalshDirect`: 反向，买入使用 `sell signal`，卖出使用 `buy signal`
- 若只有趋势线存在而无新信号，则可触发反向持仓平仓

## 指标迁移说明

`XD-RangeSwitch` 可以直接按源码重建：

- 若当前收盘价突破前 `N` 根最高价，则切到下轨趋势
- 若当前收盘价跌破前 `N` 根最低价，则切到上轨趋势
- 否则延续上一根的趋势轨道
- 新轨道首次出现时同时输出箭头信号

## 主要参数

- `direct`
- `n`
- `signal_bar`
- `stop_loss`
- `take_profit`
- `size`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
