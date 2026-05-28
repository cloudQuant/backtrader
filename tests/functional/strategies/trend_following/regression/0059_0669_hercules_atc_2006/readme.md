# 0669 Hercules A.T.C. 2006

## 策略概述

该策略是对 MT5 EA `0669_Hercules_A.T.C._2006` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- `EMA(1)` 与 `SMA(72)` 交叉后的突破触发
- `H1 RSI` 过滤
- `D1/H4 Envelope` 过滤
- 最近窗口高低点过滤
- 一次触发同时开出两条同向腿
- 两腿分别使用不同 `TP`
- 公共 trailing stop
- `blackout` 冷却窗口

## 核心逻辑

1. 在基础周期上检测 `EMA(1)` 与 `SMA(72)` 的最近 1-2 根 bar 交叉。
2. 根据交叉均值价加减 `Trigger` 形成突破触发价。
3. 仅在触发后的有限窗口内允许入场。
4. 多头需同时满足：
   - `price >= trigger_price`
   - `H1 RSI > RSI_Upper`
   - 价格高于最近窗口高点
   - 价格高于 `D1/H4 Envelope` 上轨
5. 空头条件与上面对称。
6. 入场时一次建立两条同向腿，分别对应 `TakeProfit1` 和 `TakeProfit2`。
7. 两条腿共享 trailing stop，并在触发后进入 `blackout` 冷却期。

## 迁移说明

- 原 EA 使用 MT5 多单模型，同向同时持有两条腿；迁移版保留这一结构，并在 Backtrader 中按“子腿”方式管理部分平仓。
- 原版对 `H10` 高低点窗口的写法与周期单位存在歧义；迁移版按基础周期分钟数推导窗口长度，以保持策略在当前样例数据下可运行。
- 原 EA 还包含 `MoneyFixedRisk` 风险手数计算；迁移版保留风险驱动手数入口，并提供固定手数回退。

## 主要参数

- `trigger`
- `trailing_stop`
- `take_profit_1`
- `take_profit_2`
- `rsi_upper`
- `rsi_lower`
- `blackout_period_hours`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验，再同步台账中的验证结果。
