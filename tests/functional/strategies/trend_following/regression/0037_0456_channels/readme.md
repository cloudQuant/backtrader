# 0456 Channels

## 策略来源
- MT5 EA: `ea/0456_通道/channels.mq5`
- Backtrader 实现: `examples/0456_channels/strategy_channels.py`
- 运行脚本: `examples/0456_channels/run.py`

## 核心逻辑
- 主图使用 `M15` 数据执行交易，信号来自重采样后的 `H1` 数据。
- 计算 `EMA(2, close)`、`EMA(2, open)` 与 `EMA(220, close)`，并基于 `EMA(220)` 构造 `0.3% / 0.7% / 1.0%` 三组包络线。
- 当 `EMA(2, close)` 自下向上穿越指定下轨/中轴/上轨时开多。
- 当 `EMA(2, open)` 自上向下穿越指定上轨/中轴/下轨时开空。
- 持仓后仅保留源码默认启用的尾随止损逻辑；源码默认止损和止盈均为 `0`，因此迁移版本也保持关闭。

## 参数映射
- `InpLots=0.1`
- `InpTrailingStopBuy=30`
- `InpTrailingStopSell=30`
- `InpTrailingStep=1`
- `InpUseHours=false`
- `H1 EMA(2)` + `H1 EMA(220)`
- `Envelopes deviations = 0.3 / 0.7 / 1.0`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Bar shift：`15` 分钟

## 回测结果
- 初始资金：`100000.00`
- 期末权益：`93918.90`
- 净收益：`-6081.10`
- 收益率：`-6.08%`
- 平仓交易数：`25`
- 胜率：`96.15%`
- Profit Factor：`N/A`
- 最大回撤：`11.67%`
- Sharpe：`-5.03`

## 对齐说明
- MT5 源码依赖 `iEnvelopes`，Backtrader 中改为以 `EMA(220)` 为基准手工构造百分比包络线，保持与原始偏离率一致。
- 策略严格限制为单净仓，不复现 MT5 平台层面的多 ticket 行为。
- 由于源码默认不设置固定止损/止盈，收益主要由尾随止损决定，回测表现受趋势段分布影响较大。
