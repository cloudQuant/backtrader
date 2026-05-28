# 0252 Ravi AO

## 策略来源

- MT5 源码：`ea/0252_Ravi_AO/ravi_ao.mq5`
- 指标源码：`ea/0252_Ravi_AO/ravi.mq5`

## 策略逻辑

- EA 在新柱上检查 `AO` 与 `RAVI`。
- 多头条件：`AO[2] < 0` 且 `RAVI[2] < 0`，然后 `AO[1] > 0` 且 `RAVI[1] > 0`。
- 空头条件：`AO[2] > 0` 且 `RAVI[2] > 0`，然后 `AO[1] < 0` 且 `RAVI[1] < 0`。
- 单次仅保留一笔仓位。
- 支持固定 `SL/TP` 和 trailing stop。
- 当前 backtrader 实现使用 `M15` 执行周期，并重采样为 `M30` 信号周期。

## 与源码一致/差异说明

- 保留了 `AO + RAVI` 双确认过零、单仓位、固定 `SL/TP` 与 trailing stop 主流程。
- `RAVI` 当前按 `100 * (FastEMA - SlowEMA) / SlowEMA` 做可运行近似。
- 原说明示例为 `EURUSD M30`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `M30` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_ravi_ao.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `M30` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
