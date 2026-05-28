# 1271 VininI_Trend_LRMA

## 策略概述

该策略是对 MT5 EA `1271_Exp_VininI_Trend_LRMA` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为先计算 `LRMA`，再对一组不同周期的 `LRMA` 平滑线进行多空投票，并叠加 `ChangeOfVolatility` 过滤器后交易。

## 核心逻辑

1. 先计算 `LRMA`
2. 将 `LRMA` 与一组步进增长周期的平滑 `LRMA` 比较，得到 `[-100,100]` 趋势强度
3. 对趋势强度再做一层平滑，生成 `VininI_Trend_LRMA`
4. 计算 `ChangeOfVolatility`，仅在趋势强度过滤通过时允许开仓
5. 默认 `BREAKDOWN` 模式下，指标先突破 `UpLevel/DnLevel`，随后回到阈值内时开仓或反手
6. 同时保留 `TWIST` 模式，支持按指标方向翻转交易

## 主要参数

- `mode`
- `lrma_period`
- `ma_method1`
- `length1`
- `ma_step`
- `ma_count`
- `ma_method2`
- `length2`
- `ipc`
- `up_level`
- `dn_level`
- `mperiod`
- `short`
- `long`
- `max_trend_level`
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
