# 0317 Dematus — Backtrader 策略转换

## 原始 EA
- **来源**: `ea/0317_Dematus/dematus.mq5`
- **作者**: Vladimir Karputov (barabashkakvn's edition)
- **策略类型**: DeMarker 指标策略

## 策略逻辑
1. 使用 DeMarker 指标判断超买/超卖区域
2. **做多信号**: DeMarker[2] < 0.3 且 DeMarker[0] > 0.3（从超卖区域向上穿越0.3）
3. **做空信号**: DeMarker[2] > 0.7 且 DeMarker[0] < 0.7（从超买区域向下穿越0.7）
4. 止损 + 移动止损
5. 亏损后按系数增加手数

## 简化说明
原始EA支持多持仓累积（价格远离入场价Distance后可加仓）和权益追踪止损。
为适配backtrader单持仓模型，简化为单持仓模式，仅保留核心DeMarker信号逻辑。

## 参数说明
| 参数 | 默认值 | 说明 |
|------|--------|------|
| fixed_lot | 0.1 | 基础手数 |
| stoploss_pips | 999 | 止损点数 |
| trailing_stop_pips | 5 | 移动止损距离 |
| trailing_step_pips | 5 | 移动止损步长 |
| demarker_period | 13 | DeMarker周期 |
| coefficient | 2.0 | 亏损后手数倍数 |

## 运行方式
```bash
cd examples/0317_dematus
python run.py
python run.py --plot  # 带图表
```

## 完成说明
- 转换日期: 2025年
- 核心逻辑已迁移：DeMarker超买超卖信号、止损、移动止损、亏损加仓系数
- 简化：多持仓累积和权益追踪功能未迁移（backtrader单持仓限制）
