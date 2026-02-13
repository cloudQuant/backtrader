# DOGS/USDT 布林带策略 - 快速参考

## 重要提示

**交易对**: DOGS/USDT **现货交易**（仅做多，无合约）

---

## 快速启动

```bash
# 1. 配置API密钥（在 .env 文件中）
OKX_API_KEY=your_key
OKX_SECRET=your_secret
OKX_PASSWORD=your_password

# 2. 检查配置
python check_okx_config_simple.py

# 3. 测试数据加载
python test_dogs_data.py

# 4. 运行策略
python examples/backtrader_ccxt_okx_dogs_bollinger.py
```

---

## 策略参数速查表

### 核心参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 交易对 | DOGS/USDT | 现货交易 |
| 下单金额 | 0.4 USDT | 每次 |
| K线 | 1分钟 | 实时 |
| 布林带 | 60周期, 2倍标准差 | BB |
| ATR止损 | 14周期, 2倍ATR | 止损 |
| 交易方向 | 仅做多 | 现货限制 |

### 可调整参数

```python
cerebro.addstrategy(
    BollingerBandsStrategy,
    period=60,              # 布林带周期
    devfactor=2.0,          # 标准差
    order_size=0.4,         # 下单金额(USDT)
    atr_period=14,          # ATR周期
    atr_mult=2.0,           # 止损倍数
    log_bars=True,          # 是否输出bar信息
)
```

---

## Bar输出信息解读

每个bar会显示：

```
Bar #200 | Time: 2026-01-20 15:40:00
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Price:          开高低收价格
Bollinger Bands:   上下轨、中轨、带宽
ATR:              波动率
Position:         持仓、入场价、浮亏、止损
Signals:         当前交易信号
```

### 关键指标说明

**布林带带宽**:
- < 10%: 收缩震荡，可能突破
- 10-20%: 正常波动
- > 20%: 扩张波动，趋势强

**BB位置**:
- < 20%: 超卖区（可能反弹）
- 20-80%: 中性区
- > 80%: 超买区（可能回调）

---

## 交易信号一览表

### 现货做多逻辑

| 条件 | 仓位 | 动作 |
|------|------|------|
| 价格 > 上轨 | 空 | 开多 |
| 价格 < 下轨 | 多 | 平多 |
| 价格 ≤ 止损价 | 多 | 止损平仓 |

---

## 手数计算

```python
# 理论数量
理论数量 = 0.4 / 当前价格

# DOGS示例 (价格 $0.00004)
理论数量 = 0.4 / 0.00004 = 10,000
实际下单 = int(10000) = 10,000 DOGS

# 确保 >= 1
if 实际下单 < 1:
    实际下单 = 1
```

---

## 常见调整

### 保守策略（减少交易）

```python
period=80,              # 更长周期
devfactor=2.5,          # 更宽的带宽
atr_mult=2.5,           # 更宽的止损
```

### 激进策略（增加交易）

```python
period=40,              # 更短周期
devfactor=1.5,          # 更窄的带宽
atr_mult=1.5,           # 更紧的止损
```

---

## 风险控制

### 内置

1. **ATR动态止损**: 自适应调整
2. **固定下单金额**: 0.4 USDT/次
3. **持仓限制**: 同时只持有一个仓位

### 建议

1. **每日最大交易次数**: 10次
2. **每日最大亏损**: 2 USDT
3. **账户总止损**: 50% 资金
4. **避开重大新闻**: 发布前后不交易

---

## 性能优化建议

### 1. 参数优化

使用历史数据回测优化参数：

```python
cerebro.optstrategy(
    BollingerBandsStrategy,
    period=[40, 60, 80],
    devfactor=[1.5, 2.0, 2.5],
    atr_mult=[1.5, 2.0, 2.5],
)
```

### 2. 过滤条件

添加在 `next()` 方法开头：

```python
# 成交量过滤
if self.data.volume[0] < self.data.volume[-1]:
    return

# 时间过滤
current_hour = datetime.now().hour
if 0 <= current_hour < 6:  # 凌晨不交易
    return

# 波动率过滤
if self.atr[0] < self.data.close[0] * 0.01:
    return
```

---

## 故障排查

### 问题1: 找不到DOGS/USDT交易对

**检查**: 确认交易对名称正确
```python
# 正确
dataname='DOGS/USDT'

# 错误
dataname='DOGS/USD:USDT'  # 不存在的合约
```

### 问题2: 手数太小

**解决**: 确保计算后至少为1
```python
if size < 1:
    size = 1
```

### 问题3: 日志太多

**解决**: 关闭详细输出
```python
log_bars=False
```

---

## 相关文档

- `DOGS_STRATEGY_UPDATE.md` - 详细更新说明
- `DOGS_BOLLINGER_STRATEGY_GUIDE.md` - 使用指南
- `DOGS_STRATEGY_FIX.md` - 问题修复总结

---

## 快速命令

```bash
# 测试策略（使用模拟数据）
python test_strategy_logic.py

# 运行策略（实盘）
python examples/backtrader_ccxt_okx_dogs_bollinger.py

# 检查配置
python check_okx_config_simple.py

# 测试数据加载
python test_dogs_data.py
```

---

## 交易示例输出

```
====================================================================================================
Bar #200 | Time: 2026-01-20 15:40:00
====================================================================================================
Price Information:
  Close:  $0.000040
Bollinger Bands:
  Upper: $0.000041
  Middle: $0.000040
  Lower: $0.000039
  BB Position: 50.0% (Neutral)

Trading Signals:
  >>> BUY SIGNAL (Break above upper band)
====================================================================================================

[LONG ENTRY] 突破上轨开多: 价格=$0.000040, 上轨=$0.000041, 数量=10000
[ORDER EXECUTED] 买入: 价格=$0.000040, 数量=10000, 金额=$0.40 USDT
```

---

## 现货 vs 合约对比

| 特性 | 现货 | 合约 |
|------|------|------|
| 双向交易 | ❌ 只能做多 | ✓ 支持多空 |
| 杠杆 | ❌ 无 | ✓ 有杠杆 |
| 风险 | ⚠️ 中等 | ⚠️⚠️⚠️ 高 |
| DOGS | ✓ 可用 | ❌ 不可用 |

**注意**: OKX 不提供 DOGS 永续合约，只能使用现货交易。

---

**更新日期**: 2026-01-20
**版本**: v3.0 - 现货做多版本
