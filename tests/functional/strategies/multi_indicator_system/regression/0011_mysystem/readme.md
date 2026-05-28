# 0264 MySystem

## 策略来源

- MT5 源码：`ea/0264_MySystem/mysystem.mq5`

## 策略逻辑

- EA 在无持仓时，读取 `BullsPower` 与 `BearsPower` 两根柱线的平均值。
- 令 `prev = (bears[1] + bulls[1]) / 2`，`curr = (bears[0] + bulls[0]) / 2`。
- 当 `prev < curr` 且 `curr < 0` 时开多。
- 当 `prev > curr` 且 `curr > 0` 时开空。
- 开仓附带固定 `SL/TP`。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `BullsPower + BearsPower` 平均值变化的信号判定与固定 `SL/TP` 主流程。
- 源码中注释掉了反向平仓逻辑，且仅在无仓时入场；当前实现沿用该行为，不主动反手。
- 原说明示例为 `EURUSD M15`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_mysystem.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
