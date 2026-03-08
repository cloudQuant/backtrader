# 资金费率策略使用指南

本文档说明如何在 Backtrader 中使用 **WebSocket 实时** 资金费率数据进行永续合约交易策略开发。

---
## 目录

1. [什么是资金费率](#什么是资金费率)
2. [快速开始](#快速开始)
3. [WebSocket 实时数据](#websocket-实时数据)
4. [API 参考](#api-参考)
5. [策略示例](#策略示例)
6. [交易所支持](#交易所支持)

---
## 什么是资金费率

### 资金费率简介

永续合约没有交割日期，为了使合约价格锚定现货价格，交易所引入了**资金费率**机制：

- **正费率**：合约价格 > 现货价格 → 多头支付给空头
- **负费率**：合约价格 < 现货价格 → 空头支付给多头
- **收取频率**：通常每 8 小时收取一次（00:00, 08:00, 16:00 UTC）

### 费率计算

```bash
资金费 = 持仓价值 × 资金费率

```
例如：

- 持有 100 USDT 的多仓
- 资金费率为 +0.01% (0.0001)
- 需要支付：100 × 0.0001 = 0.01 USDT

### 典型费率范围

| 费率范围 | 含义 | 策略建议 |

|---------|------|---------|

| > 0.05% | 极度贪婪，多头过度拥挤 | 考虑做空套利 |

| 0.01% ~ 0.05% | 多头偏多 | 观望 |

| -0.01% ~ 0.01% | 平衡区域 | 无明显偏向 |

| -0.05% ~ -0.01% | 空头偏多 | 观望 |

| < -0.05% | 极度恐惧，空头过度拥挤 | 考虑做多套利 |

---
## 快速开始

### 安装依赖

```bash

# 安装 ccxt.pro（WebSocket 支持）

pip install ccxtpro

# 或安装完整 ccxt

pip install ccxt[pro]

```

### 使用带资金费率的数据源

```python
import backtrader as bt
from backtrader.feeds import CCXTFeedWithFunding
from backtrader.stores import CCXTStore
from datetime import datetime, timedelta

# 创建 Store

store = CCXTStore(
    exchange='binance',
    config={'apiKey': 'xxx', 'secret': 'xxx'},
    currency='USDT'
)

# 创建带资金费率的数据源（默认启用 WebSocket）

data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT:USDT',  # 永续合约
    name='BTC/USDT:USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime.utcnow() - timedelta(hours=24),
    backfill_start=True,
    historical=False,
    use_websocket=True,              # 使用 WebSocket（默认 True）
    include_funding=True,              # 启用资金费率
    funding_history_days=3,            # 获取 3 天历史
    debug=False
)

cerebro = bt.Cerebro()
cerebro.adddata(data)

```

### 在策略中访问资金费率

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# 检查数据源是否支持资金费率
        if hasattr(self.data, 'funding_rate'):
            print("数据源支持资金费率")
        else:
            raise ValueError("请使用 CCXTFeedWithFunding 数据源")

    def next(self):

# 获取当前资金费率（实时 WebSocket 更新）
        current_funding = self.data.funding_rate[0]

# 获取标记价格
        if hasattr(self.data, 'mark_price'):
            mark_price = self.data.mark_price[0]

# 获取预测费率
        if hasattr(self.data, 'predicted_funding_rate'):
            predicted = self.data.predicted_funding_rate[0]

# 获取下次收费时间
        if hasattr(self.data, 'next_funding_time'):
            next_funding_time = self.data.next_funding_time[0]

# 获取当前价格
        price = self.data.close[0]

# 根据资金费率进行交易
        if current_funding > 0.0005:  # 0.05% 以上
            self.sell()  # 做空套利
        elif current_funding < -0.0005:  # -0.05% 以下
            self.buy()   # 做多套利

```

---
## WebSocket 实时数据

### WebSocket 连接说明

CCXTFeedWithFunding **要求** WebSocket 连接才能工作。当 WebSocket 不可用时，系统会**直接报错**，不会降级到 HTTP 轮询。

### 安装依赖

```bash

# 必须安装 ccxt.pro

pip install ccxtpro

```

### WebSocket 订阅的数据流

| 数据流 | 说明 | 更新频率 |

|--------|------|---------|

| `watch_ohlcv` | K 线数据 | 每根 K 线闭合时 |

| `watch_funding_rate` | 资金费率 | 实时推送（通常每秒） |

| `watch_mark_price` | 标记价格 | 实时推送 |

### 数据整合流程

```bash
WebSocket OHLCV 推送          WebSocket Funding 推送
        |                              |

        v                              v
   [timestamp, O, H, L, C, V]    {fundingRate, markPrice, ...}
        |                              |

        - -----------> 合并 <------------+

                     |

                     v
   [timestamp, O, H, L, C, V, funding_rate, mark_price, ...]
                     |

                     v
               self.lines.close[0]
               self.lines.funding_rate[0]
               self.lines.mark_price[0]

```

### 错误处理

当 WebSocket 不可用时，会抛出 `WebSocketRequiredError`：

```python

# 安装 ccxt.pro 时会自动检查

from backtrader.feeds import CCXTFeedWithFunding

try:
    data = CCXTFeedWithFunding(
        store=store,
        dataname='BTC/USDT:USDT',
        use_websocket=True  # 必须为 True
    )
except WebSocketRequiredError as e:
    print(f"错误: {e}")

# 请确保安装了 ccxt.pro: pip install ccxtpro

```

---
## API 参考

### CCXTFeedWithFunding

#### Lines

| Line | 类型 | 说明 |

|------|------|------|

| `funding_rate` | float | 当前资金费率（8 小时费率，如 0.0001 = 0.01%） |

| `mark_price` | float | 当前标记价格（用于资金费计算） |

| `next_funding_time` | float | 下次收取资金费的时间 |

| `predicted_funding_rate` | float | 预测的下一期资金费率 |

#### Params

| 参数 | 默认值 | 说明 |

|------|--------|------|

| `use_websocket` | True | 使用 WebSocket 实时数据（必须为 True） |

| `include_funding` | True | 是否获取资金费率数据 |

| `funding_history_days` | 3 | 启动时获取的历史天数 |

| `ws_startup_timeout` | 10 | WebSocket 启动超时时间（秒） |

| `debug` | False | 调试输出 |

### CCXTWebSocketManager

#### 新增方法

```python

# 订阅资金费率

manager.subscribe_funding_rate(symbol, callback)

# 订阅标记价格

manager.subscribe_mark_price(symbol, callback)

```

---
## 策略示例

### 示例 1: 实时资金费率监控

```python
class FundingMonitor(bt.Strategy):
    """监控并打印实时资金费率"""

    def __init__(self):
        if not hasattr(self.data, 'funding_rate'):
            raise ValueError("请使用 CCXTFeedWithFunding")

        self.bar_count = 0
        self.is_live = False

    def notify_data(self, data, status):
        if status == data.LIVE and not self.is_live:
            self.is_live = True
            print("[LIVE] 进入实时模式！")

    def next(self):
        if not self.is_live:
            return

        self.bar_count += 1
        if self.bar_count % 10 != 0:  # 每 10 根 K 线输出一次
            return

        funding = self.data.funding_rate[0]
        mark_price = self.data.mark_price[0] if hasattr(self.data, 'mark_price') else 0
        price = self.data.close[0]

# 计算溢价
        premium = (mark_price - price) / price * 100 if price > 0 else 0

        print(f"\n{'='*60}")
        print(f"[FUNDING] {self.data.datetime.datetime(0)}")
        print(f"  价格:      ${price:.6f}")
        print(f"  标记价格:  ${mark_price:.6f} (溢价: {premium:+.4f}%)")
        print(f"  资金费率:  {funding:.6f} ({funding*100:.4f}%)")
        print(f"  年化费率:  {funding*3*365*100:.2f}%")
        print(f"{'='*60}\n")

```

### 示例 2: 资金费率套利策略

```python
class FundingArbitrage(bt.Strategy):
    """资金费率套利策略（WebSocket 实时版）"""

    params = (
        ('funding_high', 0.0005),   # 0.05% 以上做空
        ('funding_low', -0.0005),   # -0.05% 以下做多
        ('position_size', 10),
    )

    def __init__(self):
        if not hasattr(self.data, 'funding_rate'):
            raise ValueError("请使用 CCXTFeedWithFunding")

    def next(self):
        funding = self.data.funding_rate[0]
        position = self.getposition()

# 高费率 = 多头过度拥挤 = 做空套利
        if funding > self.p.funding_high and position.size == 0:
            print(f"[SIGNAL] 费率 {funding:.6f} > {self.p.funding_high}，做空套利")
            self.sell(size=self.p.position_size)

# 低费率 = 空头过度拥挤 = 做多套利
        elif funding < self.p.funding_low and position.size == 0:
            print(f"[SIGNAL] 费率 {funding:.6f} < {self.p.funding_low}，做多套利")
            self.buy(size=self.p.position_size)

# 费率回归时平仓
        elif abs(funding) < abs(self.p.funding_high) / 2 and position.size != 0:
            print(f"[EXIT] 费率回归到 {funding:.6f}，平仓")
            if position.size > 0:
                self.sell(size=position.size)
            else:
                self.buy(size=abs(position.size))

```

### 示例 3: 基于标记价格的价差交易

```python
class MarkPriceArbitrage(bt.Strategy):
    """基于标记价与最新价差价的交易"""

    params = (
        ('premium_threshold', 0.001),  # 0.1% 溢价阈值
    )

    def __init__(self):
        if not hasattr(self.data, 'mark_price'):
            raise ValueError("数据源需要 mark_price")

    def next(self):
        price = self.data.close[0]
        mark_price = self.data.mark_price[0]

# 计算溢价
        premium = (mark_price - price) / price if price > 0 else 0

# 标记价 > 最新价 = 溢价 = 做多（预期回归）

# 标记价 < 最新价 = 折价 = 做空（预期回归）
        if premium > self.p.premium_threshold:
            self.buy()  # 溢价时做多
        elif premium < -self.p.premium_threshold:
            self.sell()  # 折价时做空

```

---
## 交易所支持

### WebSocket 资金费率支持

| 交易所 | watch_funding_rate | watch_mark_price | 说明 |

|--------|-------------------|------------------|------|

| **Binance**| ✅ (via markPrice) | ✅ | 通过标记价格流获取 |

|**OKX**| ✅ | ✅ | 原生支持 |

|**Bybit**| ✅ | ✅ | 支持 |

|**Bitget**| ⚠️ | ✅ | 部分支持 |

|**KuCoin**| ⚠️ | ✅ | 需测试 |

### 交易所特定配置

#### Binance

```python
store = CCXTStore(
    exchange='binance',
    config={
        'apiKey': 'xxx',
        'secret': 'xxx',
        'options': {
            'defaultType': 'future'  # 使用合约 API
        }
    }
)

# Binance 通过 markPrice stream 获取资金费率

data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT:USDT',  # 永续合约
    use_websocket=True
)

```

#### OKX

```python
store = CCXTStore(
    exchange='okx',
    config={
        'apiKey': 'xxx',
        'secret': 'xxx',
        'password': 'xxx',
        'options': {
            'defaultType': 'swap'
        }
    }
)

data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT:USDT',
    use_websocket=True
)

```

---
## 调试和监控

### 启用调试输出

```python
data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT:USDT',
    debug=True  # 启用调试输出

)

```

### 调试输出示例

```bash
[WS] WebSocket connected to binance
[WS] WebSocket started for BTC/USDT:USDT with funding rate
[FUNDING] Fetching historical funding rates for BTC/USDT:USDT...
[FUNDING] Loaded 72 historical rates
[FUNDING WS] Rate: 0.00010000, Mark: 43250.50000000
[FUNDING WS] Rate: 0.00010500, Mark: 43252.30000000

```

---
## 注意事项

1.**ccxt.pro 许可证**: ccxt.pro 需要商业许可证用于生产环境

1. **WebSocket 必需**: 此数据源强制要求 WebSocket，不会降级到 HTTP
2. **WebSocket 稳定性**: WebSocket 可能断开，内置自动重连机制
3. **数据同步**: 资金费率更新频率低于价格，属于正常现象
4. **启动检查**: 如果 WebSocket 连接超时，会抛出 `WebSocketRequiredError`

## 网络故障排查

### WebSocket 连接失败

如果遇到 WebSocket 连接问题，请检查以下几点:

1. **DNS 解析**

   ```bash

# 测试 DNS 解析
   ping ws.okx.com      # OKX
   ping stream.binance.com  # Binance
   ```

1. **防火墙设置**
   - 确保允许 WebSocket 连接 (通常端口 443)
   - 某些公司网络可能阻止 WebSocket 连接

1. **代理配置**

   ```python

# 如果需要代理，在 config 中设置
   config = {
       'proxies': {
           'https': '<http://your-proxy:port',>
           'ws': 'ws://your-proxy:port',  # WebSocket 代理
       }
   }
   ```

1. **测试脚本**

   运行简单的 WebSocket 测试以验证连接:
   ```bash
   python examples/test_websocket_simple.py
   ```

### 常见错误

| 错误信息 | 原因 | 解决方案 |

|---------|------|---------|

| `Could not contact DNS servers` | DNS 解析失败 | 检查网络连接，尝试使用 VPN |

| `Connection refused` | 防火墙阻止 | 开放 WebSocket 端口 |

| `Timeout` | 网络延迟过高 | 检查网络质量，增加超时时间 |

| `Authentication failed` | API 密钥错误 | 验证 API 密钥配置 |

---
## 相关文档

- [WebSocket 指南](./WEBSOCKET_GUIDE.md)
- [CCXT 官方文档](<https://docs.ccxt.com/)>
