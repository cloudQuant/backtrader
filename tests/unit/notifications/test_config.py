"""AC32-03 / AC32-04: configuration transaction, silence and reset semantics."""

import threading

import pytest

import backtrader as bt
from backtrader.notifications import get_notifier

from .conftest import FakeTransport, json_response, wait_until


def _worker_threads():
    return [t for t in threading.enumerate() if t.name.startswith("bt-notify-")]


def test_configure_builds_instances_and_names_duplicates(notifier_env):
    """Single channels keep their id; duplicates are numbered by order."""
    _, transport, _ = notifier_env(
        [
            {"channel": "dingtalk", "access_token": "a"},
            {"channel": "ntfy", "topic": "t"},
            {"channel": "ntfy", "topic": "t2"},
        ]
    )
    assert get_notifier().instance_names() == ("dingtalk", "ntfy#1", "ntfy#2")


def test_send_delivers_to_every_instance(notifier_env):
    """Two instances of one channel receive the message independently."""
    _, transport, _ = notifier_env(
        [
            {"channel": "ntfy", "topic": "one"},
            {"channel": "ntfy", "topic": "two"},
        ]
    )
    result = bt.send_message("hello", wait=True)
    assert result.accepted is True
    assert {outcome.channel for outcome in result.outcomes} == {"ntfy#1", "ntfy#2"}
    assert len(transport.requests) == 2
    topics = {body["topic"] for body in transport.bodies()}
    assert topics == {"one", "two"}


def test_invalid_reconfigure_keeps_previous_configuration_usable(notifier_env):
    """A rejected reconfigure must not damage the working configuration."""
    _, transport, _ = notifier_env([{"channel": "ntfy", "topic": "keep"}])
    before = get_notifier()

    bad_configs = [
        [{"channel": "nope"}],
        [{"channel": "dingtalk"}],
        [{"channel": "email", "host": "h", "port": 465, "to": []}],
        [{"channel": "ntfy", "topic": "x"}],
    ]
    for channels in bad_configs[:-1]:
        with pytest.raises(ValueError):
            bt.configure_notifications(channels, transport=FakeTransport())
    with pytest.raises(ValueError):
        bt.configure_notifications([{"channel": "ntfy", "topic": "x"}], queue_size=0)
    with pytest.raises(ValueError):
        bt.configure_notifications([{"channel": "ntfy", "topic": "x"}], dedup_cooldown=-1)
    with pytest.raises(ValueError):
        bt.configure_notifications([{"channel": "ntfy", "topic": "x"}], workers="all")
    with pytest.raises(ValueError):
        bt.configure_notifications([{"channel": "ntfy", "topic": "x"}], unknown_option=1)

    assert get_notifier() is before, "old notifier must survive a failed reconfigure"
    result = bt.send_message("still works", wait=True)
    assert result.accepted is True
    assert transport.requests[-1].url.endswith("/")


def test_reconfigure_is_idempotent_and_leaves_no_threads(notifier_env):
    """Repeated configuration replaces workers without leaking threads."""
    notifier_env([{"channel": "ntfy", "topic": "a"}])
    for _ in range(3):
        notifier_env([{"channel": "ntfy", "topic": "a"}])
    assert wait_until(
        lambda: len(_worker_threads()) == 1
    ), "expected exactly one live worker after reconfigure, saw {0}".format(_worker_threads())


def test_empty_channel_list_is_valid_and_reports_no_channels(notifier_env):
    """``channels=[]`` is a legitimate configuration, not an error."""
    notifier, transport, _ = notifier_env([])
    assert notifier.instance_names() == ()
    result = bt.send_message("nobody listens")
    assert result.accepted is False
    assert result.reason == "no_channels"
    assert transport.requests == []


def test_requesting_valid_but_unconfigured_channel_is_reported(notifier_env):
    """A valid channel id that is not configured yields ``not_configured``."""
    notifier_env([{"channel": "ntfy", "topic": "a"}])
    result = bt.send_message("partial", channels=["ntfy", "telegram"], wait=True)
    categories = {outcome.channel: outcome.error_category for outcome in result.outcomes}
    assert categories["ntfy"] is None
    assert categories["telegram"] == "not_configured"
    assert result.accepted is True


def test_unknown_channel_id_raises_value_error(notifier_env):
    """Unknown ids are programming errors and surface immediately."""
    notifier_env([{"channel": "ntfy", "topic": "a"}])
    with pytest.raises(ValueError):
        bt.send_message("x", channels=["not-a-channel"])
    with pytest.raises(ValueError):
        bt.configure_notifications([{"channel": "not-a-channel"}])


def test_default_silence_has_no_side_effects(notifier_env):
    """Without configuration there is no network, thread, file or directory."""
    import os
    import tempfile

    before = set(_worker_threads())
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        try:
            os.chdir(tmp)
            result = bt.send_message("into the void")
            assert bt.flush_notifications() is True
            bt.reset_notifications()
            assert os.listdir(tmp) == []
        finally:
            os.chdir(cwd)
    assert result.accepted is False
    assert result.reason == "not_configured"
    assert set(_worker_threads()) == before


def test_not_configured_warns_once_on_stderr(capsys):
    """The "not configured" hint is emitted once, not on every call."""
    bt.send_message("first")
    bt.send_message("second")
    captured = capsys.readouterr()
    assert captured.err.count("not configured") == 1


def test_flush_is_immediately_true_when_unconfigured():
    """Flushing without a configuration returns immediately."""
    assert bt.flush_notifications() is True


def test_reset_after_flush_timeout_discards_and_clears_stats(notifier_env):
    """``reset`` after a timed-out flush discards without deadlocking."""
    gate = threading.Event()

    def blocking(request):
        gate.wait(2.0)
        return json_response({"errcode": 0})

    notifier_env([{"channel": "ntfy", "topic": "a"}], transport=FakeTransport(handler=blocking))
    for index in range(5):
        bt.send_message("message {0}".format(index))
    assert bt.flush_notifications(timeout=0.05) is False
    assert bt.notification_stats()["ntfy"] is not None
    bt.reset_notifications()
    gate.set()
    assert bt.notification_stats() == {}


def test_channel_requires_is_a_public_capability_query():
    """Tools can discover required credentials without private helpers (F7)."""
    from backtrader.notifications import channel_requires

    assert channel_requires("dingtalk") == ("access_token",)
    assert channel_requires("email") == ("host", "port", "to")
    assert channel_requires("webhook") == ("url",)
    with pytest.raises(ValueError):
        channel_requires("not-a-channel")


def test_notify_smoke_script_does_not_use_private_helpers():
    """The documented smoke tool must not import private module symbols (F7)."""
    import io as _io
    import re as _re

    source = _io.open("scripts/notify_smoke.py", encoding="utf-8").read()
    assert "_spec_for" not in source
    assert _re.search(r"from backtrader\.notifications import .*channel_requires", source)
