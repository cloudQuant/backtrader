# 0320 Gaps (缺口) — Backtrader 策略转换

## 原始 EA
- **来源**: `ea/0320_缺口/gaps.mq5`
- **作者**: SFK Corp
- **策略类型**: 缺口交易策略

## 策略逻辑
1. 每根新K线，比较当前K线的开盘价与前一根K线的最高/最低价
2. **做多信号**: 当前开盘价 < 前一根K线最低价 - Gap点数（向下跳空，预期回补）
3. **做空信号**: 当前开盘价 > 前一根K线最高价 + Gap点数（向上跳空，预期回补）
4. 单持仓模式，支持止损/止盈/移动止损

## 参数说明
| 参数 | 默认值 | 说明 |
|------|--------|------|
| fixed_lot | 0.1 | 固定手数 |
| stoploss_pips | 50 | 止损点数 |
| takeprofit_pips | 50 | 止盈点数 |
| trailing_stop_pips | 5 | 移动止损距离 |
| trailing_step_pips | 5 | 移动止损步长 |
| gap_pips | 1 | 缺口最小点数 |

## 运行方式
```bash
cd examples/0320_gaps
python run.py
python run.py --plot  # 带图表
```

## 完成说明
- 转换日期: 2025年
- 核心逻辑已完整迁移：缺口检测、止损/止盈、移动止损
- 使用 backtrader 的单持仓模型
