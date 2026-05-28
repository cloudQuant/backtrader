# 0293 GBP9AM

## 策略来源

- MT5 源码：`ea/0293_GBP9AM/gbp9am.mq5`

## 策略逻辑

- 每天在 `look_price_hour:look_price_minute` 同时放置一组 `Buy Stop / Sell Stop` 突破挂单。
- 买入挂单和卖出挂单分别使用不同的入场距离与 `SL`，共享 `TP`。
- 任一方向成交后，撤掉另一侧挂单。
- 若启用 `use_close_hour`，到 `close_hour` 时统一平仓并撤单。

## 与源码一致/差异说明

- 保留了固定时刻双向突破挂单、单边成交后撤另一边、收盘小时统一清仓撤单的主流程。
- 原说明建议 GBPUSD 且时间按伦敦 9AM 调整，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。
- 当前 backtrader 实现以 bar 级别近似挂单触发与撤单过程。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_gbp9am.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
