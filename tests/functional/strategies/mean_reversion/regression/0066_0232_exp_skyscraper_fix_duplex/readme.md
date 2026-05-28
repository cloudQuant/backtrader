# 0232 Exp Skyscraper Fix Duplex

## 策略来源

- MT5 源码：`ea/0232_Exp_Skyscraper_Fix_Duplex/exp_skyscraper_fix_duplex.mq5`
- 指标源码：`ea/0232_Exp_Skyscraper_Fix_Duplex/skyscraper_fix.mq5`

## 策略逻辑

- EA 维护相互独立的多头/空头两个子系统，默认都使用 `H4` 周期的 `Skyscraper_Fix` 信号。
- `Skyscraper_Fix` 通过 `ATR(15)` 波动率窗口计算动态步长，并根据价格对上下阈值的突破切换趋势。
- 当指标从下行切换到上行时，`BuyBuffer` 出现值，多头子系统在下一执行 bar 开多。
- 当指标进入下行状态时，多头子系统平掉现有多单。
- 当指标从上行切换到下行时，`SellBuffer` 出现值，空头子系统在下一执行 bar 开空。
- 当指标进入上行状态时，空头子系统平掉现有空单。
- 当前实现使用 `M15` 作为执行周期，并重采样得到 `H4` 信号；入场时附带固定 `SL/TP`。

## 与源码一致/差异说明

- 保留了 `Skyscraper_Fix` 指标信号、分离的多空配置、固定 `SL/TP`、以及基于已完成高周期 bar 的开平仓主流程。
- MT5 源码通过 `TradeAlgorithms.mqh` 提供 `MarginMode` 与下单辅助函数；当前 backtrader 版本先按源码默认的 `LOT` 模式实现，因此默认参数可以直接对应。
- 原文示例品种为 `USDJPY H4`，当前仓库未提供对应数据，因此这里使用 `XAUUSD_M15.csv` 并在回测内重采样为 `H4` 信号周期。
- 由于 backtrader 采用净头寸模型，当前实现以“默认对称参数下的单净头寸行为”为主；若后续要支持更极端的多空参数分离组合，还需额外验证是否需要更细的子仓位抽象。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_skyscraper_fix_duplex.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H4` 后执行回测。
- `config.yaml`：策略参数、数据区间和回测配置。
