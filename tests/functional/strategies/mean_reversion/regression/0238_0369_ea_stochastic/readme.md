# 0369 EA Stochastic

## 策略来源

- MT5 源码：`ea/0369_随机振荡器_EA/ea_stochastic.mq5`
- 当前实现：`examples/0369_ea_stochastic/`

## 策略逻辑

- 读取 `Stochastic` 主线（`K=5, D=3, slowing=3`）并比较当前值与 `InpComparedBar` 指定的历史值。
- 当两个检查点都低于 `InpLevelUP=80` 时开多；当两个检查点都高于 `InpLevelDOWN=20` 时开空。
- 保留源码的单仓门控、固定 `SL/TP` 与 trailing stop 主流程。

## 与源码一致/差异说明

- 原 EA 的买卖条件看起来并不是典型的超买/超卖反转写法，而是直接按源码阈值判断迁移；当前版本不擅自重写为更“常见”的随机指标逻辑。
- 原 EA 支持 `Risk` 驱动的 MT5 保证金换手数；当前迁移使用 `fixed_lot` 近似默认单仓回测语义。
- 原版本在 `OnTick()` 入口先执行 trailing，再检查是否已有仓位；当前迁移保持相同顺序。

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
