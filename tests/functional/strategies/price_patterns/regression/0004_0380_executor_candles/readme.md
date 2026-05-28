# 0380 Executor Candles

## 策略来源

- MT5 源码：`ea/0380_执行者蜡烛/executor_candles.mq5`
- 当前实现：`examples/0380_executor_candles/`

## 策略逻辑

- 仅在当前没有持仓时检查最近 `3` 根已完成 K 线的形态。
- 按源码顺序识别多头形态：`Hammer`、`Bull`、`Piercing`、`Morning Star`、`Morning Doji Star`。
- 若未命中多头形态，再继续识别空头形态：`Hanging Man`、`Bear`、`Dark Cloud Cover`、`Evening Star`、`Evening Doji Star`。
- 开仓后保留分方向固定 `SL/TP` 与 trailing stop。

## 与源码一致/差异说明

- 当前迁移**仅覆盖默认 `InpMainTimeframeOff=true` 的执行路径**；原 EA 可选接入更高时间框架蜡烛方向做过滤，当前版本未启用该附加过滤层。
- 原 EA 的所有形态函数都直接基于最近 `3` 根已完成蜡烛的布尔条件判断；当前版本逐条按源码公式迁移，没有改写成抽象的 TA-Lib 形态识别器。
- 原 EA 支持 `Risk` 驱动的 MT5 保证金换手数；当前迁移使用 `fixed_lot` 近似默认单仓回测语义。

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
