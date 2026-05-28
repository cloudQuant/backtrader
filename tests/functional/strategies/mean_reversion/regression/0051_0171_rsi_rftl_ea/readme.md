# 0171 RSI_RFTL_EA

## 策略概述

该样例是对 MT5 EA `0171_RSI_RFTL_EA` 的 Backtrader 迁移版。
EA 基于 `RSI` 局部顶底构造的趋势线延长值、`RFTL` 趋势过滤和 `RSI` 极值平仓逻辑交易。当前迁移版以 Backtrader 单净头寸近似原 EA 的锁仓账户行为。

## 迁移思路

1. 在 `M15` 数据上重建 `RSI(30)` 与 `RFTL` 自定义卷积滤波器
2. 扫描最近 `500` 根 RSI 序列中的局部顶点与底点
3. 使用最近两组有效顶/底构造 RSI 趋势线延长值
4. 满足 `RFTL` 与价格相对位置过滤后，分别触发多空入场
5. 当 `RSI > 70` 时平多；当 `RSI < 30` 时平空
6. 保留固定止损、止盈与 trailing stop 主流程

## 主要参数

- `fixed_lot`
- `stoploss_pips`
- `takeprofit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `rsi_period`
- `lookback_bars`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前验证状态

- 当前近似迁移骨架已可运行
- 默认参数下本轮验证结果为 `0` 笔成交，暂不计入“已完成迁移”
- 后续需要继续对齐 RSI 顶底扫描与原锁仓账户行为，才能决定是否升级为正式完成项

## 对齐说明

- 原 EA 明确面向锁仓账户；当前 Backtrader 版本以单净头寸近似其持仓行为
- 当前迁移重点保留 `RSI 顶底趋势线 + RFTL 过滤 + RSI 极值平仓 + trailing` 主逻辑
- Backtrader 无法逐 tick 复刻 MT5 的账户模式与成交细节，因此结果应视为可运行的逻辑迁移样例
