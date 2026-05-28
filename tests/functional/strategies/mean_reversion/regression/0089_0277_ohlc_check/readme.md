# 0277 OHLC 检查

## 策略来源

- MT5 源码：`ea/0277_OHLC_检查/ohlc_check.mq5`

## 策略逻辑

- 仅在新柱线上处理信号。
- 若指定 `signal_shift` 柱线 `close > open`，则给出买入信号。
- 若指定 `signal_shift` 柱线 `close < open`，则给出卖出信号。
- `reverse_trade=true` 时，买卖信号互换。
- 仅当当前点差不超过 `spread_limit` 时允许开仓。
- 开仓附带固定 `SL/TP`；若持有反向仓位则先平仓。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `OHLC` 方向判定、反向模式与点差过滤主流程。
- 原 EA 同时支持固定手数与风险百分比；当前实现先使用固定手数近似验证可运行性。
- 原说明示例为 `EURUSD`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_ohlc_check.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
