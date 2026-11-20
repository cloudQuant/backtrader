"""Credential masking for the notifications subsystem (iteration 32).

Notification logs, results and ``repr`` output must never leak credentials.
The masking semantics mirror ``backtrader/utils/log_message.py``
(``_RedactingFormatter``), but this module is deliberately independent of the
``logging`` stack: notifications do not travel through logging handlers, so the
redaction has to happen where the strings are produced.

Public helpers:

- :func:`mask_url` - keep ``scheme://host/path``, replace secret query values,
  URL passwords and path-embedded webhook tokens with ``***``.
- :func:`mask_text` - redact bearer tokens, ``key=value`` credential pairs and
  credentials embedded in URLs.
"""

import re

# Query parameters whose value must never be shown. The pattern is
# intentionally broad on the key name (anything containing token/key/secret/
# sign/password) so new channels stay covered without editing this list.
_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&])([A-Za-z0-9_.\-]*(?:token|key|secret|sign|password|passwd)[A-Za-z0-9_.\-]*)"
    r"=[^&#\s'\"<>)\]},;]*"
)
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic|QQBot)\s+[A-Za-z0-9._~+/=\-]+")
_SECRET_VALUE_RE = re.compile(
    r"(?i)(\b(?:password|passwd|passphrase|api[_-]?key|api[_-]?secret|"
    r"app[_-]?secret|corp[_-]?secret|secret|"
    r"access[_-]?token|refresh[_-]?token|context[_-]?token|"
    r"bot[_-]?token|authorization)\b[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}\])&#]+)"
)
_URL_PASSWORD_RE = re.compile(r"(://[^\s/:@]+:)[^\s/@]+(@)")

# Webhook channels that carry the credential in the URL *path*, not the query.
# Each pattern keeps the host and the structural path prefix (group 1) and
# replaces only the secret-bearing segment with MASK. Host/path anchoring
# keeps ordinary URLs (e.g. "/services/health", "/botany", "/api/webhooks/docs")
# untouched.
_PATH_SECRET_RES = (
    # Telegram Bot API: /bot<token>/<method> (or /file/bot<token>/...) on the
    # canonical host. Any token shape is covered here.
    re.compile(
        r"(?i)(https?://(?:[^/@\s]+@)?(?:api\.)?telegram\.org/(?:file/)?bot)"
        r"[^/?#\s'\"<>)\]},;]+"
    ),
    # Self-hosted / proxied Bot API servers: a /bot segment whose token carries
    # the universal "<id>:<hash>" (possibly percent-encoded) separator.
    re.compile(r"(?i)(https?://[^\s?#]+/bot)(?=[0-9]+(?:%3A|:))[^/?#\s'\"<>)\]},;]+"),
    # Slack incoming webhooks on canonical hosts: /services/<ws>/<ch>/<secret>.
    re.compile(
        r"(?i)(https?://(?:[^/@\s]+@)?"
        r"(?:hooks\.slack\.com|hooks\.slack-gov\.com)/services/"
        r"[^/?#\s]+/[^/?#\s]+/)[^/?#\s'\"<>)\]},;]+"
    ),
    # Custom / self-hosted / proxied Slack incoming webhooks: require canonical
    # uppercase Slack workspace/channel ID prefixes so ordinary paths such as
    # "/services/health" or "/services/billing/data/report" are never touched.
    re.compile(
        r"(?i)(https?://[^\s?#]+/services/(?-i:[TE][A-Z0-9]*/[BCGD][A-Z0-9]*/))"
        r"[^/?#\s'\"<>)\]},;]+"
    ),
    # Discord webhooks (canonical or custom/self-hosted proxies):
    # /api/[v<N>/]webhooks/<numeric-id>/<token>. Numeric-id anchoring keeps
    # "/api/webhooks/docs" untouched.
    re.compile(
        r"(?i)(https?://[^\s?#]+/api/(?:v[0-9]+/)?webhooks/[0-9]+/)[^/?#\s'\"<>)\]},;]+"
    ),
    # Feishu / Lark custom-robot webhooks: /open-apis/bot/v<N>/hook/<token>.
    re.compile(r"(?i)(https?://[^\s?#]+/open-apis/bot/v[0-9]+/hook/)[^/?#\s'\"<>)\]},;]+"),
)

MASK = "***"


def _mask_path_secrets(text):
    """Replace path-embedded webhook tokens in ``text`` with MASK."""
    for pattern in _PATH_SECRET_RES:
        text = pattern.sub(r"\1" + MASK, text)
    return text


def mask_url(url):
    """Return ``url`` with credential query values and path secrets replaced by ``***``.

    Args:
        url: URL-like object; converted with ``str()`` first.

    Returns:
        str: The URL with secret query values, URL passwords and
        path-embedded webhook tokens masked.
    """
    masked = _SECRET_QUERY_RE.sub(r"\1\2=" + MASK, str(url))
    masked = _URL_PASSWORD_RE.sub(r"\1" + MASK + r"\2", masked)
    masked = _mask_path_secrets(masked)
    return _BEARER_RE.sub(r"\1 " + MASK, masked)


def mask_text(text):
    """Return ``text`` with credential-looking substrings replaced by ``***``.

    Args:
        text: Arbitrary text (log line, error message, ``repr`` body).

    Returns:
        str: The text with bearer tokens, ``key: value`` credential pairs,
        URL query secrets, URL passwords and path-embedded webhook tokens
        masked.
    """
    masked = _BEARER_RE.sub(r"\1 " + MASK, str(text))
    masked = _SECRET_QUERY_RE.sub(r"\1\2=" + MASK, masked)
    masked = _SECRET_VALUE_RE.sub(r"\1" + MASK, masked)
    masked = _URL_PASSWORD_RE.sub(r"\1" + MASK + r"\2", masked)
    return _mask_path_secrets(masked)
