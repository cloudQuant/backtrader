"""Regression coverage for LivePlotAnalyzer's local server lifecycle."""

import socket
import threading
import time
from types import SimpleNamespace

import pandas as pd
import pytest

pytest.importorskip("bokeh")
import backtrader as bt
import backtrader.bokeh.analyzers.plot as plot_module
import backtrader.bokeh.live.datahandler as datahandler_module


class _LocalSocketWebapp:
    """Small Webapp stand-in with a real local socket and Tornado IOLoop."""

    def __init__(
        self,
        stop_failures=0,
        block_before_loop=False,
        startup_failure=False,
        **_kwargs,
    ):
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.stop_failures = stop_failures
        self.stop_attempts = 0
        self.loop = None
        self.socket = None
        self.port = None
        self.stop_thread = None
        self.block_before_loop = block_before_loop
        self.startup_failure = startup_failure
        self.allow_loop_start = threading.Event()
        self.start_failed = threading.Event()

    def start(self, loop=None):
        self.loop = loop
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        self.port = self.socket.getsockname()[1]
        self.started.set()
        if self.startup_failure:
            self.start_failed.set()
            raise RuntimeError("local fixture Webapp.start failed")
        if self.block_before_loop and not self.allow_loop_start.wait(timeout=2.0):
            raise TimeoutError("local fixture loop start barrier timed out")
        loop.start()

    def stop(self):
        self.stop_thread = threading.current_thread()
        self.stop_attempts += 1
        if self.stop_attempts <= self.stop_failures:
            raise RuntimeError("local fixture server stop failed")
        if self.socket is not None:
            self.socket.close()
        self.stopped.set()


class _ClientProbe:
    """Record that the analyzer stopped and released a live client."""

    def __init__(self, stop_failures=0):
        self.stop_failures = stop_failures
        self.stop_attempts = 0
        self.stopped = False

    def next(self):
        pass

    def stop(self):
        self.stop_attempts += 1
        if self.stop_attempts <= self.stop_failures:
            raise RuntimeError("local fixture client stop failed")
        self.stopped = True


class _HandlerApp:
    """Minimal app used by the real LiveDataHandler worker."""

    def get_figurepage(self, _figid):
        return None

    def generate_data(self, **_kwargs):
        return pd.DataFrame({"index": []})


class _HandlerClient:
    """Client shell that delegates stop to an actual LiveDataHandler."""

    def __init__(self, handler):
        self._datahandler = handler
        self.stop_attempts = 0
        self.stopped = False

    def next(self):
        pass

    def stop(self):
        self.stop_attempts += 1
        self._datahandler.stop()
        self.stopped = True


class _BlockingClient:
    """Hold stop after the analyzer has snapshotted its client map."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.stop_attempts = 0

    def next(self):
        pass

    def stop(self):
        self.stop_attempts += 1
        self.entered.set()
        if not self.release.wait(timeout=3.0):
            raise TimeoutError("blocking client release timed out")


class _BlockingFailOnceClient:
    """Block a session-destroy callback, then fail once so it is retained."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.stop_attempts = 0
        self.stopped = False

    def next(self):
        pass

    def stop(self):
        self.stop_attempts += 1
        if self.stop_attempts == 1:
            self.entered.set()
            if not self.release.wait(timeout=3.0):
                raise TimeoutError("session client release timed out")
            raise RuntimeError("session client first stop failed")
        self.stopped = True


@pytest.mark.skipif(
    not plot_module.TORNADO_AVAILABLE, reason="Tornado is required for live plotting"
)
@pytest.mark.parametrize(
    (
        "client_stop_fails",
        "server_stop_fails",
        "stop_during_strategy_start",
        "real_handler_worker",
        "reentrant_stop",
        "startup_failure",
        "server_thread_stop",
    ),
    [
        (False, False, False, False, False, False, False),
        (True, False, False, False, False, False, False),
        (False, True, False, False, False, False, False),
        (True, True, False, False, False, False, False),
        (False, False, True, False, False, False, False),
        (False, False, False, True, False, False, False),
        (False, False, False, False, True, False, False),
        (False, False, False, False, False, True, False),
        (False, False, False, False, False, False, True),
    ],
)
def test_live_plot_analyzer_stop_closes_local_server_loop_thread_and_clients(
    monkeypatch,
    client_stop_fails,
    server_stop_fails,
    stop_during_strategy_start,
    real_handler_worker,
    reentrant_stop,
    startup_failure,
    server_thread_stop,
):
    """Stopping the analyzer closes its local listener and joins the loop thread."""
    webapps = []
    threads = []
    warnings = []
    client = _ClientProbe(stop_failures=int(client_stop_fails))
    real_thread = threading.Thread
    worker_sleep_entered = threading.Event()
    original_sleep = time.sleep

    if real_handler_worker:

        def observed_sleep(seconds):
            worker_sleep_entered.set()
            return original_sleep(seconds)

        # Keep LiveDataHandler and its worker real while observing entry into
        # its actual one-second sleep so the 0.5s join is deterministic.
        monkeypatch.setattr(datahandler_module, "time", SimpleNamespace(sleep=observed_sleep))

    def capture_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        threads.append(thread)
        return thread

    def make_webapp(**kwargs):
        webapp = _LocalSocketWebapp(
            stop_failures=int(server_stop_fails),
            block_before_loop=stop_during_strategy_start,
            startup_failure=startup_failure,
            **kwargs,
        )
        webapps.append(webapp)
        return webapp

    monkeypatch.setattr(
        plot_module,
        "threading",
        SimpleNamespace(
            Thread=capture_thread,
            Event=threading.Event,
            current_thread=threading.current_thread,
        ),
    )
    monkeypatch.setattr(plot_module, "Webapp", make_webapp)
    monkeypatch.setattr(
        plot_module._logger,
        "warning",
        lambda message, *args, **_kwargs: warnings.append(message % args if args else message),
    )

    first_stop_observations = {}
    analyzer_refs = []

    class PlotLifecycleStrategy(bt.Strategy):
        def start(self):
            analyzer = self.analyzers.liveplot
            analyzer_refs.append(analyzer)
            if stop_during_strategy_start:
                # Hold Webapp.start before loop.start until stop has queued its
                # cross-thread callback onto this exact IOLoop.
                webapp = analyzer._webapp
                assert webapp.started.wait(timeout=2.0)
                loop = analyzer._server_loop
                assert loop is not None
                callback_queued = threading.Event()
                original_add_callback = loop.add_callback

                def observed_add_callback(*args, **kwargs):
                    callback_queued.set()
                    return original_add_callback(*args, **kwargs)

                loop.add_callback = observed_add_callback
                result = {}

                def request_stop():
                    try:
                        analyzer.stop()
                    except BaseException as exc:
                        result["error"] = type(exc).__name__

                stopper = real_thread(target=request_stop, daemon=True)
                stopper.start()
                assert callback_queued.wait(timeout=1.0)
                webapp.allow_loop_start.set()
                stopper.join(timeout=2.0)
                first_stop_observations["startup_race_stop_thread_joined"] = not stopper.is_alive()
                first_stop_observations["startup_race_error"] = result.get("error")

        def next(self):
            if startup_failure:
                webapp = self.analyzers.liveplot._webapp
                assert webapp.start_failed.wait(timeout=2.0)
                return
            if stop_during_strategy_start:
                return
            analyzer = self.analyzers.liveplot
            webapp = analyzer._webapp
            assert webapp.started.wait(timeout=2.0)
            with socket.create_connection(("127.0.0.1", webapp.port), timeout=1.0):
                pass
            if server_thread_stop:
                completed = threading.Event()
                result = {}

                def stop_from_server_thread():
                    try:
                        analyzer.stop()
                    except RuntimeError as exc:
                        result["error"] = str(exc)
                    finally:
                        completed.set()

                analyzer._server_loop.add_callback(stop_from_server_thread)
                assert completed.wait(timeout=2.0)
                self.server_thread_stop_error = result.get("error")
                return
            if real_handler_worker:
                handler = datahandler_module.LiveDataHandler(
                    doc=None,
                    app=_HandlerApp(),
                    figid="test",
                    lookback=10,
                    timeout=1.0,
                )
                assert worker_sleep_entered.wait(timeout=1.0)
                self.handler = handler
                self.handler_thread = handler._thread
                self.handler_client = _HandlerClient(handler)
                analyzer._clients["probe"] = self.handler_client
                return
            analyzer._clients["probe"] = client

        def stop(self):
            if reentrant_stop:
                analyzer = self.analyzers.liveplot
                loop = analyzer._server_loop
                assert loop is not None
                close_entered = threading.Event()
                close_release = threading.Event()
                second_stop_started = threading.Event()
                original_close = loop.close
                original_add_callback = loop.add_callback
                callback_count = []

                def blocked_close():
                    close_entered.set()
                    close_release.wait(timeout=2.0)
                    original_close()

                def counted_add_callback(*args, **kwargs):
                    callback_count.append(1)
                    return original_add_callback(*args, **kwargs)

                loop.close = blocked_close
                loop.add_callback = counted_add_callback
                result = {}

                def first_stop():
                    try:
                        analyzer.stop()
                    except BaseException as exc:
                        result["first_error"] = type(exc).__name__

                first = real_thread(target=first_stop, daemon=True)
                first.start()
                assert close_entered.wait(timeout=2.0)
                first_stop_observations["stop_confirmed_during_finalize"] = (
                    analyzer._server_stop_succeeded
                )
                first_stop_observations["loop_retained_during_finalize"] = (
                    analyzer._server_loop is loop
                )
                first_stop_observations["thread_alive_during_finalize"] = (
                    analyzer._server_thread.is_alive()
                )

                def release_after_reentry():
                    if second_stop_started.wait(timeout=2.0):
                        original_sleep(0.05)
                        close_release.set()

                releaser = real_thread(target=release_after_reentry, daemon=True)
                releaser.start()
                second_stop_started.set()
                try:
                    analyzer.stop()
                except BaseException as exc:
                    result["second_error"] = type(exc).__name__
                finally:
                    close_release.set()
                first.join(timeout=2.0)
                releaser.join(timeout=2.0)
                first_stop_observations["reentry_first_joined"] = not first.is_alive()
                first_stop_observations["reentry_callback_count"] = len(callback_count)
                first_stop_observations["reentry_first_error"] = result.get("first_error")
                first_stop_observations["reentry_second_error"] = result.get("second_error")
                return

            if startup_failure:
                analyzer = self.analyzers.liveplot
                analyzer._server_thread.join(timeout=2.0)
                first_stop_observations[
                    "startup_thread_joined"
                ] = not analyzer._server_thread.is_alive()
                try:
                    analyzer.stop()
                except RuntimeError as exc:
                    first_stop_observations["startup_stop_error"] = str(exc)
                return

            if not (client_stop_fails or server_stop_fails or real_handler_worker):
                return

            analyzer = self.analyzers.liveplot
            try:
                analyzer.stop()
            except RuntimeError as exc:
                first_stop_observations["error"] = str(exc)
            else:
                first_stop_observations["error"] = None

            first_stop_observations["client_retained"] = bool(analyzer._clients)
            first_stop_observations["client_stopped"] = client.stopped
            first_stop_observations["webapp_stop_attempts"] = webapps[0].stop_attempts
            first_stop_observations["server_stopped"] = webapps[0].stopped.is_set()
            first_stop_observations["socket_open"] = (
                webapps[0].socket is not None and webapps[0].socket.fileno() != -1
            )
            first_stop_observations["server_loop_retained"] = (
                analyzer._server_loop is webapps[0].loop
            )
            first_stop_observations["server_thread_alive"] = (
                analyzer._server_thread is not None and analyzer._server_thread.is_alive()
            )
            first_stop_observations["server_loop_open"] = (
                webapps[0].loop is not None and not webapps[0].loop.asyncio_loop.is_closed()
            )

            # Each injected failure is transient. Let the framework's normal
            # analyzer stop perform a genuine retry after this strategy hook.
            client.stop_failures = client.stop_attempts
            webapps[0].stop_failures = webapps[0].stop_attempts

            if real_handler_worker:
                first_stop_observations["handler_thread_alive"] = self.handler_thread.is_alive()
                # Wait boundedly for the real worker's sleep to finish; the
                # framework's subsequent analyzer stop then retries cleanup.
                self.handler_thread.join(timeout=2.0)
                first_stop_observations[
                    "handler_thread_exited_before_retry"
                ] = not self.handler_thread.is_alive()

    close = [100.0]
    frame = pd.DataFrame(
        {
            "open": close,
            "high": [101.0],
            "low": [99.0],
            "close": close,
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=pd.date_range("2020-01-01", periods=1, freq="D"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(PlotLifecycleStrategy)
    cerebro.addanalyzer(
        plot_module.LivePlotAnalyzer,
        _name="liveplot",
        port=0,
        autostart=False,
    )

    try:
        if startup_failure:
            with pytest.raises(RuntimeError, match="server startup failed"):
                cerebro.run(runonce=False, preload=False)
            analyzer = analyzer_refs[0]
            webapp = webapps[0]
            assert first_stop_observations["startup_thread_joined"]
            assert first_stop_observations["startup_stop_error"] is not None
            assert (
                "server startup failed (RuntimeError)"
                in first_stop_observations["startup_stop_error"]
            )
            assert "shutdown incomplete" not in first_stop_observations["startup_stop_error"]
            assert analyzer._server_start_error_type == "RuntimeError"
            assert analyzer._server_stop_succeeded
            assert not analyzer._server_thread.is_alive()
            assert webapp.socket.fileno() == -1
            assert webapp.loop.asyncio_loop.is_closed()
            return

        strategy = cerebro.run(runonce=False, preload=False)[0]
        analyzer = strategy.analyzers.liveplot
        webapp = webapps[0]
        thread = threads[0]

        observed = {
            "client_stopped": (
                strategy.handler_client.stopped if real_handler_worker else client.stopped
            ),
            "client_retained_after_failed_stop": analyzer._clients.get("probe")
            is (strategy.handler_client if real_handler_worker else client),
            "server_stopped": webapp.stopped.is_set(),
            "server_stop_attempted_on_loop_thread": webapp.stop_thread is thread,
            "server_stop_attempts": webapp.stop_attempts,
            "server_stop_error_type": analyzer._server_stop_error_type,
            "socket_closed": webapp.socket.fileno() == -1,
            "thread_joined": not thread.is_alive(),
            "loop_closed": webapp.loop.asyncio_loop.is_closed(),
        }
        client_added = not stop_during_strategy_start and not server_thread_stop
        if real_handler_worker:
            assert observed["client_stopped"] is True
            assert strategy.handler_client.stop_attempts == 2
            assert not strategy.handler_thread.is_alive()
            assert observed["client_retained_after_failed_stop"] is False
        else:
            assert observed["client_stopped"] is client_added, observed
            assert observed["client_retained_after_failed_stop"] is False
        assert observed["server_stopped"]
        assert observed["server_stop_error_type"] is None
        assert observed["server_stop_attempted_on_loop_thread"]
        assert observed["server_stop_attempts"] == (2 if server_stop_fails else 1)
        assert observed["socket_closed"], observed
        assert observed["thread_joined"]
        assert observed["loop_closed"]
        if client_stop_fails or server_stop_fails or real_handler_worker:
            assert first_stop_observations["error"] is not None
            assert "shutdown incomplete" in first_stop_observations["error"]
        if client_stop_fails and server_stop_fails:
            assert "client cleanup incomplete" in first_stop_observations["error"]
            assert "server stop failed (RuntimeError)" in first_stop_observations["error"]
        if client_stop_fails:
            assert first_stop_observations["client_retained"]
            assert not first_stop_observations["client_stopped"]
            assert first_stop_observations["server_stopped"] is (not server_stop_fails)
            assert first_stop_observations["webapp_stop_attempts"] == 1
            assert client.stop_attempts == 2
        if server_stop_fails:
            assert not first_stop_observations["server_stopped"]
            assert first_stop_observations["socket_open"]
            assert first_stop_observations["server_loop_retained"]
            assert first_stop_observations["server_thread_alive"]
            assert first_stop_observations["server_loop_open"]
            assert first_stop_observations["webapp_stop_attempts"] == 1
        if real_handler_worker:
            assert strategy.handler_client.stop_attempts == 2
            assert first_stop_observations["client_retained"]
            assert first_stop_observations["handler_thread_alive"]
            assert first_stop_observations["handler_thread_exited_before_retry"]
            assert first_stop_observations["server_stopped"]
        if stop_during_strategy_start:
            assert first_stop_observations["startup_race_stop_thread_joined"]
            assert first_stop_observations["startup_race_error"] is None
        if reentrant_stop:
            assert first_stop_observations["stop_confirmed_during_finalize"]
            assert first_stop_observations["loop_retained_during_finalize"]
            assert first_stop_observations["thread_alive_during_finalize"]
            assert first_stop_observations["reentry_first_joined"]
            assert first_stop_observations["reentry_callback_count"] == 1
            assert first_stop_observations["reentry_first_error"] is None
            assert first_stop_observations["reentry_second_error"] is None
        if server_thread_stop:
            assert "shutdown incomplete" in strategy.server_thread_stop_error
            assert "server thread cannot confirm its own exit" in strategy.server_thread_stop_error
        if client_stop_fails or server_stop_fails or real_handler_worker:
            assert any("stop failed (RuntimeError)" in item for item in warnings)
    finally:
        # A red run must not leave its intentionally leaked local loop/socket
        # behind in the pytest process.
        if webapps and webapps[0].loop is not None:
            webapp = webapps[0]
            loop = webapp.loop
            if not webapp.stopped.is_set() and not loop.asyncio_loop.is_closed():

                def cleanup():
                    try:
                        webapp.stop()
                    finally:
                        loop.stop()

                loop.add_callback(cleanup)
            if threads and threads[0].is_alive():
                threads[0].join(timeout=2.0)
            if not loop.asyncio_loop.is_closed():
                loop.close()
            if webapp.socket is not None and webapp.socket.fileno() != -1:
                webapp.socket.close()


@pytest.mark.skipif(
    not plot_module.TORNADO_AVAILABLE, reason="Tornado is required for live plotting"
)
def test_stop_reports_client_added_by_root_callback_after_client_snapshot(monkeypatch):
    """A client retained by a racing root callback remains visible to stop()."""
    webapps = []
    server_threads = []
    root_clients = []
    first_stop_observation = {}
    initial_client = _BlockingClient()
    real_thread = threading.Thread

    def capture_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        server_threads.append(thread)
        return thread

    def make_webapp(**kwargs):
        webapp = _LocalSocketWebapp(**kwargs)
        webapps.append(webapp)
        return webapp

    def make_live_client(*_args, **_kwargs):
        client = _ClientProbe(stop_failures=1)
        client.model = object()
        root_clients.append(client)
        return client

    monkeypatch.setattr(
        plot_module,
        "threading",
        SimpleNamespace(
            Thread=capture_thread,
            Event=threading.Event,
            current_thread=threading.current_thread,
        ),
    )
    monkeypatch.setattr(plot_module, "Webapp", make_webapp)
    monkeypatch.setattr(plot_module, "LiveClient", make_live_client)

    class CallbackRaceStrategy(bt.Strategy):
        def next(self):
            analyzer = self.analyzers.liveplot
            assert analyzer._webapp.started.wait(timeout=2.0)
            analyzer._clients["initial"] = initial_client

        def stop(self):
            analyzer = self.analyzers.liveplot
            result = {}

            def stop_analyzer():
                try:
                    analyzer.stop()
                except RuntimeError as exc:
                    result["error"] = str(exc)

            stopper = real_thread(target=stop_analyzer, daemon=True)
            stopper.start()
            assert initial_client.entered.wait(timeout=1.0)

            callback_done = threading.Event()
            doc = SimpleNamespace(session_context=SimpleNamespace(id="late-root"))

            def build_root_model():
                try:
                    analyzer._app_cb_build_root_model(doc)
                finally:
                    callback_done.set()

            analyzer._server_loop.add_callback(build_root_model)
            assert callback_done.wait(timeout=1.0)
            first_stop_observation["root_client_retained_before_release"] = (
                analyzer._clients.get("late-root") is root_clients[0]
            )
            initial_client.release.set()
            stopper.join(timeout=2.0)
            first_stop_observation["stopper_joined"] = not stopper.is_alive()
            first_stop_observation["error"] = result.get("error")
            first_stop_observation["root_client_retained_after_stop"] = (
                analyzer._clients.get("late-root") is root_clients[0]
            )
            first_stop_observation["server_closed"] = webapps[0].stopped.is_set()

    frame = pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=pd.date_range("2020-01-01", periods=1, freq="D"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(CallbackRaceStrategy)
    cerebro.addanalyzer(
        plot_module.LivePlotAnalyzer,
        _name="liveplot",
        port=0,
        autostart=False,
    )

    try:
        strategy = cerebro.run(runonce=False, preload=False)[0]
        analyzer = strategy.analyzers.liveplot
        assert first_stop_observation["stopper_joined"]
        assert first_stop_observation["root_client_retained_before_release"]
        assert first_stop_observation["root_client_retained_after_stop"]
        assert "shutdown incomplete" in first_stop_observation["error"]
        assert "client cleanup incomplete (1)" in first_stop_observation["error"]
        assert first_stop_observation["server_closed"]
        assert initial_client.stop_attempts == 1
        assert root_clients[0].stop_attempts == 2
        assert root_clients[0].stopped
        assert not analyzer._clients
        assert webapps[0].stop_attempts == 1
        assert server_threads and not server_threads[0].is_alive()
        assert webapps[0].socket.fileno() == -1
        assert webapps[0].loop.asyncio_loop.is_closed()
    finally:
        if webapps and webapps[0].loop is not None:
            webapps[0].allow_loop_start.set()
            initial_client.release.set()
            if server_threads and server_threads[0].is_alive():
                server_threads[0].join(timeout=2.0)
            if not webapps[0].stopped.is_set():
                webapps[0].stop()
            if not webapps[0].loop.asyncio_loop.is_closed():
                webapps[0].loop.stop()
                webapps[0].loop.close()
            if webapps[0].socket is not None and webapps[0].socket.fileno() != -1:
                webapps[0].socket.close()


@pytest.mark.skipif(
    not plot_module.TORNADO_AVAILABLE, reason="Tornado is required for live plotting"
)
def test_stop_reports_client_reinserted_by_session_destroy_callback(monkeypatch):
    """A failing session-destroy callback is visible after loop shutdown."""
    webapps = []
    server_threads = []
    client = _BlockingFailOnceClient()
    first_stop_observation = {}
    real_thread = threading.Thread

    def capture_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        server_threads.append(thread)
        return thread

    def make_webapp(**kwargs):
        webapp = _LocalSocketWebapp(**kwargs)
        webapps.append(webapp)
        return webapp

    monkeypatch.setattr(
        plot_module,
        "threading",
        SimpleNamespace(
            Thread=capture_thread,
            Event=threading.Event,
            current_thread=threading.current_thread,
        ),
    )
    monkeypatch.setattr(plot_module, "Webapp", make_webapp)

    class SessionRaceStrategy(bt.Strategy):
        def next(self):
            analyzer = self.analyzers.liveplot
            assert analyzer._webapp.started.wait(timeout=2.0)
            analyzer._clients["session"] = client

        def stop(self):
            analyzer = self.analyzers.liveplot
            loop = analyzer._server_loop
            assert loop is not None
            callback_done = threading.Event()

            def destroy_session():
                try:
                    analyzer._on_session_destroyed(SimpleNamespace(id="session"))
                finally:
                    callback_done.set()

            loop.add_callback(destroy_session)
            assert client.entered.wait(timeout=1.0)

            stop_callback_queued = threading.Event()
            original_add_callback = loop.add_callback

            def observe_stop_callback(callback, *args, **kwargs):
                if getattr(callback, "__name__", None) == "_stop_server_on_loop":
                    stop_callback_queued.set()
                return original_add_callback(callback, *args, **kwargs)

            loop.add_callback = observe_stop_callback
            result = {}

            def stop_analyzer():
                try:
                    analyzer.stop()
                except RuntimeError as exc:
                    result["error"] = str(exc)

            stopper = real_thread(target=stop_analyzer, daemon=True)
            stopper.start()
            assert analyzer._server_stop_requested.wait(timeout=1.0)
            assert stop_callback_queued.wait(timeout=1.0)
            client.release.set()
            assert callback_done.wait(timeout=1.0)
            stopper.join(timeout=2.0)

            first_stop_observation["stopper_joined"] = not stopper.is_alive()
            first_stop_observation["error"] = result.get("error")
            first_stop_observation["client_retained_after_stop"] = (
                analyzer._clients.get("session") is client
            )
            first_stop_observation["server_closed"] = webapps[0].stopped.is_set()

    frame = pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=pd.date_range("2020-01-01", periods=1, freq="D"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(SessionRaceStrategy)
    cerebro.addanalyzer(
        plot_module.LivePlotAnalyzer,
        _name="liveplot",
        port=0,
        autostart=False,
    )

    try:
        strategy = cerebro.run(runonce=False, preload=False)[0]
        analyzer = strategy.analyzers.liveplot
        assert first_stop_observation["stopper_joined"]
        assert first_stop_observation["client_retained_after_stop"]
        assert "shutdown incomplete" in first_stop_observation["error"]
        assert "client cleanup incomplete (1)" in first_stop_observation["error"]
        assert first_stop_observation["server_closed"]
        assert client.stop_attempts == 2
        assert client.stopped
        assert not analyzer._clients
        assert webapps[0].stop_attempts == 1
        assert server_threads and not server_threads[0].is_alive()
        assert webapps[0].socket.fileno() == -1
        assert webapps[0].loop.asyncio_loop.is_closed()
    finally:
        client.release.set()
        if webapps and webapps[0].loop is not None:
            if server_threads and server_threads[0].is_alive():
                server_threads[0].join(timeout=2.0)
            if not webapps[0].stopped.is_set():
                webapps[0].stop()
            if not webapps[0].loop.asyncio_loop.is_closed():
                webapps[0].loop.stop()
                webapps[0].loop.close()
            if webapps[0].socket is not None and webapps[0].socket.fileno() != -1:
                webapps[0].socket.close()


@pytest.mark.skipif(
    not plot_module.TORNADO_AVAILABLE, reason="Tornado is required for live plotting"
)
def test_stop_before_loop_creation_cancels_late_server_start(monkeypatch):
    """A stop timeout during thread startup must cancel late listener startup."""
    webapps = []
    server_threads = []
    loop_creation_entered = threading.Event()
    release_loop_creation = threading.Event()
    stop_observations = {}
    real_thread = threading.Thread
    original_new_event_loop = plot_module.asyncio.new_event_loop

    def capture_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        server_threads.append(thread)
        return thread

    def blocked_new_event_loop():
        loop_creation_entered.set()
        if not release_loop_creation.wait(timeout=3.0):
            raise TimeoutError("loop creation barrier timed out")
        return original_new_event_loop()

    def make_webapp(**kwargs):
        webapp = _LocalSocketWebapp(**kwargs)
        webapps.append(webapp)
        return webapp

    monkeypatch.setattr(
        plot_module,
        "threading",
        SimpleNamespace(
            Thread=capture_thread,
            Event=threading.Event,
            current_thread=threading.current_thread,
        ),
    )
    monkeypatch.setattr(plot_module.asyncio, "new_event_loop", blocked_new_event_loop)
    monkeypatch.setattr(plot_module, "Webapp", make_webapp)
    monkeypatch.setattr(plot_module, "_SHUTDOWN_TIMEOUT", 0.05)

    class LateStartStrategy(bt.Strategy):
        def start(self):
            assert loop_creation_entered.wait(timeout=1.0)
            analyzer = self.analyzers.liveplot
            try:
                analyzer.stop()
            except RuntimeError as exc:
                stop_observations["first_error"] = str(exc)
            finally:
                release_loop_creation.set()

        def next(self):
            analyzer = self.analyzers.liveplot
            thread = analyzer._server_thread
            thread.join(timeout=1.0)
            stop_observations["late_thread_alive"] = thread.is_alive()
            stop_observations["webapp_started"] = webapps[0].started.is_set()

        def stop(self):
            try:
                self.analyzers.liveplot.stop()
            except RuntimeError as exc:
                stop_observations["retry_error"] = str(exc)
            else:
                stop_observations["retry_error"] = None

    frame = pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=pd.date_range("2020-01-01", periods=1, freq="D"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(LateStartStrategy)
    cerebro.addanalyzer(
        plot_module.LivePlotAnalyzer,
        _name="liveplot",
        port=0,
        autostart=False,
    )

    try:
        strategy = cerebro.run(runonce=False, preload=False)[0]
        analyzer = strategy.analyzers.liveplot
        webapp = webapps[0]
        assert "shutdown incomplete" in stop_observations["first_error"]
        assert not stop_observations["late_thread_alive"]
        assert not stop_observations["webapp_started"]
        assert stop_observations["retry_error"] is None
        assert analyzer._server_stop_succeeded
        assert analyzer._server_loop is None
        assert webapp.stop_attempts == 1
        assert webapp.stopped.is_set()
        assert webapp.socket is None
    finally:
        release_loop_creation.set()
        if server_threads and server_threads[0].is_alive():
            server_threads[0].join(timeout=2.0)
        if webapps and webapps[0].socket is not None:
            if webapps[0].socket.fileno() != -1:
                webapps[0].socket.close()
        if webapps and webapps[0].loop is not None:
            if not webapps[0].loop.asyncio_loop.is_closed():
                webapps[0].loop.stop()
                webapps[0].loop.close()


@pytest.mark.skipif(
    not plot_module.TORNADO_AVAILABLE, reason="Tornado is required for live plotting"
)
def test_stop_refreshes_shutdown_state_after_loop_readiness_wait(monkeypatch):
    """A late ready wait must re-read shutdown state after thread cleanup."""
    webapps = []
    server_threads = []
    loop_creation_entered = threading.Event()
    release_loop_creation = threading.Event()
    ready_wait_entered = threading.Event()
    release_ready_waiter = threading.Event()
    stop_observations = {}
    real_thread = threading.Thread
    original_new_event_loop = plot_module.asyncio.new_event_loop

    class PausedReadyEvent:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def set(self):
            self._wrapped.set()

        def wait(self, timeout=None):
            ready_wait_entered.set()
            result = self._wrapped.wait(timeout)
            if result:
                # Let the server thread finish cancellation and close its loop
                # before stop() resumes from the readiness wait.
                release_ready_waiter.wait(timeout=2.0)
            return result

    def capture_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        server_threads.append(thread)
        return thread

    def blocked_new_event_loop():
        loop_creation_entered.set()
        if not release_loop_creation.wait(timeout=3.0):
            raise TimeoutError("loop creation barrier timed out")
        return original_new_event_loop()

    def make_webapp(**kwargs):
        webapp = _LocalSocketWebapp(**kwargs)
        webapps.append(webapp)
        return webapp

    monkeypatch.setattr(
        plot_module,
        "threading",
        SimpleNamespace(
            Thread=capture_thread,
            Event=threading.Event,
            current_thread=threading.current_thread,
        ),
    )
    monkeypatch.setattr(plot_module.asyncio, "new_event_loop", blocked_new_event_loop)
    monkeypatch.setattr(plot_module, "Webapp", make_webapp)
    monkeypatch.setattr(plot_module, "_SHUTDOWN_TIMEOUT", 2.0)

    class ReadyRaceStrategy(bt.Strategy):
        def start(self):
            assert loop_creation_entered.wait(timeout=1.0)
            analyzer = self.analyzers.liveplot
            analyzer._server_loop_ready = PausedReadyEvent(analyzer._server_loop_ready)
            result = {}

            def stop_analyzer():
                try:
                    analyzer.stop()
                except RuntimeError as exc:
                    result["error"] = str(exc)

            stopper = real_thread(target=stop_analyzer, daemon=True)
            stopper.start()
            assert ready_wait_entered.wait(timeout=1.0)
            release_loop_creation.set()
            assert analyzer._server_thread.join(timeout=2.0) is None
            stop_observations[
                "thread_exited_before_waiter_release"
            ] = not analyzer._server_thread.is_alive()
            stop_observations["success_before_waiter_release"] = analyzer._server_stop_succeeded
            stop_observations["loop_stop_requested_before_waiter_release"] = (
                analyzer._server_loop_stop_requested
            )
            stop_observations["loop_ref_cleared_before_waiter_release"] = (
                analyzer._server_loop is None
            )
            release_ready_waiter.set()
            stopper.join(timeout=2.0)
            stop_observations["stopper_joined"] = not stopper.is_alive()
            stop_observations["first_error"] = result.get("error")

        def stop(self):
            try:
                self.analyzers.liveplot.stop()
            except RuntimeError as exc:
                stop_observations["retry_error"] = str(exc)
            else:
                stop_observations["retry_error"] = None

    frame = pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=pd.date_range("2020-01-01", periods=1, freq="D"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(ReadyRaceStrategy)
    cerebro.addanalyzer(
        plot_module.LivePlotAnalyzer,
        _name="liveplot",
        port=0,
        autostart=False,
    )

    try:
        strategy = cerebro.run(runonce=False, preload=False)[0]
        analyzer = strategy.analyzers.liveplot
        webapp = webapps[0]
        assert stop_observations["thread_exited_before_waiter_release"]
        assert stop_observations["success_before_waiter_release"]
        assert stop_observations["loop_stop_requested_before_waiter_release"]
        assert stop_observations["loop_ref_cleared_before_waiter_release"]
        assert stop_observations["stopper_joined"]
        assert stop_observations["first_error"] is None
        assert stop_observations["retry_error"] is None
        assert not webapp.started.is_set()
        assert webapp.stop_attempts == 1
        assert analyzer._server_stop_succeeded
        assert analyzer._server_loop_stop_requested
        assert analyzer._server_loop is None
    finally:
        release_loop_creation.set()
        release_ready_waiter.set()
        if server_threads and server_threads[0].is_alive():
            server_threads[0].join(timeout=2.0)
        if webapps and webapps[0].socket is not None:
            if webapps[0].socket.fileno() != -1:
                webapps[0].socket.close()
        if webapps and webapps[0].loop is not None:
            if not webapps[0].loop.asyncio_loop.is_closed():
                webapps[0].loop.stop()
                webapps[0].loop.close()
