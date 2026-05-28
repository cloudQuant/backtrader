# 0305 ZigZag EA

## 策略来源

- MT5 源码：`ea/0305_ZigZag_EA/zigzag_ea.mq5`

## 策略逻辑

- 使用 ZigZag 最近三个摆点构造通道。
- 取最近三摆点中的最新点作为 `room_0`，更早两点的高低构成通道上沿/下沿。
- 仅当通道宽度位于 `[min_corridor, max_corridor]` 且 `room_0` 落在通道内部时有效。
- 在上沿加 `n_pips` 放置 `Buy Stop`，在下沿减 `n_pips` 放置 `Sell Stop`。
- 依据 Fibo 比例从通道宽度推导止损止盈，并在持仓盈利后应用 trailing。

## 与源码一致/差异说明

- 保留了 ZigZag 三摆点通道、双向挂单、动态改单、Fibo 比例 SL/TP、时段过滤和 trailing 主流程。
- 原 EA 依赖 MT5 `Examples\\ZigZag` 指标；当前版本使用本地摆点确认逻辑代理 ZigZag 极值序列。
- 原 EA 支持按风险百分比或固定手数计算仓位；当前版本保持固定手数，以符合当前迁移框架。
- 为适配当前 `XAUUSD_M15` 数据尺度，`config.yaml` 中的 corridor 上下限做了放宽；策略结构未变，仅调整验证参数量级。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_zigzag_ea.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
