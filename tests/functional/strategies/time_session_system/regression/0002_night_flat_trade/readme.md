# 0381 夜间横盘交易 — Backtrader 迁移

## 原始 EA
- 文件：`ea/0381_夜间横盘交易/night_flat_trade.mq5`
- 类型：夜间窄幅震荡区间策略

## 策略逻辑
1. 原版限定在 `EURUSD H1` 上运行
2. 仅在 `OpenHour ~ OpenHour+1` 夜间时段寻找入场机会
3. 统计最近 `3` 根 H1 K 线的最高价与最低价，计算区间宽度 `diff`
4. 若 `diff` 处于 `DiffMin ~ DiffMax` 之间、当前无多空仓，且当前价落在区间下四分之一区域，则做多
5. 若 `diff` 处于 `DiffMin ~ DiffMax` 之间、当前无多空仓，且当前价落在区间上四分之一区域，则做空
6. 止损设为区间边界外 `diff/3`，止盈为固定 `TakeProfit`，并使用固定 trailing 规则

## 参数映射

| MQL5 参数 | Backtrader 参数 | 默认值 | 说明 |
|-----------|----------------|--------|------|
| `InpTakeProfit` | `take_profit_pips` | 50 | 固定止盈 |
| `InpTrailingStop` | `trailing_stop_pips` | 15 | 尾随距离 |
| `InpTrailingStep` | `trailing_step_pips` | 5 | 尾随步长 |
| `InpDiffMin` | `diff_min_pips` | 100 | 最小区间宽度 |
| `InpDiffMax` | `diff_max_pips` | 400 | 最大区间宽度 |
| `InpOpenHour` | `open_hour` | 0 | 开仓时间窗口起点 |
| `InpLots` | `lots` | 0.10 | 固定手数 |
| `Risk` | `risk` | 5.0 | 风险百分比 |

## 当前简化
- 原版默认品种与周期为 `EURUSD H1`；由于仓库当前仅提供 `XAUUSD_M1.csv`，示例配置使用 `XAUUSD M1` 并重采样到 `H1` 做本地近似验证
- 为适配 `XAUUSD` 波动尺度，示例验证配置将 `point` 调整为 `0.1`，并把 `DiffMin/DiffMax` 放宽到 `100/400`，以近似原版在外汇点值体系下的夜间窄幅过滤语义
- `CMoneyFixedMargin` 资金管理未直接复刻；当前首轮验证使用固定 `lots=0.10`，保留单仓限制、固定 `TP` 与 trailing 主流程

## 首轮回测结果
- 数据：`XAUUSD_M1 -> H1`
- 区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 结果：共 `22` 笔平仓（`4` 笔多单、`18` 笔空单），胜率 `68.2%`，期末权益 `99905.80`

## 回测数据
- 品种：XAUUSD
- 执行周期：M1
- 信号周期：H1
- 数据文件：`examples/../../../datas/XAUUSD_M1.csv`

## 运行
```bash
cd examples/0381_night_flat_trade
python run.py
```
