# 0359 Price Rollback

## 策略来源

- MT5 源码：`ea/0359_价格回滚/price_rollback.mq5`
- 当前实现：`examples/0359_price_rollback/`

## 策略逻辑

- 每根新柱先处理 trailing，并在晚间强制平仓时段尝试平掉现有仓位。
- 若当前没有持仓，则在指定星期的午夜窗口检查回滚条件：
  - `25` 根窗口最早一根的开盘价相对上一根收盘价向下偏移超过 `Corridor`，则做多。
  - 若上一根收盘价相对该参考开盘价向上偏移超过 `Corridor`，则做空。
- 开仓后保留固定 `SL/TP` 与 trailing stop。

## 与源码一致/差异说明

- 原 EA 在 `22:45` 之后对当前品种当前 `magic` 的所有仓位执行 `CloseAllPositions()`；当前版本在对应时间窗口内按单净仓语义平掉现有仓位。
- 原源码默认 `InpLots=0.1`，当前迁移同样以固定手数回测，不额外引入 MT5 风险换手数逻辑。
- 原实现通过 `CopyRates(..., 0, 25, rates)` 读取最近 `25` 根柱；当前版本按 Backtrader 的历史索引近似复现同一窗口比较关系。

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
