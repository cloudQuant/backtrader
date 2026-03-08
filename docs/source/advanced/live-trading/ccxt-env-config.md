# CCXT Environment Variable Configuration Guide

## Overview

The Backtrader CCXT module supports automatically loading API keys and configuration from `.env` files, making configuration more secure and convenient.

## Quick Start

### 1. Create Configuration File

Copy the example configuration file:

```bash
cp .env.example .env

```

### 2. Edit .env File

Fill in your API credentials in the `.env` file:

```bash

# OKX Exchange

OKX_API_KEY=your_api_key_here
OKX_SECRET=your_secret_here
OKX_PASSWORD=your_password_here

# Binance Exchange

BINANCE_API_KEY=your_binance_api_key_here
BINANCE_SECRET=your_binance_secret_here

```

### 3. Usage in Code

#### Method 1: Using the Config Helper (Recommended)

```python
from backtrader.ccxt import load_ccxt_config_from_env
import backtrader as bt

# Auto-load config from .env

config = load_ccxt_config_from_env('okx')

# Create store

store = bt.stores.CCXTStore(
    exchange='okx',
    currency='USDT',
    config=config,
    retries=5
)

# Get broker and data

cerebro = bt.Cerebro()
cerebro.setbroker(store.getbroker())
cerebro.adddata(store.getdata(dataname='BTC/USDT'))
cerebro.run()

```

#### Method 2: Manual Loading (Traditional)

```python
from dotenv import load_dotenv
import os
import backtrader as bt

# Load .env file

load_dotenv()

# Manually read environment variables

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

## Supported Exchanges

The following exchanges have pre-configured environment variable mappings:

| Exchange | Environment Variables |

|----------|----------------------|

| OKX | `OKX_API_KEY`, `OKX_SECRET`, `OKX_PASSWORD` |

| Binance | `BINANCE_API_KEY`, `BINANCE_SECRET` |

| Bybit | `BYBIT_API_KEY`, `BYBIT_SECRET` |

| Kraken | `KRAKEN_API_KEY`, `KRAKEN_SECRET` |

| KuCoin | `KUCOIN_API_KEY`, `KUCOIN_SECRET`, `KUCOIN_PASSWORD` |

| Coinbase | `COINBASE_API_KEY`, `COINBASE_SECRET` |

| Gate.io | `GATE_API_KEY`, `GATE_SECRET` |

| Huobi | `HUOBI_API_KEY`, `HUOBI_SECRET` |

| Bitget | `BITGET_API_KEY`, `BITGET_SECRET`, `BITGET_PASSWORD` |

## API Functions

### `load_ccxt_config_from_env(exchange, ...)`

Load exchange configuration from environment variables.

- *Parameters:**
- `exchange` (str): Exchange ID (e.g., 'binance', 'okx')
- `env_path` (str, optional): Custom .env file path
- `enable_rate_limit` (bool, default=True): Enable rate limiting
- `sandbox` (bool, default=False): Use sandbox/testnet mode

- *Returns:**
- `dict`: CCXT configuration dictionary

- *Example:**

```python
config = load_ccxt_config_from_env('binance', enable_rate_limit=True, sandbox=True)

```

### `get_exchange_credentials(exchange)`

Get only the credential fields (apiKey, secret, password), without other settings.

- *Parameters:**
- `exchange` (str): Exchange ID

- *Returns:**
- `dict`: Dictionary containing credentials

- *Example:**

```python
creds = get_exchange_credentials('okx')
print(creds['apiKey'])

```

### `list_supported_exchanges()`

Return the list of exchanges that support environment variable loading.

- *Returns:**
- `list`: List of exchange IDs

- *Example:**

```python
exchanges = list_supported_exchanges()
print(exchanges)  # ['okx', 'binance', 'bybit', ...]

```

### `load_dotenv_file(env_path=None)`

Manually load a .env file.

- *Parameters:**
- `env_path` (str, optional): Path to .env file. If None, searches default locations

- *Returns:**
- `bool`: True on success, False on failure

## Security Best Practices

1. **Never commit .env files to version control**
   - `.env` is already in `.gitignore`
   - Only commit `.env.example` as a template

1. **Use read-only API keys**
   - For backtesting and data fetching, use read-only API keys
   - Restrict IP whitelist
   - Disable withdrawal permissions

1. **Sandbox testing**
   - Test on exchange sandbox/testnet environments first

   ```python
   config = load_ccxt_config_from_env('okx', sandbox=True)
   ```

1. **Key rotation**
   - Rotate API keys regularly
   - Use different keys for different applications

## Troubleshooting

### Issue: `Missing required credential`

- *Cause:** Required credentials missing from .env file

- *Solution:**
1. Check that .env file exists
2. Confirm environment variable names are correct (use uppercase and underscores)
3. Ensure there are no extra spaces or quotes

### Issue: `python-dotenv not installed`

- *Solution:**

```bash
pip install python-dotenv

```

### Issue: Credentials not loading correctly

- *Debug:**

```python
from backtrader.ccxt import load_dotenv_file
import os

# Manual load

load_dotenv_file('.env')

# Check environment variables

print(os.getenv('OKX_API_KEY'))
print(os.getenv('OKX_SECRET'))

```

## Complete Example

See the example script:

- `examples/backtrader_ccxt_okex_sma.py` - OKX live trading example

Run tests:

```bash
python test_ccxt_config_helper.py

```
