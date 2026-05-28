# 0327 Cloud Trade 2

## 来源

- EA 源码：`ea/0327_云交易_2/cloud1s_trade_2.mq5`
- 当前实现：`examples/0327_cloud_trade_2/`
- 回测数据：`examples/../../../datas/XAUUSD_M1.csv`

## 策略逻辑

- 使用 `Fractals` 与 `Stochastic` 两类信号，保持与源码一致的“任一卖出优先、否则任一买入”合成规则。
- 仅在空仓时允许开仓，并保留 `One day: one deal` 的日历限制。
- 入场后保留固定止损、止盈、尾随止损、最低货币利润平仓与最低点数利润平仓。

## 与源码一致/差异说明

- 保留了源码中的单仓限制：`OnTick()` 中若已存在当前 `magic` 持仓则不再开新仓。
- `Stochastic` 信号按源码条件近似：前一根已完成柱线位于超买/超卖区，并与主线形成指定方向关系。
- `Fractals` 信号按最近两次已确认分形的方向组合近似。
- 原 EA 依赖 MT5 逐笔报价和券商原生 `SL/TP` 修改；当前 Backtrader 版本使用 M1 柱线的 `high/low` 区间近似触发保护退出与 trailing 更新，用于完成单净仓迁移验证。

## 运行方式

```bash
python run.py
```

如需画图：

```bash
python run.py --plot
```
