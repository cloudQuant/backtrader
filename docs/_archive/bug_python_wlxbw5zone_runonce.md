# WlxBW5Zone Python runonce 差异记录

## 现象

策略 `strategies/volatility_systems/0027_0838_wlxbw5zone` 在 Python 默认
`run.py` 路径下使用 `cerebro.run()`，也就是 backtrader 默认的 `runonce=True`。
该路径的实测结果：

- `bar_num`: 5448
- `signal_count`: 0
- `trade_count`: 0
- `final_value`: 1000000.0

同一策略改用 `cerebro.run(runonce=False)` 后，实测结果变为：

- `bar_num`: 5448
- `signal_count`: 34
- `trade_count`: 33
- `final_value`: 1001091.3999999991

## 初步判断

`WlxBW5Zone` 是自定义 `bt.Indicator`，内部依赖：

- `bt.indicators.ATR(self.data, period=12)`
- `bt.indicators.AwesomeOscillator(self.data)`
- `self.ac = self.ao - bt.indicators.SMA(self.ao, period=5)`

默认 `runonce=True` 和流式 `runonce=False` 对该自定义指标输出线的处理不一致。
当前 C++ 转换按仓库的 Python `run.py` 默认行为对齐，因此保留空信号输出，
不尝试在策略转换中修复 Python backtrader 的 runonce 行为。

## 建议

如果希望该策略按流式路径产生 34 个信号和 33 笔交易，需要由维护者决定：

1. 是否修改 Python runner，显式使用 `cerebro.run(runonce=False)`。
2. 是否调查并修复 Python backtrader 对此类自定义指标的 `runonce=True` 计算路径。
3. 是否将 C++ 转换改为匹配流式语义，而不是当前仓库默认 runner 语义。
