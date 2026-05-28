# 0258 Exp XCCI Histogram Vol Direct

## 策略来源

- MT5 源码：`ea/0258_Exp_XCCI_Histogram_Vol_Direct/Exp_XCCI_Histogram_Vol_Direct.mq5`
- 指标源码：`ea/0258_Exp_XCCI_Histogram_Vol_Direct/XCCI_Histogram_Vol_Direct.mq5`

## 策略逻辑

- EA 基于 `XCCI_Histogram_Vol_Direct` 的颜色翻转交易。
- 当直方图颜色由下跌转上涨时开多；由上涨转下跌时开空。
- 出现反向颜色翻转时，先平当前仓位，再按新方向入场。
- 开仓附带固定 `SL/TP`。
- 当前 backtrader 实现使用 `M15` 执行周期，并重采样得到 `H4` 信号周期。

## 与源码一致/差异说明

- 保留了单 magic、单档资金、颜色翻转反手与固定 `SL/TP` 主流程。
- `XCCI_Histogram_Vol_Direct` 当前按 `CCI * Volume` 平滑序列的方向翻转做可运行近似。
- 原说明示例为 `USDJPY H2`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `H4` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_xcci_histogram_vol_direct.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H4` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
