# 0229 Exp XDeMarker Histogram Vol Direct

## 策略来源

- MT5 源码：`ea/0229_Exp_XDeMarker_Histogram_Vol_Direct/Exp_XDeMarker_Histogram_Vol_Direct.mq5`
- 指标源码：`ea/0229_Exp_XDeMarker_Histogram_Vol_Direct/XDeMarker_Histogram_Vol_Direct.mq5`

## 策略逻辑

- EA 使用 `XDeMarker_Histogram_Vol_Direct` 的方向颜色缓冲区作为交易触发。
- 当方向颜色从下行切换到上行时开多，并关闭空头。
- 当方向颜色从上行切换到下行时开空，并关闭多头。
- 使用固定 `MM`、固定 `SL/TP`。
- 当前实现用 `M15` 作为执行周期，并重采样得到 `H2` 信号周期。

## 与源码一致/差异说明

- 保留了 `DeMarker * Volume`、按阈值带宽计算方向和颜色翻转触发交易的主流程。
- 当前实现严格覆盖源码默认参数路径：`DeMarkerPeriod=14`、`VolumeType=VOLUME_TICK`、`MA_SMethod=MODE_SMA_`、`MA_Length=12`。
- 原指标底层通过 `SmoothAlgorithms.mqh` 的 `XMASeries` 提供多种平滑方式；当前 backtrader 版本只实现默认 `MODE_SMA_`，未覆盖 `JJMA/JurX/T3/VIDYA` 等扩展模式。
- 当前仓库没有原文档对应品种/周期数据，因此这里使用 `XAUUSD_M15.csv` 并重采样 `H2` 进行可运行验证。
- MT5 原版依靠 `magic` 区分订单；当前 backtrader 版本采用单净头寸近似。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_xdemarker_histogram_vol_direct.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H2` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
