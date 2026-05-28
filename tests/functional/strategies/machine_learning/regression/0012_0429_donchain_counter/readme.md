# 0429 Donchain counter

## 策略来源
- MT5 EA: `ea/0429_唐奇安_(Donchain)_顺势交易/donchain_counter.mq5`
- Backtrader 实现: `examples/0429_donchain_counter/strategy_donchain_counter.py`
- 运行脚本: `examples/0429_donchain_counter/run.py`

## 核心逻辑
- 使用 `H1 Donchian Channel(period=20)` 的上下轨变化作为入场触发。
- 若上一根 `upper` 高于前一根 `upper`，则开多。
- 若上一根 `lower` 低于前一根 `lower`，则开空。
- 策略始终只允许单一活跃仓位；若检测到超过 `1` 笔仓位，MT5 原版会直接报错返回。
- 新开仓后进入 `24` 小时冷却；持仓期间只执行基于当前 Donchian 通道边界的移动止损，不设置固定止盈。

## 参数映射
- `InpLots=1.0`
- `InpChannelPeriod=20`
- `InpChannelTimeFrame=PERIOD_H1`
- `last_trade_time + 24h` 冷却
- `50 * Point` 触发后按通道边界抬升/下移止损

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 信号周期：`H1`
- 基础执行周期：`M15`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Bar shift：`15` 分钟

## 回测结果
- 本轮已补齐可运行 Backtrader 实现与回测脚本。
- 由于本次会话遵循“不在终端直接调用 Python 命令”的工作约束，尚未在当前会话内执行回测，结果待后续补录。

## 对齐说明
- MT5 原版通过 `iCustom(..., "donchian_channel", period)` 读取 `H1` 通道上下轨；Backtrader 版本以 `H1` 重采样后的 `Highest(high, period)` / `Lowest(low, period)` 近似复现。
- MT5 原版持仓时只动态抬升或下移 `SL`，不设置固定 `TP`；迁移版本保留这一行为。
- 迁移版本采用单品种、单净仓语义，不复现任何异常多仓状态。 
