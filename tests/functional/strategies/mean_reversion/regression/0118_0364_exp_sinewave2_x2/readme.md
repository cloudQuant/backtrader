# 0364 Exp_Sinewave2_X2 — Backtrader 迁移

## 原始 EA
- 文件：`ea/0364_Exp_Sinewave2_X2/exp_sinewave2_x2.mq5`
- 指标：`ea/0364_Exp_Sinewave2_X2/sinewave2.mq5`
- 周期计算：`ea/0364_Exp_Sinewave2_X2/cycleperiod.mq5`
- 交易框架：`TradeAlgorithms.mqh` 单仓开/平模板

## 策略逻辑
1. 在慢周期 `H6` 上计算 `Sinewave2`，用 `signal_line` 与 `main_line` 的相对位置判定大方向
2. 在快周期 `M30` 上计算第二组 `Sinewave2`
3. 当慢周期偏多时，若快周期 `signal_line` 从上向下穿越 `main_line`，则做多
4. 当慢周期偏空时，若快周期 `signal_line` 从下向上穿越 `main_line`，则做空
5. 若启用趋势平仓，则慢周期翻向时先平掉反向持仓
6. 执行层维持单净仓模型，并按固定 `SL/TP` 管理仓位

## 参数映射

| MQL5 参数 | Backtrader 参数 | 默认值 | 说明 |
|-----------|----------------|--------|------|
| `MM` | `fixed_lot` | 0.1 | 固定手数路径 |
| `StopLoss_` | `stop_loss_points` | 1000 | 止损点数 |
| `TakeProfit_` | `take_profit_points` | 2000 | 止盈点数 |
| `Alpha` | `alpha_slow` | 0.07 | 慢周期 Sinewave2 系数 |
| `Alpha_` | `alpha_fast` | 0.07 | 快周期 Sinewave2 系数 |
| `BuyPosOpen` | `buy_pos_open` | true | 允许做多 |
| `SellPosOpen` | `sell_pos_open` | true | 允许做空 |
| `BuyPosClose` | `buy_pos_close_trend` | true | 慢周期翻空时平多 |
| `SellPosClose` | `sell_pos_close_trend` | true | 慢周期翻多时平空 |
| `BuyPosClose_` | `buy_pos_close_signal` | false | 快周期反向时平多 |
| `SellPosClose_` | `sell_pos_close_signal` | false | 快周期反向时平空 |
| `TimeFrame` | `slow_timeframe_minutes` | 360 | 慢周期 |
| `TimeFrame_` | `fast_timeframe_minutes` | 30 | 快周期 |

## 当前简化
- `TradeAlgorithms.mqh` 未直接引入，交易执行按单净仓语义本地实现
- 直接依据仓库内 `cycleperiod.mq5` 与 `sinewave2.mq5` 的核心公式重建指标，不依赖外部 `.ex5`
- 当前按默认固定手数路径迁移，未额外复现 `MMMode` 的资金占比手数分支
- 当前未复刻 `Sinewave2_Cloud_HTF` 视觉辅助绘图，仅保留 EA 实际使用的两条信号线

## 回测数据
- 品种：XAUUSD
- 执行周期：M15
- 慢周期：H6
- 快周期：M30
- 数据文件：`examples/../../../datas/XAUUSD_M15.csv`

## 运行
```bash
cd examples/0364_exp_sinewave2_x2
python run.py
```
