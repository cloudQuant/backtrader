# 1101 Slow-Stoch

## 策略概述

该示例是对 MT5 EA `1101_Exp_Slow-Stoch` 的 Backtrader 迁移版本。
当前版本沿用仓库标准验证数据 `XAUUSD_M15.csv`，复刻原始 EA 的三种信号模式：`breakdown`、`twist`、`cloudtwist`。

## 核心逻辑

1. 使用 `Stochastic Full` 构造慢速随机振荡器主线与信号线
2. 对两条线再做一层平滑，得到 `Slow-Stoch` 样式的云带
3. `breakdown`：主线穿越 `50` 中轴时触发信号
4. `twist`：主线方向由跌转升 / 由升转跌时触发信号
5. `cloudtwist`：主线与信号线交叉、云带颜色切换时触发信号
6. 出现反向信号时先平仓再反手
7. 下单后附加固定 `SL / TP`

## 主要参数

- `mode`
- `signal_bar`
- `k_period`
- `d_period`
- `slowing`
- `xlength`
- `stop_loss_points`
- `take_profit_points`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 迁移说明

- 原始 MT5 指标依赖 `iStochastic` 与额外平滑算法，当前迁移版本先保留可运行的慢速随机近似路径
- 三种 EA 信号模式已按源码中的 buffer 读取逻辑复刻
- 如果后续需要进一步贴近 `JJMA` 等特定平滑方法，可以在当前版本上继续校准
