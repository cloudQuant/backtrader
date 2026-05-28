# 1266 ADX_Cross_Hull_Style

## 策略概述

该策略是对 MT5 EA `1266_Exp_ADX_Cross_Hull_Style` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为使用 `ADX_Cross_Hull_Style` 箭头信号入场，并叠加 `UltraXMA` 趋势过滤与辅助平仓。

## 核心逻辑

1. 用双周期 `DI` 差构造 `ADX_Cross_Hull_Style` 多空箭头
2. 用 `UltraXMA` 的多空缓冲区判断趋势方向
3. 仅在趋势过滤允许时保留入场信号
4. 若趋势过滤反向，则直接抑制对应入场并触发平仓
5. 若当前柱无过滤平仓，则回溯最近反向箭头补平仓

## 主要参数

- `adx_period`
- `w_method`
- `start_length`
- `wphase`
- `n_step`
- `n_steps_total`
- `smooth_method`
- `smooth_length`
- `smooth_phase`
- `ipc`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `N/A`
- Max Drawdown: `0.00%`
