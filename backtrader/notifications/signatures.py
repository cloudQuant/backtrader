"""Webhook signature helpers for notifications (iteration 32).

Two signing schemes are needed:

- DingTalk custom robot (加签): ``timestamp + "\n" + secret`` is the signed
  string and the **secret is the HMAC key**; the digest is base64 encoded and
  percent-encoded into the query string. Timestamp is in milliseconds.
- Feishu custom robot: ``timestamp + "\n" + secret`` is the HMAC **key** and the
  signed message is empty; the digest is base64 encoded. Timestamp is in
  seconds.

Evidence level: the constructions follow the published descriptions, but
neither was compared against an official sample vector in this offline round
(see ``evidence/channel-facts.json``). The unit tests therefore assert
self-consistency (a recomputed digest matches) and stability, not a magic
constant.

Both functions take an explicit ``timestamp`` so tests are deterministic and so
callers can prove the signature is recomputed per send rather than cached.
"""

import base64
import hashlib
import hmac
import time
from urllib.parse import quote


def _require_secret(secret):
    """Validate the signing secret.

    Args:
        secret: Candidate secret.

    Returns:
        str: The validated secret.

    Raises:
        ValueError: If the secret is missing or not a non-empty string.
    """
    if not isinstance(secret, str) or not secret:
        raise ValueError("signing secret must be a non-empty string")
    return secret


def hmac_sha256_b64(key, message):
    """Return the base64 of ``HMAC-SHA256(key, message)``.

    Args:
        key: Key bytes.
        message: Message bytes.

    Returns:
        str: Base64-encoded digest.
    """
    digest = hmac.new(key, message, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def dingtalk_sign(secret, timestamp=None):
    """Build the DingTalk signed query parameters.

    Args:
        secret: The robot's 加签 secret.
        timestamp: Millisecond timestamp; defaults to the current time.

    Returns:
        tuple: ``(timestamp_ms, url_encoded_sign)``.

    Raises:
        ValueError: If ``secret`` is empty.
    """
    secret = _require_secret(secret)
    if timestamp is None:
        timestamp = int(time.time() * 1000)
    timestamp = int(timestamp)
    string_to_sign = "{0}\n{1}".format(timestamp, secret)
    digest = hmac_sha256_b64(secret.encode("utf-8"), string_to_sign.encode("utf-8"))
    return timestamp, quote(digest, safe="")


def feishu_sign(secret, timestamp=None):
    """Build the Feishu custom-robot signature.

    Args:
        secret: The robot's signing secret.
        timestamp: Second timestamp; defaults to the current time.

    Returns:
        tuple: ``(timestamp_s, sign)``.

    Raises:
        ValueError: If ``secret`` is empty.
    """
    secret = _require_secret(secret)
    if timestamp is None:
        timestamp = int(time.time())
    timestamp = int(timestamp)
    string_to_sign = "{0}\n{1}".format(timestamp, secret)
    digest = hmac_sha256_b64(string_to_sign.encode("utf-8"), b"")
    return timestamp, digest
