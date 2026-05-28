# 0318 Sidus — Backtrader 策略转换

## 原始 EA
- **来源**: `ea/0318_Sidus/sidus.mq5`
- **作者**: Dm_Michael
- **策略类型**: Alligator + RSI 趋势跟踪策略

## 策略逻辑
1. 使用 Williams Alligator 指标（Jaw/Teeth/Lips 三线）和 RSI 指标
2. **做多信号**: RSI 从下向上穿越50 且 Alligator 三条线均上升（差值 > delta）
   - 止损设置在前一根K线最低价 - offset
3. **做空信号**: RSI 从上向下穿越50 且 Alligator 三条线均下降（差值 < -delta）
   - 止损设置在前一根K线最高价 + offset
4. 可选：收到新信号时关闭反向持仓
5. 支持止盈和移动止损

## 参数说明
| 参数 | 默认值 | 说明 |
|------|--------|------|
| fixed_lot | 0.1 | 固定手数 |
| offset_pips | 3 | 止损偏移点数 |
| takeprofit_pips | 75 | 止盈点数 |
| trailing_stop_pips | 5 | 移动止损距离 |
| trailing_step_pips | 15 | 移动止损步长 |
| delta | 0.03 | Alligator线最小变化量 |
| close_opposite | false | 是否关闭反向持仓 |
| jaw_period | 13 | Alligator Jaw周期 |
| teeth_period | 8 | Alligator Teeth周期 |
| lips_period | 5 | Alligator Lips周期 |
| rsi_period | 14 | RSI周期 |

## 运行方式
```bash
cd examples/0318_sidus
python run.py
python run.py --plot  # 带图表
```

## 完成说明
- 转换日期: 2025年
- 核心逻辑已完整迁移：Alligator指标、RSI交叉信号、动态止损、移动止损
- 使用 backtrader 的单持仓模型
