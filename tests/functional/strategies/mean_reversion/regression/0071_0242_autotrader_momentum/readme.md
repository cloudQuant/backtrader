# 0242 Autotrader Momentum

## 策略来源

- MT5 源码：`ea/0242_Autotrader_Momentum/autotrader_momentum.mq5`

## 策略逻辑

- EA 在新柱出现时比较 `当前柱收盘价` 与 `比较柱收盘价`。
- 当 `Close[current] > Close[comparable]` 时，先平空再开多。
- 当 `Close[current] < Close[comparable]` 时，先平多再开空。
- 开仓时可附带固定 `SL/TP`。
- `Trailing Stop` 持续工作，不只在新柱触发。
- 当前 backtrader 实现使用 `M15` 作为执行与信号周期。

## 与源码一致/差异说明

- 保留了新柱反手、固定 `SL/TP` 和持续 trailing stop 主流程。
- 原版可运行在净额与锁仓账户，但其交易动作本身是“先关旧仓再开新仓”的单方向切换逻辑，因此适合当前单净头寸迁移框架。
- MT5 原版是在 tick 级别持续维护 trailing stop；当前 backtrader 版本在每个执行 bar 上更新 trailing stop，属于 bar 级近似。
- 原 readme 没有附带仓库可用的原品种数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_autotrader_momentum.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
