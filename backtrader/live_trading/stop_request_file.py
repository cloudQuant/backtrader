"""Opt-in stop-request file source (iteration 66, §5.2 B1 remainder).

A supervisor (``bt_api_runtime``) may publish a stop request into its own
restricted control directory when the signal channel is unavailable (Windows
without a console, a process adopted after a runtime restart).  This module is
the read-only strategy-side consumer:

``<runtime control dir>/stop_request.json`` (``bt_api_stop_request/v1``)::

    {
      "schema": "bt_api_stop_request/v1",
      "strategy_uuid": "<UUID>",   # target strategy; a cross-unit request is refused
      "run_id": "<UUID>",          # target run; an old/duplicate request is refused
      "command_id": "<UUID>",
      "nonce": "<UUID>",           # one-time; a second different nonce is ignored
      "requested_at_utc": "<ISO-8601 UTC>",
      "expires_at_utc": "<ISO-8601 UTC>"
    }

The file is opened read-only exactly once per poll; nothing is created,
renamed or marked.  A missing, unreadable, oversized, malformed, unknown-schema,
expired, future-dated or identity-mismatched document yields ``None``: absence
of a provable request is never turned into a stop.  The first accepted nonce is
remembered in memory so the same file (a duplicate read) is idempotent and a
different nonce for the same run is refused rather than resetting the request.
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
from typing import Any, Optional, Tuple

__all__ = ("STOP_REQUEST_FILE_SCHEMA", "STOP_REQUEST_SOURCE", "StopRequestFileSource")

STOP_REQUEST_FILE_SCHEMA = "bt_api_stop_request/v1"
STOP_REQUEST_SOURCE = "stop_file"
MAX_REQUEST_BYTES = 4096
MAX_REQUEST_TTL_S = 86400.0
MAX_FUTURE_SKEW_S = 60.0

_FIELDS = frozenset(
    {
        "schema",
        "strategy_uuid",
        "run_id",
        "command_id",
        "nonce",
        "requested_at_utc",
        "expires_at_utc",
    }
)
_UTC = datetime.timezone.utc


def _canonical_uuid(value: Any) -> Optional[str]:
    if type(value) is not str:
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _utc_moment(value: Any) -> Optional[datetime.datetime]:
    if type(value) is not str or not value or len(value) > 64:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != datetime.timedelta(0):
        return None
    return parsed.astimezone(_UTC)


def _read_document(path: str) -> Optional[Any]:
    """One bounded, read-only open; a symlink or any fault is not a request."""
    try:
        if os.path.islink(path):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            payload = handle.read(MAX_REQUEST_BYTES + 1)
    except (OSError, UnicodeError):
        return None
    if len(payload.encode("utf-8", "surrogatepass")) > MAX_REQUEST_BYTES:
        return None
    try:
        return json.loads(payload)
    except ValueError:
        return None


class StopRequestFileSource:
    """Read one explicit request path bound to this strategy and run."""

    def __init__(
        self,
        path: Any,
        *,
        strategy_uuid: str,
        run_id: str,
        clock: Optional[Any] = None,
    ) -> None:
        text = os.fspath(path)
        if type(text) is not str or not text:
            raise ValueError("path")
        self.path = text
        canonical_strategy = _canonical_uuid(strategy_uuid)
        canonical_run = _canonical_uuid(run_id)
        if canonical_strategy is None:
            raise ValueError("strategy_uuid")
        if canonical_run is None:
            raise ValueError("run_id")
        self.strategy_uuid = canonical_strategy
        self.run_id = canonical_run
        self._clock = clock or (lambda: datetime.datetime.now(_UTC))
        self._accepted_nonce: Optional[str] = None
        self._accepted_state: Optional[Tuple[str, Optional[str]]] = None

    def poll(self) -> Optional[Tuple[str, Optional[str]]]:
        """Return the first provable ``("stop_file", at_utc)`` or ``None``."""
        document = _read_document(self.path)
        if document is None:
            return None
        request = self._request(document)
        if request is None:
            return None
        nonce, state = request
        if self._accepted_nonce is None:
            self._accepted_nonce = nonce
            self._accepted_state = state
            return state
        if nonce == self._accepted_nonce:
            return self._accepted_state
        # A second, different request for the same run is not allowed to reset
        # the first one (fail closed); it is ignored.
        return None

    def _request(self, document: Any) -> Optional[Tuple[str, Tuple[str, Optional[str]]]]:
        if type(document) is not dict or set(document) != _FIELDS:
            return None
        if document.get("schema") != STOP_REQUEST_FILE_SCHEMA:
            return None
        strategy_uuid = _canonical_uuid(document.get("strategy_uuid"))
        run_id = _canonical_uuid(document.get("run_id"))
        command_id = _canonical_uuid(document.get("command_id"))
        nonce = _canonical_uuid(document.get("nonce"))
        if None in (strategy_uuid, run_id, command_id, nonce):
            return None
        if strategy_uuid != self.strategy_uuid or run_id != self.run_id:
            return None

        requested = _utc_moment(document.get("requested_at_utc"))
        expires = _utc_moment(document.get("expires_at_utc"))
        if requested is None or expires is None or expires <= requested:
            return None
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=_UTC)
        now = now.astimezone(_UTC)
        if (expires - requested).total_seconds() > MAX_REQUEST_TTL_S:
            return None
        if requested > now + datetime.timedelta(seconds=MAX_FUTURE_SKEW_S):
            return None
        if now >= expires:
            return None
        return nonce, (STOP_REQUEST_SOURCE, document["requested_at_utc"])
