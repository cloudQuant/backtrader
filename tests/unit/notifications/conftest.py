"""Shared fixtures for iteration 32 notification tests.

Everything here is offline: :class:`FakeTransport` records requests in-process
and :class:`FakeSmtp` captures envelopes, so no test needs network access and no
test monkeypatches a third-party library (NFR32-05).
"""

import json
import threading
import time as _time

import pytest

import backtrader as bt
from backtrader.notifications import core as notify_core
from backtrader.notifications import reset_notifications
from backtrader.notifications.transport import HttpResponse


def json_response(payload, status=200, headers=None):
    """Build an :class:`HttpResponse` carrying a JSON body.

    Args:
        payload: JSON-serialisable body.
        status: HTTP status code.
        headers: Extra response headers.

    Returns:
        HttpResponse: The response object.
    """
    return HttpResponse(
        status=status,
        headers=dict(headers or {}),
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def text_response(body, status=200, headers=None):
    """Build an :class:`HttpResponse` carrying a raw text body.

    Args:
        body: Response body text.
        status: HTTP status code.
        headers: Extra response headers.

    Returns:
        HttpResponse: The response object.
    """
    return HttpResponse(status=status, headers=dict(headers or {}), body=str(body).encode("utf-8"))


class FakeTransport:
    """In-process HTTP transport that records every request.

    The optional ``handler`` receives the request and returns either an
    ``HttpResponse``, an ``Exception`` to raise, or ``None`` to fall back to the
    queued responses / default success body.
    """

    def __init__(self, handler=None, responses=None, default=None):
        """Initialise the transport.

        Args:
            handler: Optional ``callable(request) -> HttpResponse | Exception | None``.
            responses: Queued responses consumed in order.
            default: Response returned when nothing else applies.
        """
        self.requests = []
        self._handler = handler
        self._responses = list(responses or [])
        self._default = (
            default if default is not None else json_response({"errcode": 0, "ok": True})
        )
        self._lock = threading.Lock()

    def send(self, request):
        """Record and answer one request.

        Args:
            request: The outgoing request.

        Returns:
            HttpResponse: The response.

        Raises:
            Exception: Whatever ``handler`` raised or returned.
        """
        with self._lock:
            self.requests.append(request)
        if self._handler is not None:
            result = self._handler(request)
            if isinstance(result, Exception):
                raise result
            if result is not None:
                return result
        with self._lock:
            queued = None
            if self._responses:
                queued = self._responses.pop(0)
        if queued is not None:
            if isinstance(queued, Exception):
                raise queued
            return queued
        return self._default

    def urls(self):
        """Return the URLs of all recorded requests."""
        return [request.url for request in self.requests]

    def bodies(self):
        """Return decoded JSON bodies of the recorded requests."""
        decoded = []
        for request in self.requests:
            try:
                decoded.append(json.loads(request.body.decode("utf-8")))
            except Exception:
                decoded.append(None)
        return decoded


class FakeSmtp:
    """In-process SMTP sender capturing envelopes."""

    def __init__(self, error=None):
        """Initialise the sender.

        Args:
            error: Optional exception raised on every send.
        """
        self.envelopes = []
        self.error = error

    def send(self, envelope):
        """Record the envelope, raising ``error`` when configured.

        Args:
            envelope: The envelope to send.
        """
        if self.error is not None:
            raise self.error
        self.envelopes.append(envelope)


@pytest.fixture(autouse=True)
def _clean_notifications():
    """Reset the notification singleton around every test."""
    reset_notifications()
    yield
    reset_notifications()


@pytest.fixture
def notifier_env():
    """Provide a helper that configures channels against fake transports.

    Returns:
        callable: ``configure(channels, **options) -> (notifier, transport, smtp)``
    """

    def configure(channels, transport=None, smtp=None, **options):
        transport = transport if transport is not None else FakeTransport()
        smtp = smtp if smtp is not None else FakeSmtp()
        notifier = bt.configure_notifications(
            channels, transport=transport, smtp_sender=smtp, **options
        )
        return notifier, transport, smtp

    return configure


@pytest.fixture
def dingtalk_channel():
    """Return a minimal DingTalk channel config."""
    return {"channel": "dingtalk", "access_token": "test-token"}


@pytest.fixture
def telegram_channel():
    """Return a minimal Telegram channel config."""
    return {"channel": "telegram", "bot_token": "test-bot", "chat_id": "42"}


def wait_until(predicate, timeout=5.0, interval=0.01):
    """Poll ``predicate`` until it is true or the timeout expires.

    Args:
        predicate: Callable returning a truthy value when done.
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.

    Returns:
        bool: Whether the predicate became true.
    """
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if predicate():
            return True
        _time.sleep(interval)
    return bool(predicate())


__all__ = [
    "FakeSmtp",
    "FakeTransport",
    "json_response",
    "notify_core",
    "text_response",
    "wait_until",
]
