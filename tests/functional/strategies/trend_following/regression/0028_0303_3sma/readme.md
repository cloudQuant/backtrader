# 0303 3SMA

## 策略来源

- MT5 源码：`ea/0303_3sma/3sma.mq5`

## 策略逻辑

- 使用三条 `SMA`。
- 当 `ma1 > ma2 + spread` 且 `ma2 > ma3 + spread` 时做多。
- 当 `ma1 < ma2 - spread` 且 `ma2 < ma3 - spread` 时做空。
- 已持有多仓时，若 `ma1 < ma2 - spread/2` 则平多。
- 已持有空仓时，若 `ma1 > ma2 + spread/2` 则平空。
- 仅保留固定手数与单净仓近似。

## 与源码一致/差异说明

- 保留了三均线顺序排列入场和 `ma1/ma2` 半 spread 反向平仓主流程。
- 原 EA 在逐笔报价上执行；当前回测基于 bar close 驱动的 Backtrader 近似执行。
- 当前回测使用仓库可用的 `XAUUSD_M15.csv` 数据进行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_3sma.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
