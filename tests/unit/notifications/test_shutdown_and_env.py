"""F1 (acceptance review): interpreter-shutdown flush and env-based configuration.

Covers the two gaps found in the review round:

* the ``atexit`` safety net promised by FR32-06/D32-04 - proven with a real child
  process that exits without flushing, plus a direct hook test.
* ``configure_notifications_from_env``, which had no coverage at all: type
  coercion (``port`` int, ``to`` list, boolean flags), missing required
  credentials and an empty channel list.
"""

import multiprocessing

import pytest

import backtrader as bt
from backtrader.notifications import config as notify_config
from backtrader.notifications.transport import HttpResponse

from .conftest import FakeSmtp, FakeTransport, json_response


def _child_exit_without_flush(count_file):
    """Child entry point: queue messages, then exit without flushing.

    Args:
        count_file: File the fake transport appends each delivered message to.
    """
    import urllib.request

    import backtrader as bt

    class _FileTransport:
        """Append one line per delivered message (duplicates stay visible)."""

        def __init__(self, path):
            self.path = path

        def send(self, request):
            import json

            message = json.loads(request.body.decode("utf-8"))["message"]
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(message.splitlines()[-1] + "\n")
            return HttpResponse(200, {}, b'{"errcode": 0}')

    urllib.request._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # A child process is silent by design (FR32-10), so this scenario must
    # opt in explicitly to exercise the shutdown drain in a child process.
    bt.configure_notifications(
        [{"channel": "ntfy", "topic": "exit-check"}],
        transport=_FileTransport(count_file),
        workers="send",
    )
    for index in range(4):
        bt.send_message("queued {0}".format(index))
    # Deliberately no flush_notifications(): the atexit hook must do the work.


def test_process_exit_without_explicit_flush_still_delivers(tmp_path):
    """A script that queues messages and exits must not lose them (F1)."""
    record = str(tmp_path / "delivered.txt")
    open(record, "w", encoding="utf-8").close()
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_child_exit_without_flush, args=(record,))
    process.start()
    process.join(120)
    assert process.exitcode == 0, "child process crashed"
    delivered = [
        line.strip() for line in open(record, encoding="utf-8").read().splitlines() if line.strip()
    ]
    expected = ["queued {0}".format(i) for i in range(4)]
    # Every queued message must arrive; a duplicate is possible only in the tiny
    # window where the worker finished a send but could not clear the in-flight
    # marker before finalization, which is acceptable for a best-effort channel
    # (loss is the failure mode under test here).
    assert sorted(delivered) == sorted(
        expected + [item for item in delivered if item not in expected]
    ), "unexpected payloads: {0}".format(delivered)
    assert set(delivered) == set(expected), "the atexit drain lost messages: {0}".format(delivered)


def test_atexit_hook_is_safe_after_reset():
    """After reset the hook is inert, and calling it twice must not fail."""
    bt.configure_notifications([{"channel": "ntfy", "topic": "t"}], transport=FakeTransport())
    bt.send_message("queued")
    bt.reset_notifications()
    notify_config._atexit_flush()
    notify_config._atexit_flush()
    assert notify_config.get_notifier() is None


def test_atexit_hook_is_inert_without_configuration():
    """Unconfigured: the hook must not raise or touch any transport."""
    assert notify_config.get_notifier() is None
    notify_config._atexit_flush()


def test_atexit_hook_swallows_transport_errors(tmp_path):
    """A failing send at shutdown never turns into an exit-time traceback."""

    def boom(request):
        raise RuntimeError("socket already torn down")

    bt.configure_notifications(
        [{"channel": "ntfy", "topic": "t"}], transport=FakeTransport(handler=boom)
    )
    bt.send_message("will fail at shutdown")
    notify_config._atexit_flush()  # must not raise


def _configure_env(monkeypatch, transport=None, smtp=None, **values):
    """Set ``BT_NOTIFY_*`` variables and configure from the environment.

    Args:
        monkeypatch: pytest fixture used to isolate the environment.
        transport: Optional fake HTTP transport.
        smtp: Optional fake SMTP sender.
        **values: Credential fields keyed ``<channel>_<field>``.

    Returns:
        Notifier: The configured notifier.
    """
    monkeypatch.delenv("BT_NOTIFY_CHANNELS", raising=False)
    for key, value in values.items():
        monkeypatch.setenv("BT_NOTIFY_{0}".format(key.upper()), value)
    options = {}
    if transport is not None:
        options["transport"] = transport
    if smtp is not None:
        options["smtp_sender"] = smtp
    return bt.configure_notifications_from_env(**options)


def test_env_configuration_coerces_types(monkeypatch):
    """``port`` becomes an int and ``to`` becomes a list of addresses."""
    smtp = FakeSmtp()
    notifier = _configure_env(
        monkeypatch,
        smtp=smtp,
        channels="email",
        email_host="smtp.example.com",
        email_port="465",
        email_to="a@example.com, b@example.com",
        email_user="bot@example.com",
        email_password="pw",
        email_ssl="true",
    )
    assert notifier.instance_names() == ("email",)
    result = bt.send_message("from env", title="t", wait=True)
    assert result.outcomes[0].ok is True
    envelope = smtp.envelopes[-1]
    assert envelope.port == 465
    assert envelope.recipients == ("a@example.com", "b@example.com")
    assert envelope.use_ssl is True


def test_env_configuration_supports_several_channels(monkeypatch):
    """A comma separated channel list configures every requested channel."""
    transport = FakeTransport(default=json_response({"errcode": 0}))
    notifier = _configure_env(
        monkeypatch,
        transport=transport,
        channels="dingtalk,ntfy",
        dingtalk_access_token="tok",
        dingtalk_secret="sec",
        ntfy_topic="topic-1",
    )
    assert notifier.instance_names() == ("dingtalk", "ntfy")
    assert bt.send_message("multi", wait=True).accepted is True
    assert len(transport.requests) == 2


def test_env_configuration_reports_missing_credentials(monkeypatch):
    """A channel without its required fields fails at configuration time."""
    monkeypatch.setenv("BT_NOTIFY_CHANNELS", "dingtalk")
    monkeypatch.delenv("BT_NOTIFY_DINGTALK_ACCESS_TOKEN", raising=False)
    with pytest.raises(ValueError):
        bt.configure_notifications_from_env()


def test_env_configuration_requires_a_channel_list(monkeypatch):
    """An empty ``BT_NOTIFY_CHANNELS`` is an error, not a silent no-op."""
    monkeypatch.setenv("BT_NOTIFY_CHANNELS", "")
    with pytest.raises(ValueError):
        bt.configure_notifications_from_env()
