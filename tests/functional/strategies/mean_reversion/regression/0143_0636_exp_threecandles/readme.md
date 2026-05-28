# 0636 Exp_ThreeCandles

## 策略概述

该策略是对 MT5 EA `0636_Exp_ThreeCandles` 的 Backtrader 迁移版本。

- 基于 `ThreeCandles` 指标颜色信号入场
- 同周期反向信号触发平仓与反向重入
- 固定 `SL/TP`，单净仓

## 核心逻辑

1. `ThreeCandles` 指标使用最近 4 根 K 线的形态关系识别两类三烛形模式，并产出颜色状态。
2. 当信号值 `> 2` 时视为买入信号。
3. 当信号值 `< 2` 时视为卖出信号。
4. 若持有反向仓位且出现新信号，则先平仓再按新方向重入。
5. 持仓使用固定 `SL/TP` 管理。

## 迁移说明

- 原 EA 依赖 `ThreeCandles.ex5` 与 `TradeAlgorithms.mqh`；迁移版在 Python 中直接实现三烛形颜色信号，手数管理简化为固定 `lots`。
- 原指标包含可选成交量过滤；迁移版保留 `volume_type` 与 `max_bar1` 两项近似控制，并使用导入数据中的成交量列进行过滤。
- 示例从 `M15` 数据重采样到 `H6`，对应源码默认测试周期。

## 主要参数

- `signal_bar`
- `max_bar1`
- `volume_type`
- `buy_pos_open` / `sell_pos_open`
- `buy_pos_close` / `sell_pos_close`
- `stop_loss` / `take_profit`
- `lots`

## 运行方式

```bash
python run.py
```
