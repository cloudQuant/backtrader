# 0417 FX-CHAOS_SCALP

## 策略来源
- MT5 EA: `ea/0417_FX-CHAOS_SCALP/fx-chaos_scalp.mq5`
- Backtrader 实现: `examples/0417_fx_chaos_scalp/strategy_fx_chaos_scalp.py`
- 运行脚本: `examples/0417_fx_chaos_scalp/run.py`

## 核心逻辑
- 任意时刻仅允许单一持仓；已有仓位时不再开新单。
- 入场信号来自三层条件组合：
  - `D1 ZigZag on Fractals` 给出大级别方向锚点。
  - `H1 ZigZag on Fractals` 与 `H1 AO` 过滤局部突破方向。
  - 当前主图 bar 的 `open/close` 穿越上一根 `H1` 的高低点时触发做多或做空。
- 出场仅保留固定 `SL/TP`，不做加仓、不挂单、不做票据级管理。

## 参数映射
- `InpLots=0.10`
- `InpStopLoss=50`
- `InpTakeProfit=50`
- `m_magic=312412559`
- `m_slippage=10`
- `ZZF_D1 = ZigZag on Fractals(PERIOD_D1, index=3)`
- `ZZF_H1 = ZigZag on Fractals(PERIOD_H1, index=2)`
- `AO = Awesome Oscillator(PERIOD_H1)`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Base bar shift：`15` 分钟
- 信号层：重采样为 `H1` 与 `D1`

## 对齐说明
- 原版 readme 明确说明“同一时间不可有一笔以上持仓”，迁移版按单净仓语义保留这一限制。
- `ZigZag on Fractals` 在 MT5 中通过自定义指标句柄读取 `D1 index=3` 和 `H1 index=2`；迁移版用“最近确认分形枢轴”近似复现该缓冲区读法。
- `AO` 采用 `H1 median price` 的 `SMA(5)-SMA(34)` 近似复现。
- 原源码在 `lFlagSellOpen` 分支中调用了 `OpenBuy(sl,tp)`，看起来是明显笔误；迁移版按策略意图实现为 `OpenSell`，并在此处记录差异。
- 当前目录已完成可运行迁移，详细回测结果待后续通过非 `python` 类命令补录。
