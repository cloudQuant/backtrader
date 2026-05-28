# 0284 Nextbar

## 策略来源

- MT5 源码：`ea/0284_Nextbar/nextbar.mq5`

## 策略逻辑

- 仅在新柱线上检查信号，trailing 在每个 tick 近似执行。
- 当 `close[1] - close[signal_bar] > min_distance` 时给出买入信号。
- 当 `close[signal_bar] - close[1] > min_distance` 时给出卖出信号。
- `reverse=true` 时，买卖信号互换。
- 仅在无持仓时允许开仓。
- 持仓达到 `lifetime_bars` 后强制平仓。
- 开仓附带固定 `SL/TP` 和 trailing。

## 与源码一致/差异说明

- 保留了 `Signal bar` 差值比较、反向模式、生命周期平仓和 trailing 主流程。
- 原说明示例为 `EURUSD H1`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_nextbar.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
