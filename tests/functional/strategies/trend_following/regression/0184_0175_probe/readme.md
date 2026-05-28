# 0175 探索

## 策略来源

- MT5 源码：`ea/0175_探索/probe.mq5`

## 策略逻辑

- 使用高周期 `CCI` 作为信号源；当 `CCI` 从超跌区向上回穿 `-cci_max_min` 时，设置 `Buy Stop` 挂单。
- 当 `CCI` 从超买区向下回穿 `+cci_max_min` 时，设置 `Sell Stop` 挂单。
- 挂单价格位于当前执行价格外侧 `indent_pips`。
- 若价格远离挂单超过 `1.5 * indent_pips`，则删除未触发挂单。
- 仓位触发后保留固定止损和 trailing stop 主流程。

## 与源码一致/差异说明

- 保留了源码里的 `CCI(H4)` 过滤、单挂单生命周期管理和 trailing 逻辑。
- MT5 原版在逐 tick 上监控挂单与 trailing；当前 backtrader 版本按 bar 级近似。
- 原版示例品种为 `EURUSD M30`，当前仓库没有对应原始数据，因此这里使用 `XAUUSD_M15.csv` 并重采样出 `H4` 信号层做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_probe.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
