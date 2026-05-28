# 0415 Brandy

## 策略来源
- MT5 EA: `ea/0415_Brandy/brandy.mq5`
- Backtrader 实现: `examples/0415_brandy/strategy_brandy.py`
- 运行脚本: `examples/0415_brandy/run.py`

## 核心逻辑
- `M15` 新柱触发；只有在当前无仓时才允许开新单。
- 入场依赖两组均线比较：
  - `EMA(close, 70)` 的 `bar=1` 与 `MaOpen_SignalBar` 对比。
  - `EMA(close, 20)` 的 `bar=1` 与 `MaClose_SignalBar` 对比。
- 当两组比较同时向上时做多，同时向下时做空。
- 已有持仓后：
  - 若 `EMA(70)` 方向反转，则平仓。
  - 若启用 `TrailingStop/TrailingStep`，则按价格推进 trailing。
  - 同时保留固定 `SL/TP`。

## 参数映射
- `InpLots=0.10`
- `InpStopLoss=50`
- `InpTakeProfit=150`
- `InpTrailingStop=5`
- `InpTrailingStep=5`
- `MaClose_ma_period=20`
- `MaClose_ma_shift=0`
- `MaClose_ma_method=MODE_EMA`
- `MaClose_applied_price=PRICE_CLOSE`
- `MaClose_SignalBar=0`
- `MaOpen_ma_period=70`
- `MaOpen_ma_shift=0`
- `MaOpen_ma_method=MODE_EMA`
- `MaOpen_applied_price=PRICE_CLOSE`
- `MaOpen_SignalBar=0`
- `m_magic=37826789`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Base bar shift：`15` 分钟

## 对齐说明
- 原版通过 `CalculateAllPositions()==0` 限制任意时刻只有一笔仓位；迁移版保持同样单仓语义。
- 原源码里 `ma_close_signal_bar = iMAGet(handle_iMAOpen, MaClose_SignalBar)`，也就是 `MaClose` 的信号位读取仍然来自 `MAOpen` 句柄；迁移版按源码字面保留这一行为，并在此明确记录。
- trailing 在原版中通过 `PositionModify(ticket, ...)` 推进；迁移版以单仓内部止损阈值近似复现。
- 当前目录已完成可运行迁移，详细回测结果待后续通过非 `python` 类命令补录。
