"""Credential-safety regression tests for BtApiStore (iteration 12, S-3).

These tests lock in that live-trading credentials such as the CTP ``password``
and ``auth_code`` never leak through the store's ``repr``/``str`` rendering or
through the credential-masking helper used for debug logging.

They guard against accidental reintroduction of cleartext secrets into logs,
tracebacks or debugger output.
"""

from backtrader.stores.btapistore import BtApiStore

SECRET_PASSWORD = "sup3r-secret-pw"
SECRET_AUTH_CODE = "AUTHCODE-9988"
SECRET_API_KEY = "nested-api-key"
SECRET_PASSPHRASE = "nested-passphrase"


def _make_ctp_store():
    """Build a CTP-provider store carrying sensitive credentials.

    Returns:
        BtApiStore: A store instance with password/auth_code in its api kwargs.
    """
    return BtApiStore(
        provider="ctp",
        api_kwargs={
            "broker_id": "9999",
            "investor_id": "123456",
            "password": SECRET_PASSWORD,
            "auth_code": SECRET_AUTH_CODE,
            "app_id": "client_test",
        },
    )


def test_repr_does_not_leak_password():
    """repr(store) must not contain the cleartext password or auth_code."""
    store = _make_ctp_store()
    text = repr(store)
    assert SECRET_PASSWORD not in text
    assert SECRET_AUTH_CODE not in text


def test_str_does_not_leak_password():
    """str(store) must not contain the cleartext password or auth_code."""
    store = _make_ctp_store()
    text = str(store)
    assert SECRET_PASSWORD not in text
    assert SECRET_AUTH_CODE not in text


def test_repr_is_informative():
    """repr should still expose non-sensitive diagnostic fields."""
    store = _make_ctp_store()
    text = repr(store)
    assert "BtApiStore" in text
    assert "provider=" in text
    # Account id is rendered masked, not raw.
    assert "123456" not in text


def test_mask_sensitive_masks_known_secret_keys():
    """_mask_sensitive replaces secret values but keeps other fields intact."""
    masked = BtApiStore._mask_sensitive(
        {
            "broker_id": "9999",
            "password": SECRET_PASSWORD,
            "auth_code": SECRET_AUTH_CODE,
            "token": "abc",
        }
    )
    assert masked["broker_id"] == "9999"
    assert masked["password"] == "***"
    assert masked["auth_code"] == "***"
    assert masked["token"] == "***"


def test_mask_sensitive_handles_none():
    """_mask_sensitive returns an empty dict for None input."""
    assert BtApiStore._mask_sensitive(None) == {}


def test_mask_sensitive_is_case_insensitive():
    """Sensitive key matching ignores case."""
    masked = BtApiStore._mask_sensitive({"PassWord": SECRET_PASSWORD})
    assert masked["PassWord"] == "***"


def test_mask_sensitive_recursively_masks_exchange_kwargs_without_mutating_input():
    """Nested venue credentials are masked while ordinary options remain usable."""
    config = {
        "exchange_kwargs": {
            "BINANCE___SWAP": {
                "apiKey": SECRET_API_KEY,
                "api_secret": "binance-secret",
                "testnet": True,
                "timeout_ms": 5_000,
            },
            "OKX___SWAP": {
                "public_key": "okx-public-key",
                "secret": "okx-secret",
                "passphrase": SECRET_PASSPHRASE,
                "options": {
                    "account_credential": "nested-credential",
                    "simulated": True,
                },
            },
        },
        "symbol_routes": [
            {
                "symbol": "BTC-USDT-SWAP",
                "venue_token": "route-token",
                "leverage": 2,
            }
        ],
        "ordinary_tuple": (
            "visible",
            {"auth_token": "tuple-token", "market_data_only": True},
        ),
    }

    masked = BtApiStore._mask_sensitive(config)

    assert masked["exchange_kwargs"]["BINANCE___SWAP"] == {
        "apiKey": "***",
        "api_secret": "***",
        "testnet": True,
        "timeout_ms": 5_000,
    }
    assert masked["exchange_kwargs"]["OKX___SWAP"] == {
        "public_key": "***",
        "secret": "***",
        "passphrase": "***",
        "options": {
            "account_credential": "***",
            "simulated": True,
        },
    }
    assert masked["symbol_routes"] == [
        {
            "symbol": "BTC-USDT-SWAP",
            "venue_token": "***",
            "leverage": 2,
        }
    ]
    assert masked["ordinary_tuple"] == (
        "visible",
        {"auth_token": "***", "market_data_only": True},
    )
    assert isinstance(masked["ordinary_tuple"], tuple)

    assert config["exchange_kwargs"]["BINANCE___SWAP"]["apiKey"] == SECRET_API_KEY
    assert config["exchange_kwargs"]["OKX___SWAP"]["passphrase"] == SECRET_PASSPHRASE
    assert masked["exchange_kwargs"] is not config["exchange_kwargs"]
    assert masked["symbol_routes"] is not config["symbol_routes"]
