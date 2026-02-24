# CCXT 环境变量配置指南

## 概述

Backtrader CCXT 模块现在支持从 `.env` 文件中自动加载 API 密钥和配置，使配置更加安全和便捷。

## 快速开始

### 1. 创建配置文件

复制示例配置文件：

```bash
cp .env.example .env
```

### 2. 编辑 .env 文件

在 `.env` 文件中填入你的 API 凭证：

```bash
# OKX 交易所
OKX_API_KEY=your_api_key_here
OKX_SECRET=your_secret_here
OKX_PASSWORD=your_password_here

# Binance 交易所
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_SECRET=your_binance_secret_here
```

### 3. 在代码中使用

#### 方法 1: 使用配置辅助函数（推荐）

```python
from backtrader.ccxt import load_ccxt_config_from_env
import backtrader as bt

# 自动从 .env 加载配置
config = load_ccxt_config_from_env('okx')

# 创建 store
store = bt.stores.CCXTStore(
    exchange='okx',
    currency='USDT',
    config=config,
    retries=5
)

# 获取 broker 和 data
cerebro = bt.Cerebro()
cerebro.setbroker(store.getbroker())
cerebro.adddata(store.getdata(dataname='BTC/USDT'))
cerebro.run()
```

#### 方法 2: 手动加载（传统方式）

```python
from dotenv import load_dotenv
import os
import backtrader as bt

# 加载 .env 文件
load_dotenv()

# 手动读取环境变量
config = {
    'apiKey': os.getenv('OKX_API_KEY'),
    'secret': os.getenv('OKX_SECRET'),
    'password': os.getenv('OKX_PASSWORD'),
    'enableRateLimit': True,
}

store = bt.stores.CCXTStore(
    exchange='okx',
    currency='USDT',
    config=config,
    retries=5
)
```

## 支持的交易所

以下交易所已预配置环境变量映射：

| 交易所 | 环境变量 |
|--------|---------|
| OKX | `OKX_API_KEY`, `OKX_SECRET`, `OKX_PASSWORD` |
| Binance | `BINANCE_API_KEY`, `BINANCE_SECRET` |
| Bybit | `BYBIT_API_KEY`, `BYBIT_SECRET` |
| Kraken | `KRAKEN_API_KEY`, `KRAKEN_SECRET` |
| KuCoin | `KUCOIN_API_KEY`, `KUCOIN_SECRET`, `KUCOIN_PASSWORD` |
| Coinbase | `COINBASE_API_KEY`, `COINBASE_SECRET` |
| Gate.io | `GATE_API_KEY`, `GATE_SECRET` |
| Huobi | `HUOBI_API_KEY`, `HUOBI_SECRET` |
| Bitget | `BITGET_API_KEY`, `BITGET_SECRET`, `BITGET_PASSWORD` |

## API 函数

### `load_ccxt_config_from_env(exchange, ...)`

从环境变量加载交易所配置。

**参数:**
- `exchange` (str): 交易所 ID（如 'binance', 'okx'）
- `env_path` (str, optional): 自定义 .env 文件路径
- `enable_rate_limit` (bool, default=True): 启用速率限制
- `sandbox` (bool, default=False): 使用沙盒/测试网模式

**返回:**
- `dict`: CCXT 配置字典

**示例:**
```python
config = load_ccxt_config_from_env('binance', enable_rate_limit=True, sandbox=True)
```

### `get_exchange_credentials(exchange)`

仅获取凭证字段（apiKey, secret, password），不包含其他设置。

**参数:**
- `exchange` (str): 交易所 ID

**返回:**
- `dict`: 包含凭证的字典

**示例:**
```python
creds = get_exchange_credentials('okx')
print(creds['apiKey'])
```

### `list_supported_exchanges()`

返回支持环境变量加载的交易所列表。

**返回:**
- `list`: 交易所 ID 列表

**示例:**
```python
exchanges = list_supported_exchanges()
print(exchanges)  # ['okx', 'binance', 'bybit', ...]
```

### `load_dotenv_file(env_path=None)`

手动加载 .env 文件。

**参数:**
- `env_path` (str, optional): .env 文件路径。如果为 None，搜索默认位置

**返回:**
- `bool`: 成功返回 True，失败返回 False

## 安全建议

1. **永远不要提交 .env 文件到版本控制系统**
   - `.env` 已添加到 `.gitignore`
   - 只提交 `.env.example` 作为模板

2. **使用只读 API 密钥**
   - 对于回测和数据获取，使用只读权限的 API 密钥
   - 限制 IP 白名单
   - 禁用提现权限

3. **沙盒测试**
   - 先在交易所的测试网/沙盒环境中测试
   ```python
   config = load_ccxt_config_from_env('okx', sandbox=True)
   ```

4. **密钥轮换**
   - 定期更换 API 密钥
   - 为不同的应用使用不同的密钥

## 故障排查

### 问题: `Missing required credential`

**原因:** .env 文件中缺少必需的凭证

**解决:**
1. 检查 .env 文件是否存在
2. 确认环境变量名称正确（使用大写和下划线）
3. 确保没有额外的空格或引号

### 问题: `python-dotenv not installed`

**解决:**
```bash
pip install python-dotenv
```

### 问题: 凭证加载不正确

**调试:**
```python
from backtrader.ccxt import load_dotenv_file
import os

# 手动加载
load_dotenv_file('.env')

# 检查环境变量
print(os.getenv('OKX_API_KEY'))
print(os.getenv('OKX_SECRET'))
```

## 完整示例

查看示例脚本：
- `examples/backtrader_ccxt_okex_sma.py` - OKX 实盘交易示例

运行测试：
```bash
python test_ccxt_config_helper.py
```

## 迭代94相关

这些改进是迭代94（CCXT实盘交易优化）的一部分，旨在：
- 简化配置管理
- 提高安全性（避免硬编码密钥）
- 改善用户体验（一键配置）
- 支持多交易所快速切换
