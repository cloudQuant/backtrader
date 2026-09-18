"""Credential masking for the notifications subsystem (iteration 32).

Notification logs, results and ``repr`` output must never leak credentials.
The masking semantics mirror ``backtrader/utils/log_message.py``
(``_RedactingFormatter``), but this module is deliberately independent of the
``logging`` stack: notifications do not travel through logging handlers, so the
redaction has to happen where the strings are produced.

Public helpers:

- :func:`mask_url` - keep ``scheme://host/path``, replace secret query values
  with ``***``.
- :func:`mask_text` - redact bearer tokens, ``key=value`` credential pairs and
  credentials embedded in URLs.
"""

import re

# Query parameters whose value must never be shown. The pattern is
# intentionally broad on the key name (anything containing token/key/secret/
# sign/password) so new channels stay covered without editing this list.
_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&])([A-Za-z0-9_.\-]*(?:token|key|secret|sign|password|passwd)[A-Za-z0-9_.\-]*)=[^&#\s]*"
)
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic|QQBot)\s+[A-Za-z0-9._~+/=\-]+")
_SECRET_VALUE_RE = re.compile(
    r"(?i)(\b(?:password|passwd|passphrase|api[_-]?key|api[_-]?secret|secret|"
    r"access[_-]?token|refresh[_-]?token|context[_-]?token|appsecret|corpsecret|"
    r"bot[_-]?token|authorization)\b[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)
_URL_PASSWORD_RE = re.compile(r"(://[^\s/:@]+:)[^\s/@]+(@)")

MASK = "***"


def mask_url(url):
    """Return ``url`` with credential query values replaced by ``***``.

    Args:
        url: URL-like object; converted with ``str()`` first.

    Returns:
        str: The URL with secret query values and URL passwords masked.
    """
    masked = _SECRET_QUERY_RE.sub(r"\1\2=" + MASK, str(url))
    masked = _URL_PASSWORD_RE.sub(r"\1" + MASK + r"\2", masked)
    return _BEARER_RE.sub(r"\1 " + MASK, masked)


def mask_text(text):
    """Return ``text`` with credential-looking substrings replaced by ``***``.

    Args:
        text: Arbitrary text (log line, error message, ``repr`` body).

    Returns:
        str: The text with bearer tokens, ``key: value`` credential pairs and
        URL passwords masked.
    """
    masked = _BEARER_RE.sub(r"\1 " + MASK, str(text))
    masked = _SECRET_VALUE_RE.sub(r"\1" + MASK, masked)
    return _URL_PASSWORD_RE.sub(r"\1" + MASK + r"\2", masked)
