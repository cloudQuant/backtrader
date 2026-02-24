# DOGS/USDT 策略问题修复总结

## 重要变更

**交易对变更**: OKX **没有 DOGS 永续合约**，只能使用 **DOGS/USDT 现货交易**（仅做多）。

---

## 已修复的问题

### 1. 历史K线数据加载为 0

**问题**:
```
历史数据加载完成，K线数量: 0
[ERROR] 数据不足！当前只有 0 根K线，至少需要 61 根
```

**原因**:
1. `hist_start_date` 参数未被 CCXTFeed 识别
2. `backfill_start` 默认为 False，导致历史数据未加载
3. 使用了不存在的交易对 `DOGS/USD:USDT`（永续合约不存在）

**修复**:

**CCXTFeed 修复** (`backtrader/feeds/ccxtfeed.py`):
```python
# 添加 hist_start_date 参数支持
params = (
    ("backfill_start", True),  # 改为默认启用
    ("hist_start_date", None),  # 新增参数
)

# 更新 start() 方法支持 hist_start_date
def start(self):
    start_date = self.p.fromdate or self.p.hist_start_date
    if self.p.backfill_start and start_date:
        self._state = self._ST_HISTORBACK
        self._update_bar(start_date)
```

**策略修复** (`examples/backtrader_ccxt_okx_dogs_bollinger.py`):
```python
# 使用正确的参数和数据源
data = store.getdata(
    dataname='DOGS/USDT',           # 现货交易对
    fromdate=datetime.utcnow() - timedelta(minutes=200),
    todate=datetime.utcnow(),
    backfill_start=True,            # 启用历史数据回填
    historical=False,               # 加载历史后继续实时
    ohlcv_limit=100,
)
```

### 2. 交易对错误

**原问题**: 尝试使用 `DOGS/USD:USDT` 永续合约（不存在）

**解决方案**: 改用 `DOGS/USDT` 现货交易

**验证**:
```bash
python -c "import ccxt; ex=ccxt.okx(); ex.load_markets(); print([s for s in ex.markets if 'DOGS' in s.upper()])"
# 输出: ['DOGS/USD', 'DOGS/USDT'] - 都是现货，没有合约
```

### 3. 策略逻辑调整（现货只能做多）

**原策略**: 支持多空双向交易（合约）

**新策略**: 仅支持做多（现货）

**交易逻辑变更**:
```
原逻辑（合约）:
- 价格 > 上轨 → 开多
- 价格 < 下轨 → 开空
- 持多时价格 < 下轨 → 平多
- 持空时价格 > 中轨 → 平空

新逻辑（现货）:
- 价格 > 上轨 → 开多
- 持多时价格 < 下轨 → 平多
- 价格 <= 止损价 → 止损平仓
```

---

## 使用数据加载测试脚本

在运行主策略之前，先运行数据加载测试：

```bash
python test_dogs_data.py
```

**预期输出**:
```
================================================================================
DOGS/USDT 现货数据加载测试
================================================================================
[OK] API配置加载成功

正在加载 DOGS/USDT 现货数据...
开始加载数据...

--- Bar #1 ---
时间: 2026-01-20 12:40:00
开盘: $0.000040
...

已接收 10 根K线
已接收 20 根K线
...

[OK] 数据加载测试完成！
```

---

## 改进点总结

### 已完成

1. ✅ 修改为 DOGS/USDT 现货交易
2. ✅ 修复历史数据加载（backfill_start=True）
3. ✅ 手数自动取整
4. ✅ 详细的 bar 信息输出
5. ✅ 修复分析器 None 值错误
6. ✅ 调整为现货做多策略
7. ✅ 支持数据加载测试

### 新增功能

#### CCXTFeed 改进

- 新增 `hist_start_date` 参数（`fromdate` 的别名）
- `backfill_start` 默认改为 `True`
- 支持现货和合约数据源

#### Bar 信息输出

每根 K 线都会输出：
- 时间
- OHLC 价格
- 成交量
- 布林带指标（上轨、中轨、下轨、带宽、位置）
- ATR 指标
- 持仓信息
- 浮动盈亏
- 止损距离
- 交易信号提示

#### 现货做多逻辑

**开仓**:
- 突破上轨 → 开多仓

**平仓**:
- 持多时跌破下轨 → 平多
- 触及止损 → 强制平仓

**止损**:
- 多仓止损 = 入场价 - 2×ATR

---

## 运行流程

### 第一步：测试数据加载

```bash
python test_dogs_data.py
```

如果成功，继续运行主策略。

### 第二步：运行主策略

```bash
python examples/backtrader_ccxt_okx_dogs_bollinger.py
```

### 预期输出

**数据加载**:
```
正在加载数据...
数据进度: 已接收 10 根K线
数据进度: 已接收 20 根K线
...
数据收集完成，共 200 根K线
```

**策略运行**:
```
====================================================================================================
Bar #200 | Time: 2026-01-20 15:40:00
====================================================================================================
Price Information:
  Close:  $0.000040
...
====================================================================================================
```

如果出现 BUY 或 CLOSE 信号，则策略正常工作！

---

## 参数调整建议

### 如果策略不交易

**增加交易频率**:
```python
cerebro.addstrategy(
    BollingerBandsStrategy,
    period=40,              # 缩短周期（从60改为40）
    devfactor=1.5,          # 缩窄带宽（从2.0改为1.5）
    atr_mult=1.5,           # 缩紧止损（从2.0改为1.5）
)
```

**减少交易频率**:
```python
cerebro.addstrategy(
    BollingerBandsStrategy,
    period=80,              # 延长周期（从60改为80）
    devfactor=2.5,          # 扩大带宽（从2.0改为2.5）
    atr_mult=2.5,           # 放宽止损（从2.0改为2.5）
)
```

---

## 重要提示

### 现货 vs 合约对比

| 特性 | 现货 (DOGS/USDT) | 合约 (不存在) |
|------|-----------------|--------------|
| 双向交易 | ❌ 只能做多 | ❌ 不可用 |
| 杠杆 | ❌ 无 | ❌ 不可用 |
| 风险 | ⚠️ 中等 | - |

### 手续费

- **Maker Fee**: 0.08% (挂单)
- **Taker Fee**: 0.10% (吃单)

### 风险提示

1. 现货只能做多，下跌趋势中无法获利
2. 建议使用小额资金测试
3. 设置合理的止损
4. 不要过度交易

---

## 获取帮助

### 如果还有问题

请提供以下信息：

1. **运行哪个命令**:
   - `test_dogs_data.py` 的输出
   - 或 `backtrader_ccxt_okx_dogs_bollinger.py` 的输出

2. **错误信息**:
   - 完整的错误堆栈
   - 特别是 "Traceback" 部分

3. **环境信息**:
   - Python 版本: `python --version`
   - Backtrader 版本: `pip show backtrader`
   - CCXT 版本: `pip show ccxt`

---

## 相关文档

- `test_dogs_data.py` - 数据加载测试
- `DOGS_STRATEGY_UPDATE.md` - 更新说明
- `DOGS_STRATEGY_QUICK_REF.md` - 快速参考

---

## 最终检查清单

在运行策略前，确认：

- [ ] 已配置 .env 文件（OKX API 密钥）
- [ ] 运行 `test_dogs_data.py` 测试数据加载
- [ ] 数据加载成功（至少61根K线）
- [ ] 网络连接正常
- [ ] 账户有足够资金（0.4 USDT + 手续费）

全部通过后，运行主策略：
```bash
python examples/backtrader_ccxt_okx_dogs_bollinger.py
```

---

**更新时间**: 2026-01-20
**版本**: v3.0 - 现货做多版本
**主要变更**: 从合约改为现货交易（OKX无DOGS永续合约）
