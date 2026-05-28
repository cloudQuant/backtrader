# 0104 ICT_conceptsEA_by_Emil

## 策略概述

该样例是对 MT5 EA `0104_ICT_conceptsEA_by_Emil` 的 Backtrader 核心子集迁移版。
原 EA 结合了 `Silver Bullet`、`2022 Model`、HTF bias、流动性扫单、MSS、FVG、NDOG/NWOG、分批止盈与 trailing/保本管理。

## 迁移思路

1. 使用 `H1 SMA(200)` 作为 HTF bias
2. 保留 `Silver Bullet` 时间窗与 `2022 Model` 备选入场
3. 保留流动性扫单、MSS、FVG、NDOG/NWOG 的主判定顺序
4. 使用风险百分比计算手数
5. 保留 `TP1/TP2/TP3` 的分批止盈结构
6. 保留 `TP1` 后保本与 `TP2` 后 trailing stop

## 主要参数

- `risk_percent_per_trade`
- `tp1_rr`
- `tp2_rr`
- `tp3_rr`
- `partial_close_percent_tp1`
- `partial_close_percent_tp2`
- `move_sl_to_be_after_tp1`
- `trailing_sl_pips`
- `sb_start_time`
- `sb_end_time`
- `htf_ma_period`
- `dol_lookback_bars`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `N/A`
- Max Drawdown: `0.00%`

## 诊断说明

- 默认参数下未触发成交。
- 诊断计数显示主要阻塞项为 `liquidity_sweep` 过滤，`setup_ready = 0`。

## 对齐说明

- 当前版本保留了原 EA 的核心结构，但仍属于“核心子集迁移”，未复刻图表对象与所有全局变量存储细节
- 当前版本采用 Backtrader 的 bar 级执行近似部分止盈与 trailing 行为
- 当前版本保持单净头寸，不扩展到多策略并行持仓
