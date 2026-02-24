#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared fixtures for CCXT integration tests.

These tests require:
1. Valid exchange API credentials in .env
2. Network access to exchange APIs
3. pytest marker: -m integration

Usage:
    # Run all integration tests
    pytest tests/integration/ -m integration -v

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


def _has_ccxtpro():
    """Check if ccxt.pro is available."""
    try:
        import ccxt.pro
        return True
    except (ImportError, AttributeError):
        return False


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


# ---- Fixtures ----

@pytest.fixture(scope="session")
def okx_config():
    """OKX exchange configuration for sandbox/demo mode."""
    if not _has_okx_credentials():
        pytest.skip("OKX credentials not available")

    return {
        'apiKey': os.getenv('OKX_API_KEY'),
        'secret': os.getenv('OKX_SECRET'),
        'password': os.getenv('OKX_PASSWORD'),
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',
        },
    }


@pytest.fixture(scope="function")
def ccxt_store(okx_config):
    """Create a CCXTStore connected to OKX (sandbox mode)."""
    from backtrader.stores.ccxtstore import CCXTStore
    from ccxt.base.errors import PermissionDenied, AuthenticationError

    # Reset singleton for test isolation
    CCXTStore._instances = {}

    try:
        store = CCXTStore(
            exchange='okx',
            currency='USDT',
            config=okx_config,
            retries=1,
            debug=True,
            sandbox=True,
        )
    except (PermissionDenied, AuthenticationError) as e:
        pytest.skip(f"CCXTStore init failed (IP whitelist?): {e}")

    yield store
    try:
        store.stop()
    except Exception:
        pass


@pytest.fixture(scope="function")
def ccxt_exchange(okx_config):
    """Create a raw ccxt exchange instance for OKX sandbox."""
    import ccxt
    exchange = ccxt.okx(okx_config)
    exchange.set_sandbox_mode(True)
    return exchange


@pytest.fixture(scope="function")
def ccxt_pro_exchange(okx_config):
    """Create a ccxt.pro exchange instance for OKX sandbox (async WebSocket)."""
    try:
        import ccxt.pro as ccxtpro
    except (ImportError, AttributeError):
        pytest.skip("ccxt.pro not available")

    exchange = ccxtpro.okx(okx_config)
    exchange.set_sandbox_mode(True)
    return exchange
