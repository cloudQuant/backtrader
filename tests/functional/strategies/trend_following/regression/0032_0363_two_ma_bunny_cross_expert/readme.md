# 0363 Two MA Bunny Cross Expert

## 策略来源

- MT5 源码：`ea/0363_双均线交叉智能系统/2ma_bunny_cross_expert.mq5`
- 当前实现：`examples/0363_two_ma_bunny_cross_expert/`

## 策略逻辑

- 基于 `PRICE_WEIGHTED` 价格序列计算两条 `SMA`：
  - 快线：`5` 周期，`shift=0`
  - 慢线：`20` 周期，`shift=3`
- 当快线从下向上穿越慢线时，平掉空头并开多。
- 当快线从上向下穿越慢线时，平掉多头并开空。
- 当前迁移严格限制为单品种、单净仓，不保留 MT5 中按风险百分比自动换算手数的资金管理对象。

## 与源码一致/差异说明

- 原 EA 使用 `CMoneyFixedMargin` 在 `Risk>0` 时按保证金估算下单手数；当前版本改为 `fixed_lot`，避免把 MT5 账户保证金细节硬编码进 Backtrader。
- 原 EA 通过 `ClosePositions(POSITION_TYPE_*)` 先平反向仓，再以市价开新仓；当前版本保持同样的净仓反手语义。
- 原 EA 没有固定 `SL/TP` 或追踪止损，本迁移也保持为纯均线交叉反手出场。

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
