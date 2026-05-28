# 0272 Ketty

## 策略来源

- MT5 源码：`ea/0272_Ketty/ketty.mq5`

## 策略逻辑

- 在 `Channel start/end` 时间窗口统计区间最高价与最低价。
- 若上一根 K 线先向下跌破 `channel_low - breakthrough`，则在 `channel_high + order_price_shift` 放置 `Buy Stop`。
- 若上一根 K 线先向上突破 `channel_high + breakthrough`，则在 `channel_low - order_price_shift` 放置 `Sell Stop`。
- 仅在 `Placing order start/end` 窗口内放单。
- 超出放单窗口后，未触发挂单会被删除。
- 挂单触发后附带固定 `SL/TP`。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了通道统计、突破确认、挂单放置和到期删单主流程。
- 原实现还会绘制通道矩形；当前 backtrader 版本不做图形对象复刻。
- 原说明示例为 `GBPUSD M15`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_ketty.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
