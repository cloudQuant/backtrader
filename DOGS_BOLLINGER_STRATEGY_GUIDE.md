# DOGS/USDT 布林带突破策略使用指南

## 📋 策略概述

这是一个基于布林带指标的突破交易策略，专门用于 OKX DOGS/USDT 永续合约交易。

### 策略参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 交易对 | DOGS/USDT:USDT | OKX 永续合约 |
| 下单金额 | 0.4 USDT | 每次固定下单金额 |
| K线周期 | 1 分钟 | 实时交易 |
| 布林带周期 | 60 | 计算60根K线 |
| 标准差倍数 | 2.0 | 上下轨距离 |
| ATR止损周期 | 14 | 动态止损计算 |
| ATR止损倍数 | 2.0 | 止损距离 |

### 交易逻辑

```
价格突破上轨 → 开多仓（买入）
    ↓
持有并跟踪止损（入场价 - 2×ATR）
    ↓
触发止损或跌破下轨 → 平多仓

价格跌破下轨 → 开空仓（做空）
    ↓
持有并跟踪止损（入场价 + 2×ATR）
    ↓
触发止损或升破中轨 → 平空仓
```

---

## 🚀 快速开始

### 1. 环境准备

```bash
# 安装依赖
pip install backtrader ccxt python-dotenv

# 或使用项目中的版本
cd D:\source_code\backtrader
pip install -e .
```

### 2. 配置 API 密钥

编辑项目根目录的 `.env` 文件：

```bash
# OKX API 配置
OKX_API_KEY=your_api_key_here
OKX_SECRET=your_secret_here
OKX_PASSWORD=your_password_here
```

⚠️ **重要提示**：
- 请使用 OKX 的**合约交易 API 密钥**
- API 密钥需要开通合约交易权限
- 建议先在**测试网**或**沙盒环境**中测试

### 3. 运行策略

```bash
# 进入项目目录
cd D:\source_code\backtrader

# 运行策略（实时交易）
python examples/backtrader_ccxt_okx_dogs_bollinger.py
```

---

## ⚙️ 策略配置

### 修改参数

编辑 `backtrader_ccxt_okx_dogs_bollinger.py` 中的参数：

```python
cerebro.addstrategy(
    BollingerBandsStrategy,
    period=60,              # 布林带周期（可改为20、120等）
    devfactor=2.0,          # 标准差倍数（可改为1.5、3.0等）
    order_size=0.4,         # 每次下单金额（USDT）
    atr_period=14,          # ATR周期
    atr_mult=2.0,           # ATR止损倍数
)
```

### 常见参数调整

| 场景 | period | devfactor | 说明 |
|------|--------|-----------|------|
| 快速交易 | 20 | 1.5 | 更灵敏，更多交易 |
| 标准设置 | 60 | 2.0 | 默认参数 |
| 稳健交易 | 120 | 2.5 | 更保守，减少假突破 |
| 趋势跟踪 | 60 | 3.0 | 只捕捉大趋势 |

### 资金管理

```python
# 设置初始资金
cerebro.broker.setcash(10.0)  # 10 USDT（测试用）

# 修改下单金额
order_size=0.4  # 每次0.4 USDT
```

⚠️ **风险提示**：
- 下单金额0.4 USDT非常小，手续费占比较高
- 建议测试时使用小额，实盘时适当增加
- 确保账户有足够的保证金

---

## 📊 策略特点

### 优势

1. **趋势跟踪**: 捕捉价格突破后的趋势
2. **动态止损**: 使用ATR自适应止损
3. **双向交易**: 可做多和做空
4. **小资金友好**: 0.4 USDT即可测试
5. **机械化执行**: 消除情绪干扰

### 劣势

1. **震荡市亏损**: 横盘震荡时频繁止损
2. **滞后性**: 布林带是滞后指标
3. **假突破**: 可能遭遇假突破
4. **手续费成本**: 小额交易手续费占比高

### 适用市场

- ✅ **趋势市场**: 强烈上涨或下跌趋势
- ✅ **波动市场**: 波动率较大的市场
- ❌ **震荡市场**: 横盘整理市场
- ❌ **低波动市场**: 价格变化不大的市场

---

## 🛡️ 风险管理

### 内置风险控制

1. **ATR动态止损**
   - 多仓止损价 = 入场价 - 2×ATR
   - 空仓止损价 = 入场价 + 2×ATR

2. **仓位控制**
   - 固定每次下单0.4 USDT
   - 避免重仓交易

3. **止盈机制**
   - 多仓：价格跌破下轨时平仓
   - 空仓：价格升破中轨时平仓

### 建议的风险控制

```python
# 1. 设置最大持仓数
max_positions = 3

# 2. 设置每日最大亏损
daily_loss_limit = 2.0  # 2 USDT

# 3. 设置交易时间窗口
# 避开重大新闻发布时间

# 4. 设置账户止损
# 当总资金亏损达到50%时停止交易
```

---

## 📈 性能优化

### 1. 参数优化

建议使用历史数据回测优化参数：

```python
# 在策略中添加参数优化
cerebro.optstrategy(
    BollingerBandsStrategy,
    period=[20, 40, 60, 120],
    devfactor=[1.5, 2.0, 2.5],
    atr_mult=[1.5, 2.0, 2.5],
)
```

### 2. 过滤条件

添加额外的过滤条件减少假信号：

```python
# 添加成交量过滤
if self.data.volume[0] < self.data.volume[-1]:
    return  # 成交量不足，不交易

# 添加ATR过滤（只在波动率足够时交易）
if self.atr[0] < self.data.close[0] * 0.01:  # ATR小于1%
    return  # 波动率太低，不交易

# 添加时间过滤（避免特定时间段交易）
current_hour = datetime.now().hour
if 0 <= current_hour < 8:  # 凌晨不交易
    return
```

### 3. 仓位管理优化

```python
# 根据ATR调整仓位
if atr_value > self.data.close[0] * 0.02:  # 高波动
    size = self.p.order_size / current_price * 0.5  # 减半仓位
else:  # 正常波动
    size = self.p.order_size / current_price
```

---

## 🔧 故障排查

### 问题1: API 连接失败

**错误**: `AuthenticationError` 或 `NetworkError`

**解决**:
1. 检查 API 密钥是否正确
2. 检查网络连接
3. 确认 API 密钥有合约交易权限

### 问题2: 订单被拒绝

**错误**: `Order Rejected`

**可能原因**:
1. 账户保证金不足
2. 下单金额低于最小限制
3. 交易对暂停交易

**解决**:
```python
# 检查账户余额
balance = store.get_wallet_balance(['USDT'])
print(f"可用保证金: {balance['USDT']['free']}")

# 增加下单金额或检查交易对状态
```

### 问题3: 策略不交易

**检查**:
1. 布林带是否有足够的数据（60根K线）
2. 是否满足交易条件
3. 是否有未完成的订单

**调试**:
```python
def next(self):
    # 添加调试日志
    self.log(f'价格: {self.data.close[0]:.6f}, '
            f'上轨: {self.top[0]:.6f}, '
            f'下轨: {self.bot[0]:.6f}')
```

---

## 📚 相关资源

### 文件说明

- `backtrader_ccxt_okx_dogs_bollinger.py` - 主策略文件
- `analyze_okx_min_trading.py` - 最小交易金额分析
- `OKX_MIN_TRADING_ANALYSIS.md` - DOGS/USDT分析报告

### 参考资料

- [OKX 官方文档](https://www.okx.com/docs/)
- [Backtrader 文档](https://www.backtrader.com/)
- [CCXT 文档](https://docs.ccxt.com/)
- [布林带指标介绍](https://www.investopedia.com/terms/b/bollingerbands.asp)

---

## ⚠️ 免责声明

本策略仅供学习和研究目的使用。加密货币合约交易具有高风险，可能导致全部资金损失。

- 请在充分了解风险的情况下使用
- 建议先在模拟环境测试
- 实盘交易请使用小额资金
- 作者不对任何损失负责

**交易有风险，投资需谨慎！**
