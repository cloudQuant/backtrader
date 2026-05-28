# 0361 JS-MA-Day

## 策略来源

- MT5 源码：`ea/0361_JS-MA-Day/js-ma-day.mq5`
- 当前实现：`examples/0361_js_ma_day/`

## 策略逻辑

- 以执行级别新柱为驱动，滚动维护“当前日 + 最近若干已完成日”的 `PRICE_MEDIAN` 日线状态。
- 使用默认 `D1 SMA(3)` 与当日/前一日开盘价关系识别多空形态：
  - `MA0 < MA1 <==> 当前日线仍弱于前一日，但 MA0 重新站回当日开盘价之上` 时做多。
  - 对称条件成立时做空。
- 开仓后保留固定 `SL/TP` 与 trailing stop，并在 `close_hour` 后尝试平掉现有仓位。

## 与源码一致/差异说明

- 当前迁移**仅覆盖默认 `InpIncrease=false` 的单仓路径**；原 EA 若启用 `InpIncrease=true`，会放宽为最多 `InpMaxPos` 笔加仓，该部分不纳入当前 Backtrader 版本。
- 原 EA 使用 `PERIOD_D1` 的 `SMA(PRICE_MEDIAN)` 与日开盘价形成信号；当前版本在 M15 数据上按日内累计的 `high/low/open` 实时合成“进行中日线”，以避免直接使用整日收盘后的未来信息。
- 原 EA 支持 `Risk` 驱动的 MT5 保证金换手数；当前迁移使用 `fixed_lot` 近似默认单仓回测语义。

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
