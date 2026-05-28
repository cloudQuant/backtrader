# 0262 Breadandbutter2

## 策略来源

- MT5 源码：`ea/0262_Breadandbutter2/breadandbutter2.mq5`

## 策略逻辑

- EA 基于 `ADX` 与 `AMA` 的当前值相对上一根的变化方向发出信号。
- 买入条件：`ADX[0] < ADX[1]` 且 `AMA[0] > AMA[1]`。
- 卖出条件：`ADX[0] > ADX[1]` 且 `AMA[0] < AMA[1]`。
- 出现信号时先平掉反向仓位，再按新方向入场。
- 开仓附带固定 `SL/TP`。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `ADX + AMA` 方向变化判定、反向平仓和固定 `SL/TP` 主流程。
- `ADX` 与 `AMA` 当前使用本地安全近似实现，避免内置指标在平盘段或短样本段触发异常。
- 原说明建议通过调整不等式方向和参数做搜索；当前版本先按源码默认方向关系做可运行验证。
- 原测试环境未随仓库提供原始品种数据，这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_breadandbutter2.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
