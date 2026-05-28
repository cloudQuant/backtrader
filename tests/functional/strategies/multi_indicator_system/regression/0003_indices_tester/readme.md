# 0015 Indices Tester

## 策略概述

该策略是对 MT5 EA `0015_指数测试仪/indices_tester.mq5` 的 backtrader 迁移版本。
当前版本用现有的 `XAUUSD_M1.csv` 做可运行回测样例，但原 EA 文档中的测试标的是 `US30`。

该策略的核心特点：

- 只做多
- 仅在指定时间窗口内尝试进场
- 每个交易日限制成交次数
- 每个品种限制未平仓数量
- 到指定时间统一平仓
- 不使用固定止损止盈

## 核心逻辑

1. 读取三个时间参数：
   - `time_start`
   - `time_end`
   - `time_close`
2. 如果当前时间位于开仓窗口内，并且：
   - 当前没有持仓
   - 当前未超过每日成交次数限制
   - 当前未超过单品种持仓数量限制
   则开一笔多单
3. 到 `time_close` 后，将当前未平仓多单全部平掉
4. 下一交易日重新开始计数

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `comentar`
- `time_start`
- `time_end`
- `time_close`
- `lots`
- `limit_open_pos_sym`
- `daily_num_positions`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M1.csv`

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 原 EA 说明文档提到默认测试标的是 `US30`，当前仓库未提供对应数据，因此先使用 `XAUUSD M1` 作为可运行迁移样例
- 当前版本重点保留“只做多 + 时间窗口开仓 + 收盘时间统一平仓 + 每日次数限制”的主流程
