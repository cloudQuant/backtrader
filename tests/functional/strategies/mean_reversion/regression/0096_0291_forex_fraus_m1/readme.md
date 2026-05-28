# 0291 外汇 Fraus M1

## 策略来源

- MT5 源码：`ea/0291_外汇_Fraus_M1/forex_fraus_m1.mq5`

## 策略逻辑

- 仅在新柱线上开仓，trailing 在每个 tick 近似执行。
- 使用 `WPR`：超卖区买入，超买区卖出。
- 可启用时间窗口控制 `start_hour/end_hour`。
- 可选在信号出现时平掉反向仓 `close_opposite`。
- 开仓附带固定 `SL/TP` 和 trailing。

## 与源码一致/差异说明

- 保留了 `WPR` 超买/超卖、时间窗口、可选平反向仓与 trailing 主流程。
- 原说明示例为 `EURUSD M1`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_forex_fraus_m1.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
