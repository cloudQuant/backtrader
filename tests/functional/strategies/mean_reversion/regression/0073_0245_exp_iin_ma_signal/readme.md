# 0245 Exp Iin MA Signal

## 策略来源

- MT5 源码：`ea/0245_Exp_Iin_MA_Signal/exp_iin_ma_signal.mq5`
- 指标源码：`ea/0245_Exp_Iin_MA_Signal/iin_ma_signal.mq5`

## 策略逻辑

- EA 基于 `Iin_MA_Signal` 箭头信号交易。
- 指标使用快慢均线交叉来生成买卖箭头。
- 出现买入箭头时开多并平空，出现卖出箭头时开空并平多。
- 开仓附带固定 `SL/TP`。
- 当前 backtrader 实现使用 `M15` 执行周期，并重采样得到 `H1` 信号周期。

## 与源码一致/差异说明

- 保留了 `Iin_MA_Signal` 的快慢均线交叉箭头、方向反手和固定 `SL/TP` 主流程。
- 当前版本按本地指标源码，用快慢均线交叉和 `ATR(10)` 风格的平均波幅偏移近似还原买卖箭头缓冲区。
- 原说明测试场景为 `USDJPY H4`，但源码默认指标时间框架为 `H1`；仓库当前没有对应品种数据，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `H1` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_iin_ma_signal.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H1` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
