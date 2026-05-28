# 0788 Exp_CenterOfGravityCandle

## 策略概述

该策略是对 MT5 EA `0788_Exp_CenterOfGravityCandle` 的 Backtrader 迁移版本。
当前版本在统一验证数据 `XAUUSD_M15.csv` 上运行，并以 `H6` 重采样近似原 EA 的 `CenterOfGravityCandle` 指标周期。

## 核心逻辑

1. 将基础 `M15` 数据重采样为 `H6`
2. 计算 `CenterOfGravityCandle` 的中心线与信号线
3. 当指标状态切换为多头颜色时开多，并关闭空头
4. 当指标状态切换为空头颜色时开空，并关闭多头
5. 使用固定 `SL/TP`

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `period`
- `smooth_period`
- `ma_method`
- `signal_bar`
- `stop_loss`
- `take_profit`

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

- Trades: `21`
- Net P&L: `2,703.80`
- Win Rate: `52.38%`
- Profit Factor: `1.99`
- Max Drawdown: `1.21%`

## 对齐说明

- 原 EA 依赖 `CenterOfGravityCandle.ex5` 自定义指标；当前版本基于已有 `CenterOfGravity` 参考实现进行了 Python 等价近似
- 原 EA 指标默认运行在 `H6`，当前通过 `M15 -> H6` 重采样近似
- 原 EA 使用 `TradeAlgorithms.mqh` 进行下单与仓位处理；当前版本以 Backtrader 的单仓位开平仓逻辑实现等价行为
