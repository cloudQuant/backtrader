# 0468 Diff_TF_MA_EA

## 策略概述

该策略是对 MT5 EA `0468_Diff_TF_MA_EA` 的 backtrader 迁移版本。
原 EA 比较当前周期移动平均线与更高周期移动平均线的相对位置变化：若高周期 MA 从下向上穿越当前周期 MA，则做多；若高周期 MA 从上向下穿越当前周期 MA，则做空。出现反向信号时先平掉反向仓位，再按当前方向持有单一净头寸。

## 核心逻辑

1. 高周期 MA 周期为 `period_ma`
2. 当前周期 MA 周期按 `period_ma * higher_tf / current_tf` 自动换算
3. 比较第 2 根与第 1 根 bar 上两条 MA 的相对位置，识别穿越方向
4. 反向信号先平反向仓位，再开新仓
5. 支持可选反转信号与固定 `SL/TP`

## 主要参数

- `period_ma`
- `higher_tf_compression`
- `current_tf_compression`
- `reverse_trade`
- `volume`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- 数据区间：`2025-12-03 01:15:00` → `2026-03-10 09:00:00`
- K线数量：`6129`
- 买入次数：`36`
- 卖出次数：`37`
- 平仓交易数：`36`
- 期末权益：`101594.50`
- 净收益：`1594.50`
- 总收益率：`1.59%`
- 胜率：`70.27%`
- Profit Factor：`1.15`
- 最大回撤：`12.44%`

## 对齐说明

- 原 EA 直接在 EA 内部计算当前周期与高周期 MA，不依赖外部指标；当前版本以 `M15 + H4 resample` 的方式复现同一结构
- 原 README 提醒其设计偏向双向持仓账户，但默认进场逻辑本身是单方向反手；当前版本在 Backtrader 净头寸模型下保留该单仓切换行为
- 原 EA 默认不设置固定 `SL/TP`；当前配置也保持 `0/0`
