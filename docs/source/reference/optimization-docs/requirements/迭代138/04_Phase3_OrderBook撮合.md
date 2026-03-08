# Phase 3: OrderBook 深度撮合

> 周期: 2 周 | 优先级: 🟡 中 | 风险: 中

---
## 1. 目标

实现基于 OrderBook 深度的精确撮合逻辑，提升大单撮合的真实性。

### 1.1 核心目标

- ✅ OrderBook 深度撮合算法
- ✅ 部分成交逻辑
- ✅ 市场冲击模型（可选）
- ✅ 滑点估算优化

---
## 2. 实施内容

### 2.1 OrderBook 深度撮合（5 天）

- *文件**: `backtrader/brokers/obbroker.py`

```python
class OrderBookBroker(TickBroker):
    """基于 OrderBook 深度的撮合 Broker"""

    params = (
        ('use_orderbook', True),
        ('max_depth_levels', 10),
        ('market_impact', False),
        ('impact_factor', 0.0001),
    )

    def __init__(self):
        super().__init__()
        self._ob_channels = {}

    def register_orderbook_channel(self, symbol, channel):
        """注册 OrderBook 通道"""
        self._ob_channels[symbol] = channel

    def match_with_orderbook(self, order, orderbook):
        """使用 OrderBook 撮合订单"""
        if order.isbuy():
            return self._match_buy_order(order, orderbook)
        else:
            return self._match_sell_order(order, orderbook)

    def _match_buy_order(self, order, ob):
        """买单撮合 - 穿透 asks"""
        remaining = order.executed.remsize
        total_cost = 0.0
        fills = []

        for price, qty in ob.asks[:self.p.max_depth_levels]:
            if remaining <= 0:
                break

# 检查价格条件
            if order.exectype == Order.Limit and price > order.price:
                break

# 计算成交量
            fill_qty = min(remaining, qty)
            fill_price = price

# 应用滑点
            if self.p.market_impact:
                fill_price = self._apply_market_impact(
                    price, fill_qty, qty, 'buy'
                )

            fills.append((fill_price, fill_qty))
            total_cost += fill_price *fill_qty
            remaining -= fill_qty

# 执行成交
        if fills:
            avg_price = total_cost / (order.executed.remsize - remaining)
            filled_size = order.executed.remsize - remaining
            self._execute_order(order, avg_price, filled_size, ob.timestamp)
            return True

        return False

    def _apply_market_impact(self, price, fill_qty, level_qty, side):
        """应用市场冲击"""
        impact_ratio = fill_qty / level_qty
        impact = price*self.p.impact_factor*impact_ratio

        if side == 'buy':
            return price + impact
        else:
            return price - impact

```

- *测试**: `tests/phase3/test_orderbook_matching.py`

---
### 2.2 市场冲击模型（3 天）

- *文件**: `backtrader/brokers/impact_models.py`

```python
class MarketImpactModel:
    """市场冲击模型基类"""

    def calculate_impact(self, order_size, level_size, price):
        raise NotImplementedError

class LinearImpactModel(MarketImpactModel):
    """线性冲击模型"""

    def __init__(self, factor=0.0001):
        self.factor = factor

    def calculate_impact(self, order_size, level_size, price):
        ratio = order_size / level_size
        return price *self.factor*ratio

class SquareRootImpactModel(MarketImpactModel):
    """平方根冲击模型（更真实）"""

    def __init__(self, factor=0.001):
        self.factor = factor

    def calculate_impact(self, order_size, level_size, price):
        ratio = order_size / level_size
        return price*self.factor* (ratio ** 0.5)

```

---
## 3. 交付物

- [ ] `backtrader/brokers/obbroker.py`
- [ ] `backtrader/brokers/impact_models.py`
- [ ] `tests/phase3/` - 完整测试套件
- [ ] Phase 3 完成报告

---
## 4. 验收标准

- [ ] OrderBook 深度撮合准确
- [ ] 大单滑点合理
- [ ] 与真实交易所对比验证
- [ ] 回归测试 100%通过

---
## 5. 时间表

| 任务 | 工作量 |

|------|--------|

| OrderBook 深度撮合 | 5 天 |

| 市场冲击模型 | 3 天 |

| 测试与验证 | 4 天 |

| 文档 | 2 天 |

- *总计**: 14 天（2 周）
