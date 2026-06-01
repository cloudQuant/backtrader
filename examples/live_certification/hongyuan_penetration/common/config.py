"""宏源期货仿真环境配置与凭证管理."""
from __future__ import annotations

import os

HONGYUAN_ENVIRONMENTS = {
    "telecom": {
        "name": "宏源期货仿真（电信）",
        "td_address": "tcp://101.230.79.235:32205",
        "md_address": "tcp://101.230.79.235:32213",
        "description": "上海唐银机房，电信线路，BrokerID=3070，v6.7.10_20250422 API",
    },
    "unicom": {
        "name": "宏源期货仿真（联通）",
        "td_address": "tcp://112.65.19.116:32205",
        "md_address": "tcp://112.65.19.116:32213",
        "description": "上海唐银机房，联通线路，BrokerID=3070，v6.7.10_20250422 API",
    },
}

DEFAULT_ENV = "telecom"
DEFAULT_BROKER_ID = "3070"
DEFAULT_APP_ID = "client_wtyj_1.0.9.9"
DEFAULT_AUTH_CODE = "VCSX4A2S43I4RN25"
DEFAULT_ORDER_SYMBOL = "rb2605"
DEFAULT_TICK_SYMBOL = "rb2605"


def get_credentials():
    """Get Hongyuan credentials from environment variables."""
    investor_id = os.getenv("HONGYUAN_USER_ID") or os.getenv("hongyuan_user_id")
    password = os.getenv("HONGYUAN_PASSWORD") or os.getenv("hongyuan_password")
    if not investor_id or not password:
        raise RuntimeError(
            "宏源期货凭证未找到。"
            "请在环境变量或 .env 文件中设置 HONGYUAN_USER_ID 和 HONGYUAN_PASSWORD。"
        )
    return investor_id, password


def get_env_key():
    """Get the Hongyuan environment key from env var or default."""
    return os.getenv("HONGYUAN_ENV", DEFAULT_ENV)


def get_order_symbol():
    """Get the symbol to use for order tests."""
    return os.getenv(
        "HONGYUAN_ORDER_SYMBOL",
        os.getenv("HONGYUAN_TICK_SYMBOL", DEFAULT_ORDER_SYMBOL),
    )


def get_tick_symbol():
    """Get the symbol to use for tick / market-data tests."""
    return os.getenv("HONGYUAN_TICK_SYMBOL", DEFAULT_TICK_SYMBOL)


def create_config(env_key=None):
    """Create Hongyuan connection configuration dict."""
    env_key = env_key or get_env_key()
    if env_key not in HONGYUAN_ENVIRONMENTS:
        raise ValueError(
            f"Invalid environment key: {env_key}. "
            f"Valid keys: {', '.join(HONGYUAN_ENVIRONMENTS)}"
        )
    env = HONGYUAN_ENVIRONMENTS[env_key]
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
