"""AC32-06: signature construction and per-send recomputation."""

import hashlib
import hmac
import time

import pytest

from backtrader.notifications.signatures import dingtalk_sign, feishu_sign, hmac_sha256_b64


def _expected_dingtalk(secret, timestamp):
    """Independently recompute the DingTalk digest for comparison."""
    import base64
    from urllib.parse import quote

    string_to_sign = "{0}\n{1}".format(timestamp, secret)
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return quote(base64.b64encode(digest).decode("utf-8"), safe="")


def _expected_feishu(secret, timestamp):
    """Independently recompute the Feishu digest for comparison."""
    import base64

    key = "{0}\n{1}".format(timestamp, secret).encode("utf-8")
    digest = hmac.new(key, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def test_hmac_helper_matches_stdlib():
    """The shared HMAC helper is a thin, correct wrapper."""
    import base64

    expected = base64.b64encode(hmac.new(b"key", b"message", hashlib.sha256).digest()).decode(
        "utf-8"
    )
    assert hmac_sha256_b64(b"key", b"message") == expected


def test_dingtalk_sign_is_deterministic_for_a_fixed_timestamp():
    """A fixed timestamp yields the documented construction."""
    timestamp, sign = dingtalk_sign("secret-value", timestamp=1700000000000)
    assert timestamp == 1700000000000
    assert sign == _expected_dingtalk("secret-value", 1700000000000)


def test_dingtalk_sign_is_recomputed_each_call():
    """Signatures are never cached: a new timestamp changes the digest."""
    first_ts, first_sign = dingtalk_sign("secret-value")
    time.sleep(0.005)
    second_ts, second_sign = dingtalk_sign("secret-value")
    assert first_ts != second_ts or first_sign != second_sign
    assert first_sign != second_sign


def test_feishu_sign_uses_timestamp_and_secret_as_key():
    """The Feishu digest signs an empty message with ``timestamp\\nsecret``."""
    timestamp, sign = feishu_sign("secret-value", timestamp=1700000000)
    assert timestamp == 1700000000
    assert sign == _expected_feishu("secret-value", 1700000000)


def test_signatures_reject_missing_secret():
    """An empty secret is a configuration error."""
    with pytest.raises(ValueError):
        dingtalk_sign("")
    with pytest.raises(ValueError):
        feishu_sign(None)


def test_dingtalk_sign_is_url_encoded():
    """Base64 characters that are unsafe in a query string are encoded."""
    _, sign = dingtalk_sign("secret-value", timestamp=1700000000000)
    assert "+" not in sign and "/" not in sign and "=" not in sign
