# 0424 EMA_WMA_v2

## 策略来源
- MT5 EA: `ea/0424_EMA_WMA_v2/ema_wma_v2.mq5`
- Backtrader 实现: `examples/0424_ema_wma_v2/strategy_ema_wma_v2.py`
- 运行脚本: `examples/0424_ema_wma_v2/run.py`

## 核心逻辑
- 使用 `EMA(28, open)` 与 `WMA(8, open)` 的新柱交叉作为切换方向信号。
- 当 `EMA0 < WMA0` 且 `EMA1 > WMA1` 时做多。
- 当 `EMA0 > WMA0` 且 `EMA1 < WMA1` 时做空。
- 按源码流程，出现新方向信号时先关闭反向持仓，再切换到新方向。
- 持仓后保留固定止损、固定止盈与尾随止损逻辑。

## 参数映射
- `period_EMA=28`
- `period_WMA=8`
- `InpStopLoss=50`
- `InpTakeProfit=50`
- `InpTrailingStop=50`
- `InpTrailingStep=10`
- `risk=10`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Bar shift：`15` 分钟

## 回测结果
- 初始资金：`100000.00`
- 期末权益：`3.20`
- 净收益：`-99996.80`
- 收益率：`-100.00%`
- 平仓交易数：`207`
- 胜率：`48.79%`
- Profit Factor：`0.77`
- 最大回撤：`100.00%`
- Sharpe：`9.79`

## 对齐说明
- MT5 原版按 `risk / margin_required` 动态计算手数；Backtrader 版本按当前现金、风险百分比和每手保证金做近似复现。
- 当前默认参数在 `XAUUSD_M15` 回测下杠杆非常激进，因此虽然策略可运行，但资金曲线很容易快速衰减。
- 迁移版本采用单品种、单净仓语义，不复现 MT5 逐 ticket 管理细节。
