# 0355 Renko_Level_EA

## 策略来源

- MT5 源码：`ea/0355_Renko_Level_EA/renko_level_ea.mq5`
- 指标源码：`ea/0355_Renko_Level_EA/renko_level.mq5`
- 当前实现：`examples/0355_renko_level_ea/`

## 策略逻辑

- 基于 `Renko Level` 指标上轨台阶变化交易。
- 当上轨台阶上移时，平空并开多。
- 当上轨台阶下移时，平多并开空。
- 若开启 `reverse`，则反向解释上述信号。
- 当前迁移严格固定在单净仓约束下，仅保留 `increase=false` 语义，不支持源码中的加仓模式。

## 与源码一致/差异说明

- 当前版本按源码保留了 `Renko Level` 台阶变化触发开平仓的主流程。
- 源码允许在 `InpIncrease=true` 时继续加仓；该行为超出当前单净仓边界，因此本迁移仅覆盖默认的 `InpIncrease=false` 单仓语义。
- 原指标通过价格对离散砖块台阶的跃迁更新 `RenkoBufferUP/DOWN`；当前版本按同样的离散步长规则做近似。
- 原文示例为 `AUDUSD M1`；当前仓库没有对应数据，因此这里使用 `XAUUSD_M15` 做可运行验证。

## 首轮回测结果

- 数据区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 平仓笔数：`2011`
- 期末权益：`100625.90`
- 最大回撤：`9.26%`
- 多头开仓：`1006`
- 空头开仓：`1005`

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
