# 1123 Renko_Line_Break_vs_RSI_EA

## 策略概述

该策略是对 MT5 `RenkoLineBreakVsRSI_EA` 的 Backtrader 迁移版本。

原 EA 依赖自定义指标 `RenkoLineBreak` 判断趋势方向，再结合 `RSI` 在超买/超卖区域的状态，放置顺趋势的 `BUY_STOP/SELL_STOP` 挂单。当前示例已根据仓库中的指标源码 `indicators/3965_Renko_线突破/renkolinebreak.mq5` 重建其核心 box 逻辑，并复现挂单重挂与条件离场规则。

## 交易逻辑

- `RenkoLineBreak` 判断当前是 `UP / DOWN / TO_UP / TO_DOWN`
- 当趋势为 `UP` 且 `RSI < 50 - rsi_vertical_shift` 时，准备 `BUY_STOP`
- 当趋势为 `DOWN` 且 `RSI > 50 + rsi_vertical_shift` 时，准备 `SELL_STOP`
- 若挂单未触发且下一根仍满足条件，则按最近三根已完成柱重新计算触发价和止损位
- 若趋势出现 `TO_UP / TO_DOWN` 反转，则取消未触发挂单
- 持仓后：
  - 多单在 `TO_DOWN` 或 `RSI` 进入超买区域时平仓
  - 空单在 `TO_UP` 或 `RSI` 进入超卖区域时平仓

## 风控逻辑

- 触发价基于最近三根已完成柱的高低点，并附加 `indent_from_hl`
- 止损基于最近三根柱的极值再加/减 `indent_from_hl`
- 固定 `take_profit`
- 固定手数 `volume`

## 文件

- `strategy_renko_line_break_vs_rsi_ea.py` - 指标重建、挂单管理与交易实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 说明

- 原始 MT5 EA 使用真正的 `BUY_STOP/SELL_STOP` 挂单与实时 `Bid/Ask`；Backtrader 版本采用 bar 级近似，保留“挂单待触发、条件变化重挂、趋势反转撤销”的核心思想
- `spread_points` 默认为 `0.0`；如需更贴近原 EA，可在配置中加入固定点差近似

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`min_box_size=500`、`rsi_period=4`、`rsi_vertical_shift=20`、`take_profit=1000`、`indent_from_hl=50`、`volume=1.0`
- 信号次数：`69`
- 已平仓交易：`69`
- TradeAnalyzer 统计交易：`69`
- 胜率：`59.42%`
- 期初资金：`100000.00`
- 期末现金：`102112.00`
- 期末权益：`102112.00`
- 净收益：`2112.00`
- 最大回撤：`5.04%`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。当前 runner 使用统一 JSON 指标输出，未接入 `SQN` 分析器，因此本示例文档不单列 `SQN`。
