# 0408 UniversalMACrossEA

## 策略来源
- MT5 EA: `ea/0408_UniversalMACrossEA/universalmacrossea.mq5`
- Backtrader 实现: `examples/0408_universal_macross_ea/strategy_universal_macross_ea.py`
- 运行脚本: `examples/0408_universal_macross_ea/run.py`

## 核心逻辑
- 双均线交叉信号：`EMA(10)` 与 `EMA(80)`。
- `ConfirmedOnEntry=true` 时，使用前一根已完成 bar 的交叉确认；否则允许使用当前 bar。
- `OneEntryPerBar=true` 时，同一 bar 只允许一次新开仓检查。
- `StopAndReverse=true` 时，若已有仓位且交叉方向反转，则先平旧仓，待下一次信号再重新入场，保持单仓语义。
- 可选时段过滤 `UseHourTrade / StartHour / EndHour`。
- 若 `PureSAR=false`，保留固定 `SL/TP` 与 trailing；若 `PureSAR=true`，则关闭这些保护参数。

## 参数映射
- `InpStopLoss=100`
- `InpTakeProfit=200`
- `InpTrailingStop=40`
- `InpTrailingStep=5`
- `FastMAPeriod=10`
- `FastMAType=MODE_EMA`
- `FastMAPrice=PRICE_CLOSE`
- `SlowMAPeriod=80`
- `SlowMAType=MODE_EMA`
- `SlowMAPrice=PRICE_CLOSE`
- `InpMinCrossDistance=0`
- `ReverseCondition=false`
- `ConfirmedOnEntry=true`
- `OneEntryPerBar=true`
- `StopAndReverse=true`
- `PureSAR=false`
- `UseHourTrade=false`
- `StartHour=10`
- `EndHour=11`
- `InpLots=0.10`（迁移版固定 lot，未复现 MT5 风险换算）
- `m_magic=15489`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Base bar shift：`15` 分钟

## 对齐说明
- 原版通过 `CalculateAllPositions()>0` 与 `total<1` 组合保持同品种同 magic 单仓；迁移版保持同样单仓语义。
- 原版 `StopAndReverse` 是先 `CloseAllPositions()` 再等待后续入场逻辑；迁移版保持“先平再重新开”的反手框架，不做多仓叠加。
- MT5 版本支持 `Risk` 驱动的 `CMoneyFixedMargin` 动态手数；迁移版为了与当前样例目录保持一致，固定使用配置里的 `lot`。
- 当前目录已完成可运行迁移，详细回测结果待后续通过非 `python` 类命令补录。
