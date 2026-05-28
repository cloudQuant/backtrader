# 0384 AIS2 交易机器人 — Backtrader 迁移

## 原始 EA
- 文件：`ea/0384_AIS2_交易机器人/ais2_trading_robot.mq5`
- 类型：单品种、双时间框架区间突破系统

## 策略逻辑
1. 使用 `Timeframe_1` 的上一根 K 线高低点和均价定义突破方向
2. 若 `Close_1 > Average_1` 且当前价突破 `High_1`，则做多
3. 若 `Close_1 < Average_1` 且当前价跌破 `Low_1`，则做空
4. `Take/Stop` 基于 `Range_1 × Factor` 计算
5. `Trail` 基于 `Range_2 × TrailFactor` 计算
6. 仅在空仓时开仓；已有持仓时只做 trailing 与止盈止损管理
7. 下单手数按 `order_reserve × equity` 对单笔风险做近似换算

## 参数映射

| MQL5 参数 | Backtrader 参数 | 默认值 | 说明 |
|-----------|----------------|--------|------|
| `Inp_aed_AccountReserve` | `account_reserve` | 0.20 | 账户保留权益比例 |
| `Inp_aed_OrderReserve` | `order_reserve` | 0.04 | 单笔风险比例 |
| `aes_Symbol` | `symbol` | `EURUSD` | 交易品种 |
| `Inp_aei_Timeframe_1` | `signal_timeframe_1` | `M15` | 主信号周期 |
| `Inp_aei_Timeframe_2` | `signal_timeframe_2` | `M1` | trailing 周期 |
| `Inp_aed_TakeFactor` | `take_factor` | 1.7 | 止盈系数 |
| `Inp_aed_StopFactor` | `stop_factor` | 1.7 | 止损系数 |
| `Inp_aed_TrailFactor` | `trail_factor` | 0.5 | 尾随系数 |

## 当前简化
- 原版监控面板、全局变量面板和告警文本未迁移
- 下单手数按 `equity × order_reserve / (风险点数 × 每点合约价值)` 做近似，并结合 `contract_size`、`lot_step`、`lot_max` 约束，尽量贴近原版按单笔风险预算分配仓位的语义
- `FreezeLevel/StopsLevel` 约束未逐项复刻，当前保留核心突破、止盈止损与 trailing 语义
- 原版默认品种为 `EURUSD`；由于仓库当前仅提供 `XAUUSD_M1.csv`，示例运行配置改为 `XAUUSD` 本地数据近似验证框架行为，并将 `point=0.01`、`contract_size=100`、`multiplier=100` 作为本地回测口径

## 首轮回测结果
- 数据：`XAUUSD_M1 -> M15/M1`
- 区间：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- 结果：共 `1727` 笔平仓（`1025` 笔多单、`703` 笔空单），胜率 `83.8%`，期末权益 `141093.76`

## 回测数据
- 品种：XAUUSD
- 执行周期：M1
- 信号周期：M15 + M1
- 数据文件：`examples/../../../datas/XAUUSD_M1.csv`

## 运行
```bash
cd examples/0384_ais2_trading_robot
python run.py
```
