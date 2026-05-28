# 0794 Exp_3RVI

## 策略概述

该策略是对 MT5 EA `0794_Exp_3RVI` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，保留了原 EA 的核心结构：

- 三个不同周期的 `RVI`
- 高周期与中周期定义趋势方向
- 低周期的 `RVI` / signal 交叉触发入场
- 任一周期趋势反向时触发离场
- 固定 `SL/TP`

## 核心逻辑

1. 计算三个不同周期上的 `RVI`
2. 在高周期和中周期上，用 `main > signal` 视为多头趋势，`main < signal` 视为空头趋势
3. 在低周期上，当 `RVI` 上穿 `signal` 且高/中周期同向看多时做多
4. 在低周期上，当 `RVI` 下穿 `signal` 且高/中周期同向看空时做空
5. 持仓后若任一启用的周期趋势反向，则平仓
6. 同时应用固定止损和止盈

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `lot`
- `stop_loss`
- `take_profit`
- `rvi_period`
- 各周期开平仓许可参数

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M15.csv`

运行命令：

```bash
python run.py
```

如果需要绘图：

```bash
python run.py --plot
```

## 当前回测结果

当前参数下的回测结果：

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `None`
- Max Drawdown: `0.00%`

## 对齐说明

- 原 EA 默认运行在 `M30/M15/M5` 三周期；当前统一验证数据只有 `M15`，因此采用 `H1/M30/M15` 近似保留三周期层次
- 原 EA 依赖 `TradeAlgorithms.mqh` 完成订单管理；当前版本在 Backtrader 中直接实现同等的开平仓与 `SL/TP` 逻辑
- 当前版本内置了标准 `RVI` 计算与 signal 线，作为 MT5 `iRVI` 的可运行近似实现
