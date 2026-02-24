# DOGS/USDT 现货布林带策略 - 更新说明

## 重要变更

**交易对**: DOGS/USD 永续合约 → **DOGS/USDT 现货**

**原因**: OKX 不提供 DOGS 永续合约，只有现货交易。

---

## 最新改进

### 1. 历史数据加载修复

**问题**: 策略加载 0 根K线

**修复内容**:
1. CCXTFeed 新增 `hist_start_date` 参数支持
2. `backfill_start` 默认改为 `True`
3. 数据源从不存在的 `DOGS/USD:USDT` 改为 `DOGS/USDT`

### 2. 交易逻辑调整

**原设计**: 合约双向交易（多空）

**新实现**: 现货做多（仅买入）

**变更对比**:

```
原逻辑（合约）:
- 突破上轨 → 开多
- 跌破下轨 → 开空
- 持多时跌破下轨 → 平多
- 持空时升破中轨 → 平空

新逻辑（现货）:
- 突破上轨 → 开多
- 持多时跌破下轨 → 平多
- 触及止损 → 强制平仓
```

### 3. 详细的Bar信息输出（保留）

每个bar都会输出以下信息：

```
====================================================================================================
Bar #200 | Time: 2026-01-20 15:40:00
====================================================================================================
Price Information:
  Open:   $0.000040
  High:   $0.000041
  Low:    $0.000039
  Close:  $0.000040
  Volume: 15000000

Bollinger Bands (Period=60, Std=2.0):
  Upper Band: $0.000041
  Middle Band: $0.000040
  Lower Band: $0.000039
  Bandwidth: 5.0%
  BB Position: 50.0% (Neutral)

ATR (Period=14):
  ATR Value: 0.000001
  ATR % of Price: 2.5%

Position Information:
  Position Size: 10000
  Entry Price: $0.000040
  Unrealized P&L: $0.0000 USDT
  Stop Loss: $0.000038 (Distance: 5.0%)

Trading Signals:
  >>> HOLD LONG (In position)
====================================================================================================
```

### 4. 手数取整（保留）

```python
def calculate_order_size(self, price):
    # 计算理论数量
    theoretical_size = 0.4 / price  # 例如: 0.4 / 0.00004 = 10000

    # 向上取整
    size = int(theoretical_size)  # 例如: 10000

    # 确保至少为1
    if size < 1:
        size = 1

    return size
```

---

## CCXTFeed 改进

### 新增参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `hist_start_date` | None | 历史数据开始日期（fromdate的别名） |
| `backfill_start` | True | 是否启用历史数据回填 |

### 代码变更

`backtrader/feeds/ccxtfeed.py`:

```python
# 添加新参数
params = (
    ("backfill_start", True),  # 改为默认启用
    ("hist_start_date", None),  # 新增参数
)

# 更新 start() 方法
def start(self):
    """Start the CCXT data feed."""
    DataBase.start(self)

    # Use hist_start_date if fromdate is not set
    start_date = self.p.fromdate or self.p.hist_start_date

    if self.p.backfill_start and start_date:
        self._state = self._ST_HISTORBACK
        self.put_notification(self.DELAYED)
        self._update_bar(start_date)
    elif self.p.historical:
        # Historical only mode
        self._state = self._ST_HISTORBACK
        self.put_notification(self.DELAYED)
        if start_date:
            self._update_bar(start_date)
    else:
        self._state = self._ST_LIVE
        self.put_notification(self.LIVE)
```

---

## 策略文件变更

### 文件: `examples/backtrader_ccxt_okx_dogs_bollinger.py`

**数据源配置**:

```python
# 旧配置（错误）
data = store.getdata(
    dataname='DOGS/USD:USDT',      # 不存在
    hist_start_date=datetime.utcnow() - timedelta(minutes=200),
    # ...
)

# 新配置（正确）
data = store.getdata(
    dataname='DOGS/USDT',           # 现货交易对
    fromdate=datetime.utcnow() - timedelta(minutes=200),
    todate=datetime.utcnow(),
    backfill_start=True,            # 启用历史数据回填
    historical=False,               # 加载历史后继续实时
    ohlcv_limit=100,
)
```

**策略类调整**:

```python
# 旧：双向交易
self.long_stop_price = None  # 多仓止损价
self.short_stop_price = None  # 空仓止损价

# 新：仅做多
self.stop_price = None  # 止损价
```

**交易逻辑简化**:

```python
# 旧：双向交易逻辑
# 1. 检查多仓止损
# 2. 检查空仓止损
# 3. 突破上轨 → 开多
# 4. 跌破下轨 → 开空
# 5. 持多时跌破下轨 → 平多
# 6. 持空时升破中轨 → 平空

# 新：仅做多逻辑
# 1. 检查止损
# 2. 突破上轨 → 开多
# 3. 持多时跌破下轨 → 平多
```

---

## 完整交易逻辑（现货）

### 多头策略

```
1. 突破上轨
   ├─ 检查当前无仓位
   ├─ 计算下单数量（取整）
   └─ 开多仓
   └─ 设置止损 = 入场价 - 2×ATR

2. 持有中
   ├─ 每分钟检查是否触及止损
   ├─ 价格回到下轨以下 → 平仓
   └─ 每30分钟输出持仓状态

3. 平仓
   ├─ 跌破下轨 → 主动平仓
   ├─ 触及止损 → 强制平仓
   └─ 记录交易盈亏
```

---

## 测试脚本

### 文件: `test_dogs_data.py`

更新为使用 DOGS/USDT 现货:

```python
data = store.getdata(
    dataname='DOGS/USDT',
    name='DOGS/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime.utcnow() - timedelta(minutes=200),
    todate=datetime.utcnow(),
    backfill_start=True,
    historical=False,
    ohlcv_limit=100,
)
```

---

## 运行方法

### 步骤1: 测试数据加载

```bash
python test_dogs_data.py
```

**预期输出**:
```
DOGS/USDT 现货数据加载测试
================================================================================
[OK] API配置加载成功
正在加载 DOGS/USDT 现货数据...
数据收集完成，共 200 根K线
[OK] 数据加载测试完成！
```

### 步骤2: 运行策略

```bash
python examples/backtrader_ccxt_okx_dogs_bollinger.py
```

---

## 策略参数说明

### 布林带参数

| 参数 | 默认值 | 建议范围 | 说明 |
|------|--------|----------|------|
| period | 60 | 20-120 | 周期越长，信号越少但越可靠 |
| devfactor | 2.0 | 1.5-3.0 | 标准差越大，带宽越宽 |

### ATR参数

| 参数 | 默认值 | 建议范围 | 说明 |
|------|--------|----------|------|
| atr_period | 14 | 7-21 | ATR周期 |
| atr_mult | 2.0 | 1.5-3.0 | 止损距离倍数 |

### 资金管理

| 参数 | 默认值 | 建议范围 | 说明 |
|------|--------|----------|------|
| order_size | 0.4 | 0.4-10.0 | 每次下单金额（USDT） |

---

## 重要提示

### 1. 合约vs现货

| 特性 | 现货 | 合约 |
|------|------|------|
| 双向交易 | ❌ 只能做多 | ✓ 支持多空 |
| 杠杆 | ❌ 无 | ✓ 有杠杆 |
| 资金效率 | ❌ 低 | ✓ 高 |
| 风险 | ⚠️ 中等 | ⚠️⚠️⚠️ 高 |
| DOGS | ✓ 可用 | ❌ 不可用 |

### 2. 手续费

- **Maker Fee**: 0.08% (挂单)
- **Taker Fee**: 0.10% (吃单)

### 3. 风险提示

现货交易风险提示：
- ⚠️ 只能做多，下跌趋势中无法获利
- ⚠️ 无杠杆放大收益
- ⚠️ 需要持有实际资产

**建议**:
- 使用小额资金测试
- 设置合理的止损
- 不要过度交易

---

## 文件更新总结

**主文件**: `examples/backtrader_ccxt_okx_dogs_bollinger.py`

**更新内容**:
- ✓ 改为 DOGS/USDT 现货交易
- ✓ 增加上做多交易逻辑（移除做空）
- ✓ 新增手数取整方法
- ✓ 增加详细的bar信息输出
- ✓ 优化日志格式
- ✓ 增加交易信号提示

**CCXTFeed**: `backtrader/feeds/ccxtfeed.py`

**更新内容**:
- ✓ 新增 `hist_start_date` 参数
- ✓ `backfill_start` 默认改为 `True`
- ✓ 优化 `start()` 方法逻辑

**测试文件**: `test_dogs_data.py`

**更新内容**:
- ✓ 改用 DOGS/USDT 现货数据源
- ✓ 更新参数配置

---

## 总结

所有改进已完成：
1. ✅ 修复历史数据加载问题
2. ✅ 改用 DOGS/USDT 现货交易
3. ✅ 实现现货做多策略（移除做空逻辑）
4. ✅ 增加详细的bar信息输出
5. ✅ 实现手数自动取整
6. ✅ 完整的交易日志
7. ✅ ATR动态止损

**现在可以运行策略了！** 🚀

---

**更新时间**: 2026-01-20
**版本**: v3.0 - 现货做多版本
