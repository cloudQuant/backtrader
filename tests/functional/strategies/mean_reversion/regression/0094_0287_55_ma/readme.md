# 0287 55 MA

## 策略来源

- MT5 源码：`ea/0287_55_MA/55_ma.mq5`

## 策略逻辑

- 仅在指定交易时段内的新柱线上检查信号。
- 比较 `MA(bar_a)` 与 `MA(bar_b)`：
  - 若 `MA(bar_a) > MA(bar_b) + difference`，则产生买入信号。
  - 若 `MA(bar_a) < MA(bar_b) - difference`，则产生卖出信号。
- `reverse=true` 时，买卖信号互换。
- `close_opposite=true` 时，出现反向信号会先平掉反向仓。
- 开仓附带固定 `SL/TP`。

## 与源码一致/差异说明

- 保留了 55 周期 MA 的双 bar 比较、时间窗口、反向模式和可选平反向仓主流程。
- 原 EA 同时支持固定手数与风险百分比；当前实现先使用固定手数近似验证可运行性。
- 原说明示例为 `EURUSD H1`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_55_ma.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
