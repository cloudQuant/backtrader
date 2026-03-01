#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared fixtures for CCXT and CTP integration tests.

These tests require:
1. Valid exchange API credentials in .env
2. Network access to exchange APIs
3. pytest marker: -m integration

Usage:
    # Run all integration tests
    pytest tests/integration/ -m integration -v

    # Run only CTP tests
    pytest tests/integration/ -k ctp -m integration -v

    # Run only WS tests
    pytest tests/integration/ -m "integration and websocket" -v

    # Run read-only tests (no orders)
    pytest tests/integration/ -m "integration and not trading" -v
"""

import os
import sys
import pytest
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---- Helper functions ----

def _load_env():
    """Load .env from project root."""
    try:
        from dotenv import load_dotenv
        env_path = PROJECT_ROOT / '.env'
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            return True
    except ImportError:
        pass
    return False


def _has_okx_credentials():
    """Check if OKX credentials are available."""
    return all([
        os.getenv('OKX_API_KEY'),
        os.getenv('OKX_SECRET'),
        os.getenv('OKX_PASSWORD'),
    ])


def _has_binance_credentials():
    """Check if Binance credentials are available."""
    return all([
        os.getenv('BINANCE_API_KEY'),
        os.getenv('BINANCE_SECRET'),
    ])


def _has_ctp_credentials():
    """Check if CTP (SimNow) credentials are available."""
    return all([
        os.getenv('simnow_user_id'),
        os.getenv('simnow_password'),
    ])


def _has_ctp_module():
    """Check if ctp-python is installed."""
    try:
        import ctp
        return True
    except ImportError:
        return False


def _has_ccxtpro():
    """Check if ccxt.pro is available."""
    try:
        import ccxt.pro
        return True
    except (ImportError, AttributeError):
        return False


def _use_sandbox():
    """Check if sandbox/demo mode should be used (based on OKX_SANDBOX env var)."""
    val = os.getenv('OKX_SANDBOX', 'false').strip().lower()
    return val in ('true', '1', 'yes')


# Load env at import time
_load_env()


# ---- Skip conditions ----

skip_no_okx = pytest.mark.skipif(
    not _has_okx_credentials(),
    reason="OKX credentials not found in .env"
)

skip_no_binance = pytest.mark.skipif(
    not _has_binance_credentials(),
    reason="Binance credentials not found in .env"
)

skip_no_ccxtpro = pytest.mark.skipif(
    not _has_ccxtpro(),
    reason="ccxt.pro (ccxt[async]) not installed"
)

skip_no_ctp = pytest.mark.skipif(
    not (_has_ctp_credentials() and _has_ctp_module()),
    reason="CTP credentials not found in .env or ctp-python not installed"
)


# ---- Fixtures ----

@pytest.fixture(scope="session")
def okx_config():
    """OKX exchange configuration for sandbox/demo mode."""
    if not _has_okx_credentials():
        pytest.skip("OKX credentials not available")

    config = {
        'apiKey': os.getenv('OKX_API_KEY'),
        'secret': os.getenv('OKX_SECRET'),
        'password': os.getenv('OKX_PASSWORD'),
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',
        },
    }

    # Apply proxy from .env if available (needed for GFW bypass)
    proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
    if proxy_url:
        # REST API proxy (requests/urllib)
        config['proxies'] = {
            'http': proxy_url,
            'https': proxy_url,
        }
        # Async WebSocket proxy (aiohttp)
        config['aiohttp_proxy'] = proxy_url

    # Pre-check: verify IP whitelist with a lightweight REST call
    try:
        import ccxt
        from ccxt.base.errors import PermissionDenied, AuthenticationError, NetworkError
        _ex = ccxt.okx(config)
        if _use_sandbox():
            _ex.set_sandbox_mode(True)
        _ex.load_markets()
    except (PermissionDenied, AuthenticationError) as e:
        pytest.skip(f"OKX API access denied (IP whitelist?): {e}")
    except NetworkError as e:
        pytest.skip(f"OKX network unreachable: {e}")
    except Exception:
        pass  # Other errors — let individual tests handle

    return config


@pytest.fixture(scope="function")
def ccxt_store(okx_config):
    """Create a CCXTStore connected to OKX."""
    from backtrader.stores.ccxtstore import CCXTStore
    from ccxt.base.errors import PermissionDenied, AuthenticationError, NetworkError

    # Reset singleton for test isolation
    CCXTStore._instances = {}

    try:
        store = CCXTStore(
            exchange='okx',
            currency='USDT',
            config=okx_config,
            retries=1,
            debug=True,
            sandbox=_use_sandbox(),
        )
    except (PermissionDenied, AuthenticationError) as e:
        pytest.skip(f"CCXTStore init failed (IP whitelist?): {e}")
    except NetworkError as e:
        pytest.skip(f"CCXTStore network unreachable: {e}")

    yield store
    try:
        store.stop()
    except Exception:
        pass


@pytest.fixture(scope="function")
def ccxt_exchange(okx_config):
    """Create a raw ccxt exchange instance for OKX."""
    import ccxt
    from ccxt.base.errors import PermissionDenied, AuthenticationError, NetworkError
    exchange = ccxt.okx(okx_config)
    if _use_sandbox():
        exchange.set_sandbox_mode(True)
    # Verify connectivity — skip early if IP not whitelisted or network down
    try:
        exchange.load_markets()
    except (PermissionDenied, AuthenticationError) as e:
        pytest.skip(f"OKX API access denied (IP whitelist?): {e}")
    except NetworkError as e:
        pytest.skip(f"OKX network unreachable: {e}")
    return exchange


@pytest.fixture(scope="function")
def ccxt_pro_exchange(okx_config):
    """Create a ccxt.pro exchange instance for OKX."""
    try:
        import ccxt.pro as ccxtpro
    except (ImportError, AttributeError):
        pytest.skip("ccxt.pro not available")
    from ccxt.base.errors import PermissionDenied, AuthenticationError, NetworkError

    exchange = ccxtpro.okx(okx_config)
    if _use_sandbox():
        exchange.set_sandbox_mode(True)
    # Verify connectivity — skip early if IP not whitelisted or network down
    try:
        exchange.load_markets()
    except (PermissionDenied, AuthenticationError) as e:
        pytest.skip(f"OKX API access denied (IP whitelist?): {e}")
    except NetworkError as e:
        pytest.skip(f"OKX network unreachable: {e}")
    return exchange


# ---- CTP Fixtures ----

# CTP test server endpoints
# SimNow Set 1 (penetrating front, uses monitoring center production key, recommended)
CTP_SIMNOW_SET1_TD = 'tcp://182.254.243.31:30001'
CTP_SIMNOW_SET1_MD = 'tcp://182.254.243.31:30011'
# SimNow Set 2
CTP_SIMNOW_SET2_TD = 'tcp://182.254.243.31:30002'
CTP_SIMNOW_SET2_MD = 'tcp://182.254.243.31:30012'
# SimNow Set 3
CTP_SIMNOW_SET3_TD = 'tcp://182.254.243.31:30003'
CTP_SIMNOW_SET3_MD = 'tcp://182.254.243.31:30013'
# SimNow 7x24 (2nd env, requires separate registration)
CTP_SIMNOW_7X24_V2_TD = 'tcp://182.254.243.31:40001'
CTP_SIMNOW_7X24_V2_MD = 'tcp://182.254.243.31:40011'
# SimNow 7x24 test server (old)
CTP_SIMNOW_7X24_TD = 'tcp://180.168.146.187:10130'
CTP_SIMNOW_7X24_MD = 'tcp://180.168.146.187:10131'
# SimNow normal trading hours
CTP_SIMNOW_TRADE_TD = 'tcp://180.168.146.187:10201'
CTP_SIMNOW_TRADE_MD = 'tcp://180.168.146.187:10211'
# OpenCTP 7x24
CTP_OPENCTP_TD = 'tcp://121.37.80.177:20002'
CTP_OPENCTP_MD = 'tcp://121.37.80.177:20004'


def _find_reachable_ctp_server(timeout=3):
    """Find a reachable CTP server from known SimNow/OpenCTP endpoints.

    Also respects CTP_TD_FRONT / CTP_MD_FRONT env vars (highest priority).
    """
    import socket

    # Check env overrides first
    env_td = os.getenv('CTP_TD_FRONT')
    env_md = os.getenv('CTP_MD_FRONT')
    if env_td and env_md:
        return 'env-override', env_td, env_md

    servers = [
        ('SimNow-Set1', CTP_SIMNOW_SET1_TD, CTP_SIMNOW_SET1_MD),
        ('SimNow-Set2', CTP_SIMNOW_SET2_TD, CTP_SIMNOW_SET2_MD),
        ('SimNow-Set3', CTP_SIMNOW_SET3_TD, CTP_SIMNOW_SET3_MD),
        ('SimNow-7x24-v2', CTP_SIMNOW_7X24_V2_TD, CTP_SIMNOW_7X24_V2_MD),
        ('SimNow-7x24', CTP_SIMNOW_7X24_TD, CTP_SIMNOW_7X24_MD),
        ('SimNow-Trade', CTP_SIMNOW_TRADE_TD, CTP_SIMNOW_TRADE_MD),
        ('OpenCTP', CTP_OPENCTP_TD, CTP_OPENCTP_MD),
    ]
    for name, td, md in servers:
        try:
            # Parse host:port from tcp://host:port
            parts = td.replace('tcp://', '').split(':')
            host, port = parts[0], int(parts[1])
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((host, port))
            s.close()
            return name, td, md
        except (socket.timeout, socket.error, OSError):
            continue
    return None, None, None


@pytest.fixture(scope="session")
def ctp_config():
    """CTP configuration for SimNow test environment."""
    if not _has_ctp_credentials():
        pytest.skip("CTP credentials not available")
    if not _has_ctp_module():
        pytest.skip("ctp-python not installed")

    server_name, td_front, md_front = _find_reachable_ctp_server()
    if td_front is None:
        pytest.skip("No reachable CTP server found")

    config = {
        'td_front': td_front,
        'md_front': md_front,
        'broker_id': '9999',
        'user_id': os.getenv('simnow_user_id'),
        'password': os.getenv('simnow_password'),
        'app_id': 'simnow_client_test',
        'auth_code': '0000000000000000',
        'server_name': server_name,
    }
    return config


@pytest.fixture(scope="session")
def ctp_store(ctp_config):
    """Create a CTPStore connected to SimNow (session-scoped to avoid login ban).

    CTP has strict rate-limiting on login attempts (error 75). Using session
    scope ensures we only connect once for all integration tests.
    """
    from backtrader.stores.ctpstore import CTPStore

    # Reset singleton for clean state
    CTPStore._reset_instance()

    store = CTPStore(ctp_setting=ctp_config)
    if not store.is_connected:
        trader_err = getattr(store.trader_spi, 'login_error', None)
        CTPStore._reset_instance()
        if trader_err and trader_err[0] == 75:
            pytest.skip(f"CTP login banned (error 75): {trader_err[1]}")
        pytest.skip(f"CTPStore failed to connect/login: {trader_err}")

    yield store

    try:
        store._feed_count = 0  # force full stop
        store.stop()
    except Exception:
        pass
    CTPStore._reset_instance()
