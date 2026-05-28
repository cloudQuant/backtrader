# 1100 The_20s_v020

## 策略概述

该示例是对 MT5 EA `1100_Exp_The_20s_v020` 的 Backtrader 迁移版本。
当前版本沿用仓库标准验证数据 `XAUUSD_M15.csv`，复刻原始 EA 的箭头信号逻辑与反手处理方式。

## 核心逻辑

1. 指标基于最近一根 K 线区间，计算 `Top20 / Bottom20` 触发区
2. 结合 `Level` 形成的价格偏移阈值，检测当前 bar 是否突破前一根 bar 的高低点结构
3. `MODE_1` 使用单根前置 K 线的开收盘位置和当前高低点突破生成信号
4. `MODE_2` 使用更长的 4 根 bar 结构过滤后生成信号
5. `Direct=false` 时按源码反转信号方向，`Direct=true` 时保持指标原始方向
6. 出现反向箭头后先平仓再反手
7. 下单后附加固定 `SL / TP`

## 主要参数

- `alg`
- `level`
- `ratio`
- `direct`
- `signal_bar`
- `stop_loss_points`
- `take_profit_points`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 迁移说明

- 原始 MT5 指标使用 `ATR(15)` 为箭头位置提供垂直偏移，当前版本已保留该逻辑
- EA 仅读取指标 `buy/sell` 两个 buffer，并据此执行开仓、平仓与反手
- 当前配置先按源码默认参数验证 `MODE_1` 路径，后续可继续测试 `MODE_2`
