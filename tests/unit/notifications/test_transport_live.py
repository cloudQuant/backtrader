"""AC32-02: the production transport against a real socket on localhost.

The other transport tests stub ``py3.urlopen``. This module runs the real
``UrllibTransport`` against a loopback HTTP server, which proves the parts a stub
cannot: header/body encoding on the wire, status handling and failure
classification over an actual connection. No external network is used.
"""

import http.server
import json
import socket
import threading

import pytest

import backtrader as bt


def _probe(server):
    """Return a diagnostic string describing whether the loopback port accepts.

    Used in assertion messages: it separates "our server is unreachable" from
    "the urllib path misbehaved", which is what tells a genuine transport bug
    apart from a polluted test process.

    Args:
        server: The loopback server.

    Returns:
        str: Diagnostic text.
    """
    import http.client
    import urllib.request

    try:
        with socket.create_connection(server.server_address, timeout=2.0):
            socket_state = "raw connect ok"
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        socket_state = "raw connect failed: {0}: {1}".format(type(exc).__name__, exc)
    try:
        status = urllib.request.urlopen(
            "http://127.0.0.1:{0}/probe".format(server.server_address[1]), timeout=2.0
        ).status
        urllib_state = "urllib ok ({0})".format(status)
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        urllib_state = "urllib failed: {0}: {1}".format(type(exc).__name__, exc)
    opener = urllib.request._opener
    proxies = []
    for handler in getattr(opener, "handlers", []):
        if isinstance(handler, urllib.request.ProxyHandler):
            proxies.append(handler.proxies)
    env_proxies = {
        key: value for key, value in __import__("os").environ.items() if "proxy" in key.lower()
    }
    return "{0}; {1}; connect={2}; proxies={3}; env={4}; handlers={5}".format(
        socket_state,
        urllib_state,
        getattr(http.client.HTTPConnection.connect, "__qualname__", "?"),
        proxies,
        env_proxies,
        [type(handler).__name__ for handler in getattr(opener, "handlers", [])],
    )


class _EchoHandler(http.server.BaseHTTPRequestHandler):
    """Records requests and answers with the status the server was given."""

    protocol_version = "HTTP/1.1"
    # Read the announced length so keep-alive framing stays correct.
    _ = None

    def do_POST(self):  # noqa: N802 - http.server naming
        """Record the request and reply with the configured status."""
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.server.received.append(
            {"path": self.path, "headers": dict(self.headers), "body": body}
        )
        payload = json.dumps({"errcode": 0}).encode("utf-8")
        self.send_response(self.server.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        """Silence the default stderr logging."""
        return


@pytest.fixture
def loopback_server():
    """Provide a local HTTP server recording requests.

    A threading server is used deliberately: the transport retries a failed send
    immediately, and a single-threaded ``HTTPServer`` blocks in keep-alive
    ``handle_one_request`` after the first response, which fills its accept queue
    and makes BSD/Darwin answer retries with ECONNREFUSED - a test artefact, not
    a transport bug.

    Yields:
        http.server.ThreadingHTTPServer: The running server with ``received``
        and ``response_status`` attributes.
    """
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    server.received = []
    server.response_status = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5.0)


@pytest.fixture
def isolated_opener(monkeypatch):
    """Pin an explicitly proxy-free urllib opener for the loopback tests.

    Two pieces of shared process state can otherwise make a loopback request fail
    with ``ECONNREFUSED`` and look like a transport bug:

    * ``urllib.request`` caches its opener process-wide (``_opener``), so another
      test's installed opener survives into this one.
    * ``examples/013_1|013_2/ctp_example_support.py`` call ``load_dotenv`` at
      import time, which injects the developer's ``.env`` (including
      ``HTTP_PROXY``/``SOCKS_PROXY`` pointing at a local proxy) into
      ``os.environ`` for the rest of the worker.

    ``ProxyHandler({})`` states "no proxies" explicitly and therefore keeps the
    test's meaning - "the production transport works over a real socket" -
    independent of both. The production transport itself still honours proxies,
    which is the right behaviour for real deployments.

    Args:
        monkeypatch: pytest fixture used to restore the previous opener.
    """
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    monkeypatch.setattr(urllib.request, "_opener", opener)


def _url(server, path="/hook"):
    """Return the loopback URL for a path."""
    return "http://127.0.0.1:{0}{1}".format(server.server_address[1], path)


def test_real_http_delivery_over_loopback(loopback_server, isolated_opener):
    """A webhook message reaches a real socket with its JSON body intact."""
    bt.configure_notifications(
        [
            {
                "channel": "webhook",
                "url": _url(loopback_server),
                "body_json": {"level": "{level}", "text": "{text}"},
            }
        ]
    )
    result = bt.send_message("localhost delivery", level="warning", wait=True)

    assert result.outcomes[0].ok is True, "{0} | {1}".format(
        result.outcomes[0].error, _probe(loopback_server)
    )
    assert len(loopback_server.received) == 1
    recorded = loopback_server.received[0]
    assert recorded["path"] == "/hook"
    assert recorded["headers"]["Content-Type"].startswith("application/json")
    payload = json.loads(recorded["body"].decode("utf-8"))
    assert payload["level"] == "warning"
    assert "localhost delivery" in payload["text"]
    assert "[WARNING]" in payload["text"]


def test_real_http_server_error_is_classified(loopback_server, isolated_opener):
    """A 5xx response is retried (per policy) and classified as ``server``."""
    loopback_server.response_status = 503
    bt.configure_notifications(
        [{"channel": "webhook", "url": _url(loopback_server)}],
        retry_backoff=0.0,
        max_retries=1,
    )
    outcome = bt.send_message("will fail", wait=True).outcomes[0]

    assert outcome.ok is False, _probe(loopback_server)
    assert outcome.error_category == "server"
    assert outcome.attempts == 2
    assert len(loopback_server.received) == 2


def test_real_http_rejects_unknown_channel_without_network(loopback_server):
    """Configuration errors surface before any socket is touched."""
    with pytest.raises(ValueError):
        bt.configure_notifications([{"channel": "webhook"}])
    assert loopback_server.received == []
