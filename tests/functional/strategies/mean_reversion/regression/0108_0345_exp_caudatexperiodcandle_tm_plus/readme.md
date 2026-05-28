# 0345 Exp_CaudateXPeriodCandle_Tm_Plus

## 策略来源

- MT5 源码：`ea/0345_Exp_CaudateXPeriodCandle_Tm_Plus/Exp_CaudateXPeriodCandle_Tm_Plus.mq5`
- 指标源码：`ea/0345_Exp_CaudateXPeriodCandle_Tm_Plus/CaudateXPeriodCandle.mq5`
- 当前实现：`examples/0345_exp_caudatexperiodcandle_tm_plus/`

## 策略逻辑

- 基于 `CaudateXPeriodCandle` 的尾状烛条颜色信号交易。
- 当前近似颜色含义：
  - `0/1` 视为下尾型多头触发区。
  - `5/6` 视为上尾型空头触发区。
  - `0/1/2` 视为空头平仓区。
  - `4/5/6` 视为多头平仓区。
- 保留固定 `SL/TP` 与 `TimeTrade/nTime` 的时间离场主流程。

## 与源码一致/差异说明

- 当前版本按源码结构保留了单指标尾状烛条信号与时间持仓离场主流程。
- `TradeAlgorithms` 库文件未直接收录在仓库中；当前迁移按同仓库内联同名函数的常见实现语义，采用单品种单仓开仓约束。
- 原 `CaudateXPeriodCandle` 为自定义平滑周期蜡烛指标；当前版本用“平滑 OHLC + 烛身位置/尾部类型”做可运行近似。
- 原文示例为 `GBPUSD H4`；当前仓库没有对应数据，因此这里使用 `XAUUSD_M15` 重采样到 `H4` 做可运行验证。

## 首轮回测结果

- 数据区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 平仓笔数：`55`
- 期末权益：`102934.80`
- 最大回撤：`2.17%`
- 多头开仓：`31`
- 空头开仓：`24`

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
