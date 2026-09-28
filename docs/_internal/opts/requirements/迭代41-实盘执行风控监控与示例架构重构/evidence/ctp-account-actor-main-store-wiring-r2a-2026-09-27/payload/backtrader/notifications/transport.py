"""Injectable HTTP and SMTP transports for notifications (iteration 32, D32-02).

Two seams keep the whole subsystem offline-testable without monkeypatching any
third-party library (NFR32-05):

- :class:`HttpTransport` / :class:`UrllibTransport` for every webhook-style
  channel.
- :class:`SmtpSender` / :class:`SmtplibSender` for the email channel.

Dependency policy (D32-B): the production HTTP implementation goes through
``backtrader.utils.py3.urlopen`` (the standard-library shim that already applies
a 30s default timeout). ``urllib`` is imported in this module only -
``backtrader/utils/py3.py`` is outside this iteration's allowed-modification
list, so the package does not grow that shim's public surface.

Transports never retry, never log and never raise channel-level errors: they
normalise failures into :class:`TransportError` / :class:`SmtpError` so the
channel layer owns classification and the core owns retry policy.
"""

import smtplib
import socket
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Dict, Optional, Tuple
from urllib import error as _urllib_error
from urllib import request as _urllib_request

from ..utils import py3 as _py3

# Failure kinds shared by both seams. The channel layer maps them onto the
# public ERROR_CATEGORIES.
KIND_NETWORK = "network"
KIND_TIMEOUT = "timeout"
KIND_TLS = "tls"


class TransportError(Exception):
    """Normalised HTTP failure.

    Attributes:
        kind: One of ``network``, ``timeout`` or ``tls``.
        url: The URL that failed, already masked by the caller.
        reason: Masked description of the underlying failure (may be empty).
    """

    def __init__(self, kind, url="", reason=None):
        """Store the failure kind, the (masked) URL and the underlying reason.

        Args:
            kind: Failure kind string.
            url: Masked URL for diagnostics.
            reason: Masked description of the original exception. Kept so an
                operator can tell a refused connection from a DNS or TLS
                problem without reproducing it.
        """
        detail = " ({0})".format(reason) if reason else ""
        super().__init__("{0} error for {1}{2}".format(kind, url, detail))
        self.kind = kind
        self.url = url
        self.reason = reason


class SmtpError(Exception):
    """Normalised SMTP failure.

    Attributes:
        kind: One of ``network``, ``timeout`` or ``auth``.
    """

    def __init__(self, kind, detail=""):
        """Store the failure kind and a masked detail string.

        Args:
            kind: Failure kind string.
            detail: Extra diagnostic text, already masked.
        """
        super().__init__("{0} error{1}".format(kind, ": " + detail if detail else ""))
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class HttpRequest:
    """An outgoing HTTP request.

    Attributes:
        method: HTTP verb.
        url: Fully built URL including query string.
        headers: Header name/value pairs.
        body: Request body bytes, or ``None`` for bodyless requests.
        timeout: Per-request timeout in seconds.
    """

    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[bytes] = None
    timeout: float = 10.0


@dataclass(frozen=True)
class HttpResponse:
    """An HTTP response.

    Attributes:
        status: HTTP status code.
        headers: Response headers (lower-cased keys).
        body: Raw response body bytes.
        elapsed_ms: Wall-clock duration of the request in milliseconds.
    """

    status: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    elapsed_ms: float = 0.0

    def text(self):
        """Decode the body as UTF-8, replacing undecodable bytes.

        Returns:
            str: The decoded body.
        """
        return self.body.decode("utf-8", errors="replace")


class UrllibTransport:
    """Production HTTP transport built on ``py3.urlopen``.

    ``HTTPError`` responses (4xx/5xx) are returned as ordinary
    :class:`HttpResponse` objects because gateway-style channels report their
    real status inside the body. Only transport-level failures raise.
    """

    def send(self, request):
        """Perform one HTTP request.

        Args:
            request: The request to send.

        Returns:
            HttpResponse: The response, including HTTP error responses.

        Raises:
            TransportError: On DNS, connection, timeout or TLS failures.
        """
        started = time.monotonic()
        data = request.body
        urllib_request = _urllib_request.Request(
            request.url, data=data, headers=dict(request.headers), method=request.method
        )
        if data is not None and "Content-Type" not in request.headers:
            urllib_request.add_header("Content-Type", "application/json; charset=utf-8")
        try:
            response = _py3.urlopen(urllib_request, timeout=request.timeout)
            try:
                body = response.read() or b""
                headers = {str(k).lower(): str(v) for k, v in (response.headers or {}).items()}
                status = int(getattr(response, "status", 200) or 200)
            finally:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
        except _urllib_error.HTTPError as exc:
            try:
                body = exc.read() or b""
            except Exception:  # nosec B110 - reading an error body is best effort
                body = b""
            headers = {str(k).lower(): str(v) for k, v in (exc.headers or {}).items()}
            return HttpResponse(
                status=int(exc.code or 0),
                headers=headers,
                body=body,
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )
        except _urllib_error.URLError as exc:
            raise TransportError(
                _classify_reason(exc.reason), _mask(request.url), _describe(exc.reason)
            ) from exc
        except socket.timeout as exc:
            raise TransportError(KIND_TIMEOUT, _mask(request.url), _describe(exc)) from exc
        except ssl.SSLError as exc:
            raise TransportError(KIND_TLS, _mask(request.url), _describe(exc)) from exc
        except OSError as exc:
            raise TransportError(KIND_NETWORK, _mask(request.url), _describe(exc)) from exc
        return HttpResponse(
            status=status,
            headers=headers,
            body=body,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )


def _classify_reason(reason):
    """Map a ``URLError.reason`` onto a failure kind.

    Args:
        reason: The wrapped reason object.

    Returns:
        str: ``timeout``, ``tls`` or ``network``.
    """
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return KIND_TIMEOUT
    if isinstance(reason, ssl.SSLError):
        return KIND_TLS
    return KIND_NETWORK


def _mask(url):
    """Mask a URL for diagnostics without importing the whole security module.

    Args:
        url: URL to mask.

    Returns:
        str: Masked URL.
    """
    from .security import mask_url

    return mask_url(url)


@dataclass(frozen=True)
class SmtpEnvelope:
    """A fully resolved email message.

    Attributes:
        host: SMTP host.
        port: SMTP port.
        user: Login user (empty string disables login).
        password: Login password.
        sender: From address.
        recipients: To addresses (never empty).
        subject: Message subject, already carrying the level prefix.
        body: Message body.
        html: Whether ``body`` is HTML.
        use_ssl: Whether to use implicit TLS (port 465 style).
        use_starttls: Whether to issue STARTTLS after connecting.
        timeout: Socket timeout in seconds.
    """

    host: str
    port: int
    user: str
    password: str
    sender: str
    recipients: Tuple[str, ...]
    subject: str
    body: str
    html: bool = False
    use_ssl: bool = False
    use_starttls: bool = False
    timeout: float = 10.0


class SmtplibSender:
    """Production SMTP sender built on the standard library."""

    def send(self, envelope):
        """Deliver one email.

        Args:
            envelope: The resolved message.

        Raises:
            SmtpError: On authentication, timeout or connection failures.
        """
        message = EmailMessage()
        message["From"] = envelope.sender
        message["To"] = ", ".join(envelope.recipients)
        message["Subject"] = envelope.subject
        if envelope.html:
            message.set_content(envelope.body, subtype="html")
        else:
            message.set_content(envelope.body)
        server: Optional[smtplib.SMTP] = None
        try:
            if envelope.use_ssl:
                server = smtplib.SMTP_SSL(envelope.host, envelope.port, timeout=envelope.timeout)
            else:
                server = smtplib.SMTP(envelope.host, envelope.port, timeout=envelope.timeout)
                if envelope.use_starttls:
                    server.starttls()
            if envelope.user:
                server.login(envelope.user, envelope.password)
            server.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise SmtpError("auth", _describe(exc)) from exc
        except (smtplib.SMTPException, OSError, socket.timeout, TimeoutError) as exc:
            kind = KIND_TIMEOUT if isinstance(exc, (socket.timeout, TimeoutError)) else KIND_NETWORK
            raise SmtpError(kind, _describe(exc)) from exc
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:  # nosec B110 - closing a broken session is best effort
                    pass


def _describe(exc):
    """Return a masked one-line description of an exception.

    Args:
        exc: The exception to describe.

    Returns:
        str: Masked ``type: message`` text.
    """
    from .security import mask_text

    return mask_text("{0}: {1}".format(type(exc).__name__, exc))
