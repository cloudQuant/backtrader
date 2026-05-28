# 0655 21hour

## 策略概述

该策略是对 MT5 EA `0655_21hour` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 两个不重叠时间窗口
- 每个窗口起点放置双向突破意图
- 触发一侧后取消另一侧
- 到窗口终点强制平仓并撤销挂单
- 固定 `TP`

## 核心逻辑

1. 当时间到达 `hour_start_first:00` 或 `hour_start_second:00` 时：
   - 上方放置 `BuyStop`
   - 下方放置 `SellStop`
2. 突破距离由 `step` 控制。
3. 一旦任一方向被触发，另一侧意图取消。
4. 若时间到达 `hour_stop_first:00` 或 `hour_stop_second:00`：
   - 关闭当前仓位
   - 删除未触发意图
5. 触发后的持仓使用固定 `TP` 管理。

## 迁移说明

- 原 EA 使用 MT5 挂单；迁移版在 Backtrader 中以“待触发突破价位”近似重建。
- 原源码中的对冲检查被注释掉，主体行为仍是单仓风格，迁移版按单净仓实现。
- 示例使用 `XAUUSD_M5.csv`，以适配当前工作区可用数据与原策略推荐周期。

## 主要参数

- `hour_start_first`
- `hour_stop_first`
- `hour_start_second`
- `hour_stop_second`
- `step`
- `take_profit`
- `lots`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验，再同步台账中的验证结果。
