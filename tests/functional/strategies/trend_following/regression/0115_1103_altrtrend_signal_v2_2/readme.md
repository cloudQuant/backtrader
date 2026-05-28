# 1103 AltrTrend Signal v2.2

## 策略概述

该示例是对 MT5 EA `1103_Exp_AltrTrend_Signal_v2_2` 的 Backtrader 迁移版本。
当前版本沿用仓库标准验证数据 `XAUUSD_M15.csv`，复刻原始 `AltrTrend_Signal_v2_2` 指标的箭头信号与反手逻辑。

## 核心逻辑

1. 使用 `ADX` 计算自适应窗口长度 `SSP`
2. 在动态窗口内统计最高价、最低价和平均波动范围
3. 根据 `K` 计算上下阈值 `smax / smin`
4. 价格突破阈值后更新趋势方向
5. 当趋势方向相对前值发生切换时，输出买入或卖出箭头
6. 策略使用箭头信号开仓，出现反向箭头时先平仓再反手
7. 下单后附加固定 `SL / TP`

## 主要参数

- `signal_bar`
- `k`
- `kstop`
- `kperiod`
- `per_adx`
- `stop_loss_points`
- `take_profit_points`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 迁移说明

- 原始 MT5 指标通过 `iADX` 与自适应窗口生成信号箭头，当前迁移版本保留了这一思路
- MT5 指标在 timeseries 索引下从旧到新维护趋势状态，Backtrader 版本改为顺序递推方式复刻同类状态机
- 如果后续需要进一步逐 tick 校准，可在当前基础上继续对齐 `old_trend` 的边界行为
