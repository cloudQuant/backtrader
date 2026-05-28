# 0266 JS MA SAR Trades

## 策略来源

- MT5 源码：`ea/0266_JS_MA_SAR_Trades/js_ma_sar_trades.mq5`

## 策略逻辑

- 使用 `ZigZag` 极值关系、`SAR` 与两条均线组合信号。
- 多头开仓：最近 `ZigZag Low 0 > Low 1`，`Fast MA > Slow MA`，且 `Close > SAR`。
- 空头开仓：最近 `ZigZag High 0 < High 1`，`Fast MA < Slow MA`，且 `Close < SAR`。
- 平仓信号不再要求均线，仅要求对应 `ZigZag` 结构仍成立且 `Close` 穿越 `SAR`。
- 可选启用时间窗口，仅在指定小时区间处理信号。
- 开仓附带固定 `SL/TP`，并带 trailing stop。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `SAR + MA + ZigZag` 组合信号、时间窗口与 trailing 主流程。
- 原 `Examples\\ZigZag` 当前以本地 pivot 近似实现，不是逐点复刻原 ZigZag 缓冲输出。
- 原说明示例为 `EURUSD M15`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_js_ma_sar_trades.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
