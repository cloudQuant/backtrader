# 0426 Poker_SHOW

## 策略来源
- MT5 EA: `ea/0426_Poker_SHOW/poker_show.mq5`
- Backtrader 实现: `examples/0426_poker_show/strategy_poker_show.py`
- 运行脚本: `examples/0426_poker_show/run.py`

## 核心逻辑
- 每个新 `M15` bar 仅评估一次信号。
- 使用 `H1 EMA(24)` 作为趋势过滤层；默认要求均线与当前价格距离至少 `50` 点。
- 若 `Royal > MathRand()` 随机阈值成立，且趋势条件满足，则按方向做市价单。
- 仅允许单一净头寸；持仓后只依赖固定 `SL/TP` 出场，不做加仓、不挂单。

## 参数映射
- `Royal=royal_7 (16383)`
- `InpLots=0.10`
- `InpStopLoss=50`
- `InpTakeProfit=150`
- `In_BUY=true`
- `In_SELL=true`
- `InpDistanceMAandPrice=50`
- `InpMA_trend_period=H1`
- `InpMA_trend_ma_period=24`
- `InpMA_trend_ma_method=EMA`
- `InpMA_trend_applied_price=CLOSE`
- `InpReverseSignal=false`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Base bar shift：`15` 分钟
- 信号层：重采样为 `H1`

## 对齐说明
- MT5 原版通过 `MathRand()` 决定本 bar 是否允许入场；迁移版使用固定 `rng_seed=42` 的伪随机序列，以保证回测结果可重复。
- MT5 在 `InpMA_trend_period=H1` 上读取 `iMA(..., shift=1)`；迁移版改为使用独立 `H1` 信号层的最近已完成 bar 近似复现。
- MT5 原版对 `ask/bid` 与均线做距离过滤；迁移版在 bar 级回测中使用当前收盘价近似该判断。
- 当前目录已完成可运行迁移，详细回测结果待后续通过非 `python` 类命令补录。
