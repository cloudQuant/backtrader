"""SimNow environment configuration and credential management."""
from __future__ import annotations

import os

SIMNOW_ENVIRONMENTS = {
    "new_7x24": {
        "name": "新7x24环境（看穿式前置）",
        "td_address": "tcp://182.254.243.31:40001",
        "md_address": "tcp://182.254.243.31:40011",
        "description": "7x24看穿式前置，使用监控中心生产秘钥",
    },
    "new_group1": {
        "name": "新第一组（看穿式前置）",
        "td_address": "tcp://182.254.243.31:30001",
        "md_address": "tcp://182.254.243.31:30011",
        "description": "看穿式前置",
    },
    "new_group2": {
        "name": "新第二组（看穿式前置）",
        "td_address": "tcp://182.254.243.31:30002",
        "md_address": "tcp://182.254.243.31:30012",
        "description": "看穿式前置",
    },
    "new_group3": {
        "name": "新第三组（看穿式前置）",
        "td_address": "tcp://182.254.243.31:30003",
        "md_address": "tcp://182.254.243.31:30013",
        "description": "看穿式前置",
    },
}

DEFAULT_ENV = "new_7x24"
DEFAULT_BROKER_ID = "9999"
DEFAULT_APP_ID = "simnow_client_test"
DEFAULT_AUTH_CODE = "0000000000000000"
DEFAULT_ORDER_SYMBOL = "rb2610"
DEFAULT_TICK_SYMBOL = "rb2610"


def get_credentials():
    """Get SimNow credentials from environment variables."""
    investor_id = os.getenv("simnow_user_id") or os.getenv("SIMNOW_USER_ID")
    password = os.getenv("simnow_password") or os.getenv("SIMNOW_PASSWORD")
    if not investor_id or not password:
        raise RuntimeError(
            "SimNow credentials not found. "
            "Set SIMNOW_USER_ID and SIMNOW_PASSWORD in environment or .env file."
        )
    return investor_id, password


def get_env_key():
    """Get the SimNow environment key from env var or default."""
    return os.getenv("SIMNOW_ENV", DEFAULT_ENV)


def get_order_symbol():
    """Get the symbol to use for order tests."""
    return os.getenv(
        "SIMNOW_ORDER_SYMBOL",
        os.getenv("SIMNOW_TICK_SYMBOL", DEFAULT_ORDER_SYMBOL),
    )


def get_tick_symbol():
    """Get the symbol to use for tick / market-data tests."""
    return os.getenv("SIMNOW_TICK_SYMBOL", DEFAULT_TICK_SYMBOL)


def create_config(env_key=None):
    """Create SimNow connection configuration dict."""
    env_key = env_key or get_env_key()
    if env_key not in SIMNOW_ENVIRONMENTS:
        raise ValueError(
            f"Invalid environment key: {env_key}. "
            f"Valid keys: {', '.join(SIMNOW_ENVIRONMENTS)}"
        )
    env = SIMNOW_ENVIRONMENTS[env_key]
    investor_id, password = get_credentials()
    return {
        "td_address": env["td_address"],
        "md_address": env["md_address"],
        "broker_id": DEFAULT_BROKER_ID,
        "investor_id": investor_id,
        "password": password,
        "app_id": DEFAULT_APP_ID,
        "auth_code": DEFAULT_AUTH_CODE,
    }
