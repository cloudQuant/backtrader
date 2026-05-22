# Band R Squared Donchian 当前线差异记录

## 现象

策略 `strategies/volatility_systems/0023_0105_band_r_squared` 的 Python 版本在
`runonce=False` 下，`DonchianChannel` 自定义指标通过以下方式绑定输出线：

```python
self.lines.upper = bt.indicators.Highest(self.data.high, period=self.p.period)
self.lines.lower = bt.indicators.Lowest(self.data.low, period=self.p.period)
```

实测 `_lower_rising()` 中 `self.donch.lower[0]` 为 `0.0`，而
`self.donch.lower[-1]` 等历史值为正常 Donchian lower。因此第一项比较：

```python
self.donch.lower[0] < self.donch.lower[-1]
```

通常直接为真，导致 `_lower_rising()` 返回 `False`，策略没有 buy 信号。

## 对转换的影响

按正常 Donchian 公式预计算时会出现 45 个原始 buy 信号，但 Python 策略实测原始
buy 信号为 0，最终回测为：

- `buy_count`: 0
- `sell_count`: 17
- `trade_count`: 17

C++ 转换为了匹配当前仓库 Python runner 的实际行为，显式保留 `buy_signal = false`，
并只按可触发的 sell 路径对齐。

## 建议

如果希望策略使用正常 Donchian current line 语义，需要由维护者决定是否修改 Python
自定义指标的实现方式，或显式改写 buy/sell 条件。当前转换不修改 Python/backtrader
源码，也不修改测试用例。
