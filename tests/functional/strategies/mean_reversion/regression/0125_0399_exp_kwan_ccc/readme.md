# 0399 Exp_KWAN_CCC — Backtrader 迁移

## 原始 EA
- 文件：`ea/0399_Exp_KWAN_CCC/Exp_KWAN_CCC.mq5`
- 指标：`ea/0399_Exp_KWAN_CCC/KWAN_CCC.mq5`
- 框架：`TradeAlgorithms.mqh` 单仓开/平模板

## 策略逻辑
1. **复合指标 KWAN_CCC**
   - 计算 `kwan_raw = Chaikin × CCI / Momentum`
   - 再做 `XMA` 平滑得到最终 KWAN 值
2. **方向判断**（在信号时间框架 H1 上）
   - `direction = 0`：上升（当前 > 前值）
   - `direction = 2`：下降（当前 < 前值）
   - `direction = 1`：持平
3. **交易信号**（SignalBar 偏移处取值）
   - 方向从 非0 变为 0 → BUY_Open + SELL_Close
   - 方向从 非2 变为 2 → SELL_Open + BUY_Close
4. **仓位管理**
   - 单仓模型，先平反向仓再开新仓
   - 固定 SL/TP（点数方式）

## 参数映射

| MQL5 参数 | Backtrader 参数 | 默认值 | 说明 |
|-----------|----------------|--------|------|
| `MM` | `mm` | 0.1 | 手数/资金比例 |
| `MMMode` | `mm_mode` | LOT | 固定手数模式 |
| `StopLoss_` | `stop_loss_points` | 1000 | 止损点数 |
| `TakeProfit_` | `take_profit_points` | 2000 | 止盈点数 |
| `BuyPosOpen` | `buy_pos_open` | true | 允许做多 |
| `SellPosOpen` | `sell_pos_open` | true | 允许做空 |
| `BuyPosClose` | `buy_pos_close` | true | 允许平多 |
| `SellPosClose` | `sell_pos_close` | true | 允许平空 |
| `fast_ma_period` | `fast_ma_period` | 3 | Chaikin 快周期 |
| `slow_ma_period` | `slow_ma_period` | 10 | Chaikin 慢周期 |
| `ma_method` | `ma_method` | LWMA | Chaikin 平滑类型 |
| `CCIPeriod` | `cci_period` | 14 | CCI 周期 |
| `CCIPrice` | `cci_price` | MEDIAN | CCI 价格类型 |
| `MomentumPeriod` | `momentum_period` | 7 | Momentum 周期 |
| `MomentumPrice` | `momentum_price` | CLOSE | Momentum 价格类型 |
| `XMA_Method` | `xma_method` | JJMA | 平滑方法 |
| `XLength` | `x_length` | 7 | 平滑深度 |
| `XPhase` | `x_phase` | 100 | 平滑参数 |
| `SignalBar` | `signal_bar` | 1 | 信号偏移柱数 |

## 当前简化
- 用固定 `lot` 替代原版 `TradeAlgorithms.mqh` 的账户级动态手数
- `TradeAlgorithms.mqh` 未直接引入，交易执行按单净仓语义内嵌实现
- `SmoothAlgorithms.mqh` 未直接引入；当前对 `XMA_Method=JJMA` 采用低滞后递推平滑近似，`MODE_SMA_` 则按简单移动平均实现

## 回测数据
- 品种：XAUUSD
- 执行周期：M15
- 信号周期：H1
- 数据文件：`examples/../../../datas/XAUUSD_M15.csv`

## 运行
```bash
cd examples/0399_exp_kwan_ccc
python run.py
```
