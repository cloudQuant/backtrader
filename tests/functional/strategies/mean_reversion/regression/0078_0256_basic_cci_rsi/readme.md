# 0256 基础 CCI RSI

## 策略来源

- MT5 源码：`ea/0256_基础_CCI_RSI/basic_cci_rsi.mq5`

## 策略逻辑

- 新柱出现时同时检查 `CCI` 和 `RSI`。
- 买入条件：`RSI > RSI_level_up` 且 `CCI > CCI_level_up`。
- 卖出条件：`RSI < RSI_level_down` 且 `CCI < CCI_level_down`。
- 条件满足时按固定手数开仓。
- 支持固定 `SL/TP` 和 trailing stop。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `CCI + RSI` 双阈值确认、固定 `SL/TP` 与 trailing stop 主流程。
- 原说明示例为 `EURUSD M15`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_basic_cci_rsi.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
