# 0787 OpenTicks

## 策略概述

该策略是对 MT5 EA `0787_OpenTicks` 的 Backtrader 迁移版本。
当前版本保留了原 EA 的核心结构：

- 基于前 4 根已完成 K 线的 `high` 与 `open` 单调关系开仓
- 使用固定 `StopLoss`
- 盈利达到阈值后执行 trailing stair
- 可选的 `HalfLots` 半仓减持

## 核心逻辑

1. 若前 4 根 bar 的 `high/open` 依次抬高，则生成买入信号
2. 若前 4 根 bar 的 `high/open` 依次降低，则生成卖出信号
3. 空仓时根据新 bar 信号开仓
4. 有持仓时先检查固定止损
5. 当盈利超过 `TrailingStop` 后，推进止损，并按配置执行半仓处理

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `trailing_stop`
- `stop_loss`
- `lot`
- `half_lots`
- `max_orders`

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

- Trades: `462`
- Net P&L: `1,387.10`
- Win Rate: `46.97%`
- Profit Factor: `1.08`
- Max Drawdown: `1.68%`

## 对齐说明

- 原 EA 使用 `CPartialClosing` 和逐步 trailing stop；当前版本在 Backtrader 中实现了等价近似的 trailing stair + 半仓减持行为
- 原 EA 限制 `MaxOrders`；当前统一单品种验证框架下默认按单净持仓运行
- 原 EA 仅在新 bar 时开仓判断，当前版本保持同样约束
