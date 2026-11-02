"""Credential redaction for diagnostics and exception surfaces."""

from dataclasses import dataclass

from backtrader.utils.redaction import (
    is_sensitive_key,
    masked_copy,
    redact_diagnostic,
)


def test_sensitive_key_detection_handles_common_spellings():
    assert is_sensitive_key("password")
    assert is_sensitive_key("PASSWORD")
    assert is_sensitive_key("api-secret")
    assert is_sensitive_key("apiSecret")
    assert is_sensitive_key("broker_auth_code")
    assert not is_sensitive_key("symbol")
    assert not is_sensitive_key("open_price")


def test_redaction_masks_mappings_lists_and_tuples():
    value = {
        "password": "secret-value",
        "nested": {"api_key": "k", "safe": "ok"},
        "items": [{"token": "t"}, ("auth_code", "a")],
        "count": 2,
    }

    redacted = redact_diagnostic(value)

    assert redacted["password"] == "***"
    assert redacted["nested"]["api_key"] == "***"
    assert redacted["nested"]["safe"] == "ok"
    assert redacted["items"][0]["token"] == "***"
    assert redacted["items"][1] == ("auth_code", "a")
    assert redacted["count"] == 2


def test_redaction_masks_inline_credential_patterns():
    text = (
        "password=hunter2 Authorization: Bearer abc.def "
        "https://example.test/?api_key=k&symbol=rb2510&token=t"
    )

    redacted = redact_diagnostic(text)

    assert "hunter2" not in redacted
    assert "abc.def" not in redacted
    assert "api_key=***" in redacted
    assert "token=t" not in redacted


def test_exception_values_are_reduced_to_their_type_name():
    assert redact_diagnostic(ValueError("password=leak")) == "ValueError"
    assert masked_copy(ValueError("password=leak")) == "ValueError"


def test_masked_copy_is_cycle_safe_for_plain_objects():
    class Payload:
        def __init__(self):
            self.api_key = "leak"
            self.safe = "ok"

    payload = Payload()
    payload.self = payload

    masked = masked_copy(payload)

    assert masked["api_key"] == "***"
    assert masked["safe"] == "ok"
    assert masked["self"] == "<recursive>"


@dataclass
class Credentials:
    password: str
    region: str


def test_masked_copy_handles_dataclasses():
    masked = masked_copy(Credentials(password="leak", region="cn"))

    assert masked == {"password": "***", "region": "cn"}
