# 0304 Breakdown

## 策略来源

- MT5 源码：`ea/0304_突破/breakdown.mq5`

## 策略逻辑

- 每个新交易日删除旧挂单。
- 以上一交易日最高价加 `min_distance` 放置 `Buy Stop`。
- 以上一交易日最低价减 `min_distance` 放置 `Sell Stop`。
- 任一方向成交后，取消另一侧挂单。
- 持仓保留固定止损止盈与盈利后 trailing。

## 与源码一致/差异说明

- 保留了前日高低点双向 OCO 突破、成交后撤销另一侧挂单和 trailing 主流程。
- 原 EA 使用按风险百分比计算手数；当前版本先按固定手数近似运行，保持与当前迁移框架一致。
- 当前回测使用仓库可用的 `XAUUSD_M15.csv` 数据进行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_breakdown.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
