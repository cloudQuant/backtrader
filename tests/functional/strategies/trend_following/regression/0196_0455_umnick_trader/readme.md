# 0455 UmnickTrader

## 策略来源
- MT5 EA: `ea/0455_UmnickTrader/umnicktrader.mq5`
- Backtrader 实现: `examples/0455_umnick_trader/strategy_umnick_trader.py`
- 运行脚本: `examples/0455_umnick_trader/run.py`

## 核心逻辑
- 使用上一根 K 线典型价格 `(open+high+low+close)/4` 与上次触发价格的距离，作为下一次进场触发条件。
- 默认方向为做多；若上一笔交易亏损，则翻转下一笔交易方向。
- 每笔交易使用一组动态 `limit/stop`，其值由最近 8 笔的最大浮盈与最大回撤滚动平均得到。
- 同一时刻仅保留单一净头寸；迁移版使用 bracket order 近似源码中的入场附带 `SL/TP` 行为。

## 参数映射
- `StopBase=0.0170`
- `InpLots=0.1`
- `spred=0.0005`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Bar shift：`15` 分钟

## 首轮回测结果
- 期初权益：`100000.00`
- 期末权益：`79856.62`
- 净收益：`-20143.38`
- 平仓笔数：`2902`
- 胜率：`43.56%`
- Profit Factor：`0.83`
- 最大回撤：`21.75%`

## 对齐说明
- 原 EA 在 `hedging` 账户上运行，但实际主流程通过 `CalculatePositions()==0` 保持同品种单次只持有一笔仓位；迁移版据此落为单净仓语义。
- 原 EA 以服务器侧 `SL/TP` 驱动离场，迁移版使用 Backtrader bracket order 近似复现。
- 原 EA 在下一次触发前通过账户权益差判断上一笔盈亏，迁移版在 `notify_trade` 中于平仓时即时更新同一状态机。

## 验证状态
- 当前已完成可运行迁移目录、参数映射与非 `python` 类命令方式的运行验证。
- 首轮回测已通过 `bash run_example_backtest.sh 0455` 完成结果回写。
