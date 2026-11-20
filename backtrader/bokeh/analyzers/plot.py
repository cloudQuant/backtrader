#!/usr/bin/env python
"""
Live plotting analyzer.

Provides real-time plotting functionality based on Bokeh Server.
"""

import asyncio
import threading
from threading import Lock

from backtrader.utils.log_message import get_logger

try:
    import tornado.ioloop

    TORNADO_AVAILABLE = True
except ImportError:
    TORNADO_AVAILABLE = False

import backtrader as bt

from ..app import BacktraderBokeh
from ..live.client import LiveClient
from ..schemes import Tradimo
from ..webapp import Webapp

_logger = get_logger(__name__)
_SHUTDOWN_TIMEOUT = 5.0


class LivePlotAnalyzer(bt.Analyzer):
    """Live plotting analyzer.

    Provides real-time plotting functionality based on Bokeh Server, including:
    - WebSocket real-time data push
    - Pause/resume functionality
    - Forward/backward navigation
    - Data lookback control

    Args:
        scheme: Theme instance, defaults to Tradimo
        style: Chart style, 'bar' or 'candle'
        lookback: Amount of historical data to retain
        address: Server address
        port: Server port
        title: Title
        autostart: Whether to auto-start the server

    Example:
        cerebro.addanalyzer(LivePlotAnalyzer,
                          scheme=Blackly(),
                          lookback=100,
                          port=8999)
    """

    params = (
        ("scheme", None),  # Theme
        ("style", "bar"),  # Chart style
        ("lookback", 100),  # Historical data retention
        ("address", "localhost"),  # Server address
        ("port", 8999),  # Server port
        ("title", None),  # Title
        ("autostart", True),  # Auto-start
    )

    def __init__(self, **kwargs):
        """Initialize live plot analyzer.

        Args:
            **kwargs: Keyword arguments overriding default parameters:
                - scheme: Theme instance (defaults to Tradimo)
                - style: Chart style ('bar' or 'candle')
                - lookback: Number of bars to retain in display
                - address: Server address (default: 'localhost')
                - port: Server port (default: 8999)
                - title: Chart title (default: 'Live {StrategyName}')
                - autostart: Whether to auto-start server (default: True)
        """
        super().__init__()

        # Set title
        title = self.p.title
        if title is None:
            title = f"Live {type(self.strategy).__name__}"

        # Set auto-start
        autostart = kwargs.get("autostart", self.p.autostart)

        # Get theme
        scheme = self.p.scheme
        if scheme is None:
            scheme = Tradimo()

        # Create Webapp
        self._webapp = Webapp(
            title=title,
            template="basic.html.j2",
            scheme=scheme,
            on_root_model=self._app_cb_build_root_model,
            on_session_destroyed=self._on_session_destroyed,
            autostart=autostart,
            address=self.p.address,
            port=self.p.port,
        )

        self._lock = Lock()
        self._server_start_lock = Lock()
        self._clients = {}
        self._app_kwargs = kwargs
        self._server_thread = None
        self._server_loop = None
        self._server_loop_ready = threading.Event()
        self._server_stop_event = threading.Event()
        self._server_stop_requested = threading.Event()
        self._server_stop_attempted = False
        self._server_stop_succeeded = False
        self._server_stop_error_type = None
        self._server_loop_stop_requested = False
        self._server_loop_stop_error_type = None
        self._server_loop_close_error_type = None
        self._server_start_error_type = None

    def _create_app(self):
        """Create BacktraderBokeh application instance.

        Returns:
            BacktraderBokeh instance
        """
        return BacktraderBokeh(
            style=self.p.style, scheme=self.p.scheme or Tradimo(), **self._app_kwargs
        )

    def _on_session_destroyed(self, session_context):
        """Session destroyed callback.

        Args:
            session_context: Bokeh session context
        """
        with self._lock:
            session_id = session_context.id
            client = self._clients.pop(session_id, None)

        if client is not None:
            self._stop_client(session_id, client)

    def _t_server(self):
        """Server thread method."""
        if not TORNADO_AVAILABLE:
            with self._lock:
                self._server_start_error_type = "TornadoUnavailable"
            self._server_loop_ready.set()
            _logger.error("Tornado is not available. Cannot start Bokeh server.")
            return

        asyncio_loop = None
        loop = None
        try:
            asyncio_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(asyncio_loop)
            loop = tornado.ioloop.IOLoop.current()
            with self._server_start_lock:
                with self._lock:
                    self._server_loop = loop
                self._server_loop_ready.set()
                start_requested = not self._server_stop_requested.is_set()

            if start_requested:
                self._webapp.start(loop)
            else:
                # Stop won the startup barrier. Do not bind a listener after
                # the caller has already requested shutdown.
                self._stop_server_on_loop(loop)
        except BaseException as exc:
            with self._lock:
                self._server_start_error_type = type(exc).__name__
            self._server_loop_ready.set()
            _logger.warning(
                "LivePlotAnalyzer server thread failed (%s)",
                type(exc).__name__,
                exc_info=True,
            )
        finally:
            if loop is not None:
                # If start() returns unexpectedly, make one stop attempt on the
                # loop thread. A failed stop must leave the loop alive so a
                # later analyzer.stop() can retry it.
                stopped = self._stop_server_on_loop(loop)
                if not stopped:
                    try:
                        loop.start()
                    except BaseException as exc:
                        self._server_loop_stop_error_type = type(exc).__name__
                        _logger.warning(
                            "LivePlotAnalyzer IOLoop restart failed (%s)",
                            type(exc).__name__,
                            exc_info=True,
                        )

                if self._server_stop_succeeded:
                    close_succeeded = True
                    try:
                        loop.close()
                    except BaseException as exc:
                        close_succeeded = False
                        self._server_loop_close_error_type = type(exc).__name__
                        _logger.warning(
                            "LivePlotAnalyzer IOLoop close failed (%s)",
                            type(exc).__name__,
                            exc_info=True,
                        )

                    if close_succeeded and asyncio_loop is not None:
                        try:
                            if not asyncio_loop.is_closed():
                                asyncio_loop.close()
                        except BaseException as exc:
                            close_succeeded = False
                            self._server_loop_close_error_type = type(exc).__name__
                            _logger.warning(
                                "LivePlotAnalyzer asyncio loop close failed (%s)",
                                type(exc).__name__,
                                exc_info=True,
                            )

                    if close_succeeded:
                        with self._lock:
                            if self._server_loop is loop:
                                self._server_loop = None
                else:
                    _logger.warning("LivePlotAnalyzer server shutdown remains incomplete")

            if asyncio_loop is not None and (
                loop is None
                or (self._server_stop_succeeded and self._server_loop_close_error_type is None)
            ):
                try:
                    if not asyncio_loop.is_closed():
                        asyncio_loop.close()
                except BaseException as exc:
                    _logger.warning(
                        "LivePlotAnalyzer asyncio loop close failed (%s)",
                        type(exc).__name__,
                        exc_info=True,
                    )
                try:
                    asyncio.set_event_loop(None)
                except BaseException as exc:
                    _logger.warning(
                        "LivePlotAnalyzer event loop reset failed (%s)",
                        type(exc).__name__,
                        exc_info=True,
                    )

    def _app_cb_build_root_model(self, doc):
        """Build root model callback.

        Args:
            doc: Bokeh document

        Returns:
            Root model
        """
        client = LiveClient(doc, self._create_app(), self.strategy, self.p.lookback)
        session_id = doc.session_context.id

        with self._lock:
            stopping = self._server_stop_requested.is_set()
            if not stopping:
                self._clients[session_id] = client

        if stopping:
            self._stop_client(session_id, client)

        return client.model

    def _stop_client(self, session_id, client):
        """Stop a client without preventing server shutdown on failure."""
        try:
            client.stop()
            return True
        except BaseException as exc:
            # Keep the failed client reachable so shutdown is not represented
            # as complete when its worker may still be alive.
            with self._lock:
                self._clients.setdefault(session_id, client)
            _logger.warning("LivePlotAnalyzer client stop failed (%s)", type(exc).__name__)
            return False

    def _stop_server_on_loop(self, loop):
        """Stop Bokeh resources on their IOLoop thread, then stop the loop."""
        with self._lock:
            stop_succeeded = self._server_stop_succeeded

        if not stop_succeeded:
            with self._lock:
                self._server_stop_attempted = True
            try:
                self._webapp.stop()
            except BaseException as exc:
                with self._lock:
                    self._server_stop_error_type = type(exc).__name__
                self._server_stop_event.set()
                _logger.warning(
                    "LivePlotAnalyzer server stop failed (%s)",
                    type(exc).__name__,
                    exc_info=True,
                )
                return False

            with self._lock:
                self._server_stop_succeeded = True
                self._server_stop_error_type = None

        try:
            loop.stop()
            with self._lock:
                self._server_loop_stop_requested = True
                self._server_loop_stop_error_type = None
        except BaseException as exc:
            with self._lock:
                self._server_loop_stop_requested = False
                self._server_loop_stop_error_type = type(exc).__name__
            _logger.warning(
                "LivePlotAnalyzer IOLoop stop failed (%s)",
                type(exc).__name__,
                exc_info=True,
            )
            self._server_stop_event.set()
            return False
        self._server_stop_event.set()
        return True

    def start(self):
        """Start from backtrader.

        Starts the Bokeh Server.
        """
        _logger.debug("Starting LivePlotAnalyzer...")
        with self._lock:
            if self._server_stop_requested.is_set():
                _logger.warning("LivePlotAnalyzer cannot restart after stop")
                return
            if self._server_stop_attempted:
                _logger.warning("LivePlotAnalyzer cannot restart after IOLoop exit")
                return
            if self._server_thread is not None and self._server_thread.is_alive():
                return

            thread = threading.Thread(
                target=self._t_server,
                name="backtrader-bokeh-server",
                daemon=True,
            )
            self._server_thread = thread
            try:
                thread.start()
            except BaseException:
                self._server_thread = None
                raise

    def stop(self):
        """Stop from backtrader."""
        _logger.debug("Stopping LivePlotAnalyzer...")

        with self._server_start_lock:
            self._server_stop_requested.set()
        with self._lock:
            clients = list(self._clients.items())
            self._clients.clear()
            thread = self._server_thread

        for session_id, client in clients:
            self._stop_client(session_id, client)

        server_issue = None
        with self._lock:
            loop = self._server_loop
            stop_succeeded = self._server_stop_succeeded

        if thread is not None and not stop_succeeded and loop is None:
            self._server_loop_ready.wait(timeout=_SHUTDOWN_TIMEOUT)

        current_thread = threading.current_thread()
        with self._lock:
            # The readiness wait may outlive startup cancellation: the server
            # thread can stop and clear its loop before this caller resumes.
            # Refresh all three values together so decisions use one state.
            loop = self._server_loop
            stop_succeeded = self._server_stop_succeeded
            loop_stop_requested = self._server_loop_stop_requested

        if loop is not None and thread is current_thread:
            # A call from the server loop cannot use add_callback (it would be
            # queued behind this call) or join itself. Perform the owner-thread
            # cleanup directly, then report that thread exit is not yet proven.
            self._server_stop_event.clear()
            if not stop_succeeded or not loop_stop_requested:
                self._stop_server_on_loop(loop)
            with self._lock:
                stop_succeeded = self._server_stop_succeeded
                stop_error = self._server_stop_error_type
            if not stop_succeeded:
                server_issue = "server stop failed ({})".format(stop_error or "unknown error")
            else:
                server_issue = "server thread cannot confirm its own exit"
        elif loop is not None and (not stop_succeeded or not loop_stop_requested):
            self._server_stop_event.clear()
            try:
                # IOLoop.add_callback is Tornado's cross-thread-safe handoff.
                loop.add_callback(self._stop_server_on_loop, loop)
            except BaseException as exc:
                server_issue = "shutdown request failed ({})".format(type(exc).__name__)
            else:
                if not self._server_stop_event.wait(timeout=_SHUTDOWN_TIMEOUT):
                    server_issue = "server stop did not complete before timeout"
                else:
                    with self._lock:
                        stop_succeeded = self._server_stop_succeeded
                        stop_error = self._server_stop_error_type
                        loop_stop_error = self._server_loop_stop_error_type
                    if not stop_succeeded:
                        server_issue = "server stop failed ({})".format(
                            stop_error or "unknown error"
                        )
                    elif loop_stop_error is not None:
                        server_issue = "IOLoop stop failed ({})".format(loop_stop_error)
        elif thread is not None and not stop_succeeded:
            with self._lock:
                start_error = self._server_start_error_type
            if start_error is None:
                server_issue = "server loop unavailable before stop confirmation"

        thread_alive = False
        if thread is not None and stop_succeeded:
            if thread is not current_thread:
                thread.join(timeout=_SHUTDOWN_TIMEOUT)
                thread_alive = thread.is_alive()
                if thread_alive:
                    server_issue = "server thread did not stop before timeout"
            else:
                server_issue = "server thread cannot confirm its own exit"
        elif thread is not None and server_issue is None:
            # No IOLoop was created before asynchronous startup failed. There is
            # no server to stop, but wait boundedly for the startup thread itself.
            if thread is not current_thread:
                thread.join(timeout=_SHUTDOWN_TIMEOUT)
            if thread.is_alive():
                server_issue = "server startup thread did not stop before timeout"

        if self._server_loop_close_error_type is not None:
            server_issue = "event loop close failed ({})".format(self._server_loop_close_error_type)

        with self._lock:
            start_error = self._server_start_error_type
            # Session/root callbacks run on the loop until its thread exits.
            # Recheck only after the bounded join so clients reinserted by a
            # racing callback cannot be mistaken for a completed shutdown.
            retained_client_count = len(self._clients)

        incomplete = []
        if retained_client_count:
            incomplete.append("client cleanup incomplete ({})".format(retained_client_count))
        if server_issue is not None:
            incomplete.append(server_issue)
        if start_error is not None:
            startup_issue = "server startup failed ({})".format(start_error)
            if incomplete:
                raise RuntimeError(
                    "LivePlotAnalyzer "
                    + startup_issue
                    + "; shutdown incomplete: "
                    + "; ".join(incomplete)
                )
            raise RuntimeError("LivePlotAnalyzer " + startup_issue)
        if incomplete:
            raise RuntimeError("LivePlotAnalyzer shutdown incomplete: " + "; ".join(incomplete))

    def next(self):
        """Receive new data from backtrader.

        Updates all connected clients.
        """
        with self._lock:
            for client in self._clients.values():
                client.next()

    def get_analysis(self):
        """Return analysis results.

        Returns:
            dict: Empty dict (this analyzer is for plotting, does not produce analysis data)
        """
        return {}
