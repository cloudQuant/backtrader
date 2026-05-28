# 0040 Moving Average Crossover

## 策略概述

该策略是对 `0040_Beginner_Programming_Moving_Average_Crossover_with_and_without_Martingale_functionality` 目录下两个 MT5 EA 的统一迁移版本：

- `movingaverage.mq5`
- `movingaveragemartingale.mq5`

统一实现保留了“价格穿越移动平均线”这一核心入场逻辑，并通过 `use_martingale` 参数切换普通版与马丁版行为。

## 核心逻辑

1. 使用 `SMA(MAPeriod)` 作为参考线。
2. 仅在无持仓时开新仓。
3. 当价格从均线上方穿到下方时做空。
4. 当价格从均线下方穿到上方时做多。
5. 普通版：
   - 使用固定 `LotSize`
   - 使用固定 `TPPoints / SLPoints`
6. 马丁版：
   - 起始手数 `StartingLot`
   - 若上一笔交易亏损且未达到 `MaxLot`，则下笔交易按 `LotMultiplier` 放大手数
   - 同时按 `TPMultiplier` 放大 `TP/SL`
   - 若上一笔盈利，则恢复到初始参数

## 主要参数

主要参数定义在 `config.yaml`：

- `use_martingale`
- `ma_period`
- `lot_size`
- `tp_points`
- `sl_points`
- `starting_lot`
- `max_lot`
- `lot_multiplier`
- `tp_multiplier`

## 当前数据与运行方式

当前验证方式：

- 数据：`../../../datas/XAUUSD_M15.csv`
- 当前按 `M15` 直接运行

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 源码依赖 `ImportantFunctions.mqh` 中的辅助函数；迁移版本直接在 backtrader 中实现等价逻辑
- 当前 `config.yaml` 默认验证马丁版行为；将 `use_martingale` 改为 `false` 即可切换为普通版
