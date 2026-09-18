"""AC32-16: child processes are silent unless explicitly opted in.

A real ``spawn`` child is used because that is the stricter case: it starts with
no inherited configuration at all, exactly like an optimization worker.
"""

import multiprocessing
import queue as queue_module

from backtrader.notifications.config import _in_child_process
from backtrader.notifications.transport import HttpResponse


class _RecordingTransport:
    """Child-side transport that counts requests instead of sending them."""

    def __init__(self):
        """Prepare the call counter."""
        self.calls = 0

    def send(self, request):
        """Count one request and answer with a success body."""
        self.calls += 1
        return HttpResponse(200, {}, b'{"errcode": 0}')


def _child_run(mode, out):
    """Child entry point: configure, send, report.

    Args:
        mode: ``default``, ``silent`` or ``send``.
        out: Multiprocessing queue receiving the report.
    """
    import backtrader as bt

    transport = _RecordingTransport()
    options = {"transport": transport}
    if mode == "send":
        options["workers"] = "send"
    elif mode == "silent":
        options["workers"] = "silent"
    bt.configure_notifications([{"channel": "ntfy", "topic": "child"}], **options)
    result = bt.send_message("from the child", wait=True)
    out.put(
        {
            "reason": result.reason,
            "calls": transport.calls,
            "categories": [outcome.error_category for outcome in result.outcomes],
        }
    )


def _run_child(mode, timeout=90.0):
    """Run one child-process scenario and return its report.

    Args:
        mode: ``default``, ``silent`` or ``send``.
        timeout: Seconds to wait for the child.

    Returns:
        dict: The child's report.

    Raises:
        AssertionError: If the child dies or reports nothing.
    """
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    process = context.Process(target=_child_run, args=(mode, results))
    process.start()
    process.join(timeout)
    assert not process.is_alive(), "child process did not finish"
    assert process.exitcode == 0, "child process failed with exit code {0}".format(process.exitcode)
    try:
        return results.get(timeout=5.0)
    except queue_module.Empty as exc:  # pragma: no cover - defensive
        raise AssertionError("child produced no report") from exc


def test_child_process_is_silent_by_default():
    """The default child never sends, so a parameter sweep cannot become a storm."""
    report = _run_child("default")
    assert report["reason"] == "worker_silent"
    assert report["calls"] == 0
    assert report["categories"] == ["worker_silent"]


def test_child_process_silent_mode_is_explicitly_supported():
    """``workers="silent"`` behaves the same way in a child."""
    report = _run_child("silent")
    assert report["reason"] == "worker_silent"
    assert report["calls"] == 0


def test_child_process_can_send_when_explicitly_opted_in():
    """``workers="send"`` lets a child that configured itself deliver."""
    report = _run_child("send")
    assert report["reason"] == "ok"
    assert report["calls"] == 1
    assert report["categories"] == [None]


def test_main_process_is_never_treated_as_a_child():
    """The guard is specific to child processes."""
    assert _in_child_process() is False
