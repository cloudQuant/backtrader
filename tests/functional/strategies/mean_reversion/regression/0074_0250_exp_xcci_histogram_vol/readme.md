# 0250 Exp XCCI Histogram Vol

## 策略来源

- MT5 源码：`ea/0250_Exp_XCCI_Histogram_Vol/Exp_XCCI_Histogram_Vol.mq5`
- 指标源码：`ea/0250_Exp_XCCI_Histogram_Vol/XCCI_Histogram_Vol.mq5`

## 策略逻辑

- EA 基于 `XCCI_Histogram_Vol` 的颜色区间跃迁交易。
- 指标把 `CCI * Volume` 的平滑值分成五个区间：强买、普通买、中性、普通卖、强卖。
- 当颜色从 `1 -> >1` 触发普通买入，从 `0 -> >0` 触发强买入。
- 当颜色从 `3 -> <3` 触发普通卖出，从 `4 -> <4` 触发强卖出。
- 原版用两个 magic 与两档资金比例分别持仓；当前 backtrader 版本保留两档信号与不同入场手数，但采用单净头寸近似，同一时刻仅保留一笔仓位。
- 开仓附带固定 `SL/TP`。

## 与源码一致/差异说明

- 保留了颜色跃迁触发、两档信号强度与固定 `SL/TP` 主流程。
- 原版可按两个 magic 独立管理普通/强烈信号仓位；backtrader 版本将其近似为单净头寸，并按当次触发信号选择 `MM1` 或 `MM2`。
- 指标中的平滑算法当前采用可运行近似，不完整复刻自定义 `SmoothAlgorithms` 族；默认参数下可用于功能验证。
- 原说明示例为 `USDJPY H4`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `H4` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_xcci_histogram_vol.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H4` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
