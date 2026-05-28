# 1272 VininI_Trend

## 策略概述

该策略是对 MT5 EA `1272_Exp_VininI_Trend` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为让一组不同周期均线对收盘价进行多空投票，得到趋势强度，再按默认 `BREAKDOWN` 模式做阈值回归交易。

## 核心逻辑

1. 生成一组步进增长周期的均线
2. 统计收盘价相对这些均线的位置，得到 `[-100,100]` 趋势强度
3. 对趋势强度再做一层平滑
4. 默认 `BREAKDOWN` 模式下，趋势强度先突破 `UpLevel/DnLevel`，随后回到阈值内时开仓或反手
5. 同时保留 `TWIST` 模式，支持按指标方向翻转交易

## 主要参数

- `mode`
- `ma_method1`
- `length1`
- `ma_step`
- `ma_count`
- `ma_method2`
- `length2`
- `ipc`
- `up_level`
- `dn_level`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `13`
- Net P&L: `-311.90`
- Win Rate: `61.54%`
- Profit Factor: `0.75`
- Max Drawdown: `3.68%`
