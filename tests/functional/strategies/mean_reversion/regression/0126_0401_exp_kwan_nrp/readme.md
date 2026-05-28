# 0401 Exp_KWAN_NRP — Backtrader 迁移

## 原始 EA
- 文件：`ea/0401_Exp_KWAN_NRP/Exp_KWAN_NRP.mq5`
- 指标：`ea/0401_Exp_KWAN_NRP/KWAN_NRP.mq5`
- 框架：`TradeAlgorithms.mqh` 单仓开/平模板

## 策略逻辑
1. **复合指标 KWAN_NRP**
   - 计算 `kwan_raw = Stochastic_%D × RSI / MomentumOsc`
   - 用 SMA(`XLength`=3) 平滑得到最终 KWAN 值
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
| `InpKPeriod` | `k_period` | 5 | Stochastic K 周期 |
| `InpDPeriod` | `d_period` | 3 | Stochastic D 周期 |
| `InpSlowing` | `slowing` | 3 | Stochastic 减速 |
| `RSIPeriod` | `rsi_period` | 14 | RSI 周期 |
| `MomentumPeriod` | `momentum_period` | 14 | Momentum 周期 |
| `XLength` | `x_length` | 3 | XMA 平滑深度 |
| `SignalBar` | `signal_bar` | 1 | 信号偏移柱数 |

## 当前简化
- 用固定 `lot` 替代原版 `TradeAlgorithms.mqh` 的账户级动态手数
- `XMA_Method` 仅实现默认 SMA，未覆盖 JJMA/JurX/ParMA/T3/VIDYA/AMA 等高级平滑方法
- `SmoothAlgorithms.mqh` 未直接引入，等效逻辑内嵌在策略指标类中

## 回测数据
- 品种：XAUUSD
- 执行周期：M15
- 信号周期：H1
- 数据文件：`examples/../../../datas/XAUUSD_M15.csv`

## 运行
```bash
cd examples/0401_exp_kwan_nrp
python run.py
```
