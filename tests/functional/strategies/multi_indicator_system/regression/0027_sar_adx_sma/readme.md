# 1109 SAR + ADX + SMA100

## 策略概述

该策略是对 MT5 EA `1109_基于指标_SAR_e_ADX_e_sma_100_的_EA` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Parabolic SAR、ADX 与 SMA100 三重确认。

## 核心逻辑

1. 计算 `SMA100` 作为大方向过滤
2. 计算 `ADX` 判断趋势强度
3. 计算 `Parabolic SAR` 判断局部翻转方向
4. 只有当 SAR 方向、ADX 强度与 SMA100 大方向一致时才开仓
5. 指标关系失效时离场

## 主要参数

- `sma_period`
- `adx_period`
- `adx_threshold`
- `sar_af`
- `sar_afmax`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `267`
- Net P&L: `-1,092`
- Win Rate: `38.2%`
- Profit Factor: `0.96`
- Max Drawdown: `6.25%`
