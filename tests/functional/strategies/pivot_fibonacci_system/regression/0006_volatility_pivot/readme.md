# 1095 Exp_VolatilityPivot

## 策略概述

该示例是对 MT5 EA `1095_Exp_VolatilityPivot` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `VolatilityPivot` 指标的上下轨与买卖箭头信号，并根据 `Direct` 参数决定顺势或反向交易。

## 原始信号逻辑

指标共有 4 个缓冲区：

1. `buffer0`: upper trend
2. `buffer1`: lower trend
3. `buffer2`: buy signal
4. `buffer3`: sell signal

EA 逻辑：

- `TrueDirect`: 顺势，买入使用 `buy signal`，卖出使用 `sell signal`
- `FalshDirect`: 反向，买入使用 `sell signal`，卖出使用 `buy signal`
- 若只有趋势线存在而无新信号，则可触发反向持仓平仓

## 指标迁移说明

`VolatilityPivot` 支持两种模式：

- `Mode_ATR`: 先计算 ATR，再用 EMA 平滑并乘上 `atr_factor` 作为动态偏移
- `Mode_Price`: 直接使用固定价格偏移 `delta_price * point`

然后按源码递推止损轨迹 `Stop`，再生成上下轨和新出现时的箭头信号。

## 主要参数

- `direct`
- `atr_range`
- `ima_range`
- `atr_factor`
- `ind_mode`
- `delta_price`
- `signal_bar`
- `stop_loss`
- `take_profit`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
