# 0301 CCI and Martin (CCI 和马丁) — Backtrader 策略转换

## 原始 EA
- **来源**: `ea/0301_CCI_和马丁/cci_and_martin.mq5`
- **作者**: Voloshin Yuri (barabashkakvn's edition)
- **策略类型**: CCI 指标 + K线形态 + 可选马丁格尔加仓

## 策略逻辑
1. 使用 CCI (Commodity Channel Index) 指标判断趋势反转
2. **做多信号**:
   - CCI[1] < 5, CCI下降后反转上升 (CCI[2]<CCI[3], CCI[1]<CCI[2], CCI[0]>CCI[1])
   - Bar#2 阴线, Bar#1 阴线, Bar#0 阳线, Bar#1开盘价 < Bar#0收盘价
3. **做空信号**:
   - CCI[1] > -5, CCI上升后反转下降
   - Bar#2 阳线, Bar#1 阳线, Bar#0 阴线, Bar#1开盘价 > Bar#0收盘价
4. **马丁格尔**: 亏损后按系数增加手数（最多N次）

## 参数说明
| 参数 | 默认值 | 说明 |
|------|--------|------|
| fixed_lot | 0.1 | 基础手数 |
| stoploss_pips | 20 | 止损点数 |
| takeprofit_pips | 50 | 止盈点数 |
| trailing_stop_pips | 5 | 移动止损距离 |
| trailing_step_pips | 15 | 移动止损步长 |
| cci_period | 27 | CCI周期 |
| use_martin | true | 是否使用马丁格尔 |
| martin_coeff | 3.0 | 马丁格尔系数 |
| martin_max_multiplications | 3 | 最大加倍次数 |

## 运行方式
```bash
cd examples/0301_cci_and_martin
python run.py
python run.py --plot  # 带图表
```

## 完成说明
- 转换日期: 2025年
- 核心逻辑已完整迁移：CCI信号、K线形态确认、止损/止盈、移动止损、马丁格尔加仓
- 使用 backtrader 的单持仓模型
