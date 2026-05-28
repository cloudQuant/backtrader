# 0416 Momentum-M15

## 策略来源
- MT5 EA: `ea/0416_Momentum-M15/momentum-m15.mq5`
- Backtrader 实现: `examples/0416_momentum_m15/strategy_momentum_m15.py`
- 运行脚本: `examples/0416_momentum_m15/run.py`

## 核心逻辑
- `M15` 新柱触发；若当前没有仓位才允许开新单。
- 入口由三层条件组成：
  - `SMMA(low, 26)` 再配合 `ma_shift=8` 作为位置过滤。
  - `Momentum(open, 23)` 与 `MO_Min / MO_Shift` 组成强弱阈值。
  - 最近 `MO_OpenTime=6` 根的 `Momentum` 必须保持单调上行或下行。
- 出场条件：
  - 多头在 `Momentum` 下行持续 `MO_CloseTime=10` 根，或上一根收盘跌回均线下方时平仓。
  - 空头在 `Momentum` 上行持续 `MO_CloseTime=10` 根，或上一根收盘升回均线上方时平仓。
  - 若启用 `InpTrailingStop`，则按当前新柱价格推进 trailing。
- 额外保留 `gap` 冷却：当 `(open[0]-close[1]) / point > 30` 时，暂停后续 `100` 根 bar 的开仓检查。

## 参数映射
- `InpLots=0.10`
- `InpTrailingStop=0`
- `InpMA_ma_period=26`
- `InpMA_ma_shift=8`
- `InpMA_ma_method=MODE_SMMA`
- `InpMA_ma_price=PRICE_LOW`
- `MO_Min=100.0`
- `MO_Shift=-0.2`
- `InpMO_mom_period=23`
- `InpMO_applied_price=PRICE_OPEN`
- `MO_OpenTime=6`
- `MO_CloseTime=10`
- `m_magic=15489`
- 固定 gap 参数：`GAP_Level=30`, `GAP_TimeOUT=100`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Base bar shift：`15` 分钟

## 对齐说明
- 原版 EA 通过 `!IsPositions()` 限制任意时刻仅存在一笔持仓；迁移版保持同样单仓语义。
- MT5 中 `iMA(..., shift=8)` 使用了向右平移后的显示缓冲区；迁移版以 `SMMA(low)[-8]` 近似复现该比较基线。
- MT5 在新柱出生时读取 `Momentum(open)` 与 `iOpen(0)`；迁移版按当前 bar 的 `open` 近似复现，不使用挂单、多票和加仓。
- trailing 在原版中通过 `PositionModify(ticket, ...)` 推进；迁移版以单仓内部 trailing 阈值近似复现。
- 当前目录已完成可运行迁移，详细回测结果待后续通过非 `python` 类命令补录。
