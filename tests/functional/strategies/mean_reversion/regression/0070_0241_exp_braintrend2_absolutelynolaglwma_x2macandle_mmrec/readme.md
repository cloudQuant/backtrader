# 0241 Exp BrainTrend2 AbsolutelyNoLagLwma X2MACandle MMRec

## 策略来源

- MT5 源码：`ea/0241_Exp_BrainTrend2_AbsolutelyNoLagLwma_X2MACandle_MMRec/Exp_BrainTrend2_AbsolutelyNoLagLwma_X2MACandle_MMRec.mq5`
- 指标源码：`ea/0241_Exp_BrainTrend2_AbsolutelyNoLagLwma_X2MACandle_MMRec/BrainTrend2_V2.mq5`
- 指标源码：`ea/0241_Exp_BrainTrend2_AbsolutelyNoLagLwma_X2MACandle_MMRec/AbsolutelyNoLagLwma.mq5`
- 指标源码：`ea/0241_Exp_BrainTrend2_AbsolutelyNoLagLwma_X2MACandle_MMRec/X2MACandle.mq5`
- 指标源码：`ea/0241_Exp_BrainTrend2_AbsolutelyNoLagLwma_X2MACandle_MMRec/X2MA.mq5`

## 策略逻辑

- EA 由三个子系统组成：
  - `A = BrainTrend2_V2`
  - `B = AbsolutelyNoLagLwma`
  - `C = X2MACandle`
- 任一子系统在其信号周期发生方向切换时，都可以触发对应方向开仓。
- 三个子系统分别维护自己的 `MMRec` 参数：当最近同方向连续亏损达到阈值后，下一笔仓位从常规 `MM` 切到 `SmallMM`。
- 当前 backtrader 实现使用 `M15` 执行周期，并重采样得到 `H6` 信号周期。

## 与源码一致/差异说明

- 保留了 `BrainTrend2_V2`、`AbsolutelyNoLagLwma`、`X2MACandle` 三系统、固定 `SL/TP`、反手和 `MMRec` 主流程。
- `BrainTrend2_V2` 与 `AbsolutelyNoLagLwma` 当前版本按本地源码公式做直接 Python 近似转写。
- `X2MACandle` 当前版本忠实覆盖默认第一层 `SMA` 路径，并用本地递推式低滞后平滑近似第二层 `JJMA`。
- MT5 原版通过不同 `magic` 允许 `A/B/C` 子系统各自独立持仓；当前 backtrader 迁移框架仍是单净头寸模型，因此这里采用“同一时刻只保留一笔当前激活子系统仓位”的近似实现；当同一信号柱上多个子系统同时给出开仓信号时，当前实现按 EA 主循环顺序使用 `A -> B -> C` 的优先级。
- `MMRec` 的底层 `TradeAlgorithms.mqh` 细节仓库中未提供，当前版本按“同方向连续亏损计数达到阈值时切换到 `SmallMM`，盈利后恢复 `MM`”进行近似还原。
- 原 readme 示例场景为 `EURJPY H6`，当前仓库没有对应 CSV，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `H6` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_braintrend2_absolutelynolaglwma_x2macandle_mmrec.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H6` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
