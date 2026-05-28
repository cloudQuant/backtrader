# 0397 Spasm

## 策略来源

- MT5 源码：`ea/0397_痉挛_(Spasm)/spasm.mq5`
- 当前实现：`examples/0397_spasm/`

## 策略逻辑

- 先在最近 `InpPeriod=24` 根柱上计算当前波动率，默认使用 `High-Low` 的简单滑动平均。
- 再把波动率乘以 `InpCoefficient=5.0` 形成动态阈值 `plech`，围绕最近高点/低点维护自适应翻转带。
- 当价格自下向上突破低带时做多；当价格自上向下跌破高带时做空。
- 每次翻向前先平掉旧仓，新仓只带基于波动率比例 `SL_pp` 的止损，不设置固定止盈。

## 与源码一致/差异说明

- 原 EA 通过 `trend + high_highest/low_lowest + plech` 维护单一净方向状态；当前版本保持相同的净仓翻转语义。
- 原源码支持 `InpExp` 线性权重与 `OpenClose` 波动口径切换；当前迁移保留这两个参数接口。
- MT5 版本直接按 `Bid/Ask` 与 `Spread` 约束最小止损距离；Backtrader 版本用数据内 `spread` 字段近似最小止损保护。

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
