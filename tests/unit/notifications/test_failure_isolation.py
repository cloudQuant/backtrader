"""AC32-11: failure isolation across channels and the ``Strategy`` entry point."""

import json

import backtrader as bt

from .conftest import FakeTransport, json_response, wait_until

CSV = "tests/datas/2006-day-001.txt"


def _add_csv(cerebro):
    """Add the shared CSV fixture feed to a cerebro."""
    cerebro.adddata(
        bt.feeds.GenericCSVData(
            dataname=CSV,
            dtformat="%Y-%m-%d",
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
        )
    )


def test_one_failing_channel_does_not_affect_the_others(notifier_env):
    """Three channels, three independent classifications."""

    def handler(request):
        if "dingtalk" in request.url:
            return json_response({"errcode": 500}, status=500)
        if "ntfy" in request.url:
            return json_response({"errcode": 0})
        return json_response({"ok": False, "error_code": 400, "description": "bad"}, status=400)

    transport = FakeTransport(handler=handler)
    notifier_env(
        [
            {"channel": "dingtalk", "access_token": "tok"},
            {"channel": "ntfy", "topic": "t"},
            {"channel": "telegram", "bot_token": "b", "chat_id": "1"},
        ],
        transport=transport,
        retry_backoff=0.0,
        max_retries=1,
    )
    result = bt.send_message("mixed", wait=True)

    by_channel = {outcome.channel: outcome for outcome in result.outcomes}
    assert len(by_channel) == 3
    assert by_channel["ntfy"].ok is True
    assert by_channel["dingtalk"].error_category == "server"
    assert by_channel["dingtalk"].attempts == 2, "one retry then failure"
    assert by_channel["telegram"].error_category == "bad_request"
    assert by_channel["telegram"].attempts == 1, "4xx is not retried"
    assert result.accepted is True


def test_async_delivery_records_every_outcome(notifier_env):
    """Async sends record per-channel outcomes in the statistics."""

    def handler(request):
        if "ntfy" in request.url:
            return json_response({"errcode": 0})
        return json_response({"errcode": 93000, "errmsg": "invalid key"})

    notifier_env(
        [
            {"channel": "ntfy", "topic": "t"},
            {"channel": "wecom_bot", "key": "bad"},
        ],
        transport=FakeTransport(handler=handler),
    )
    assert bt.send_message("both").accepted is True
    assert bt.flush_notifications(timeout=5.0) is True
    stats = bt.notification_stats()
    assert stats["ntfy"]["sent"] == 1
    assert stats["wecom_bot"]["failed"] == 1


def test_strategy_send_message_injects_context(notifier_env):
    """``Strategy.send_message`` sends a backtest timestamp and the strategy name."""
    _, transport, _ = notifier_env([{"channel": "ntfy", "topic": "t"}])

    class ContextStrategy(bt.Strategy):
        def next(self):
            if len(self) == 3:
                self.send_message("from the strategy", level="warning")
                self.stop()

    cerebro = bt.Cerebro()
    _add_csv(cerebro)
    cerebro.addstrategy(ContextStrategy)
    cerebro.run()
    assert bt.flush_notifications(timeout=5.0) is True

    assert transport.requests, "the strategy message must reach the transport"
    payload = transport.bodies()[-1]
    message = payload["message"]
    assert "[WARNING] ContextStrategy" in message
    # The injected timestamp is the backtest date, not the wall clock.
    assert "2006-" in message
    assert "已截断" not in message


def test_strategy_send_message_never_raises_on_failure(notifier_env):
    """A failing channel must not break the strategy's ``next()``."""

    def handler(request):
        raise RuntimeError("transport exploded")

    notifier_env([{"channel": "ntfy", "topic": "t"}], transport=FakeTransport(handler=handler))
    completed = []

    class ResilientStrategy(bt.Strategy):
        def next(self):
            self.send_message("boom")
            completed.append(len(self))

    cerebro = bt.Cerebro()
    _add_csv(cerebro)
    cerebro.addstrategy(ResilientStrategy)
    cerebro.run()
    bt.flush_notifications(timeout=5.0)
    assert completed, "the strategy must keep running"
    stats = bt.notification_stats()["ntfy"]
    assert stats["failed"] >= 1


def test_strategy_send_message_reports_not_configured():
    """Without configuration the strategy call is inert but well-formed."""

    class QuietStrategy(bt.Strategy):
        def next(self):
            result = self.send_message("nobody")
            assert result.reason == "not_configured"
            self.stop()

    cerebro = bt.Cerebro()
    _add_csv(cerebro)
    cerebro.addstrategy(QuietStrategy)
    cerebro.run()


def test_order_of_delivery_within_a_channel_is_preserved(notifier_env):
    """A channel delivers its own queue in order."""
    seen = []

    def handler(request):
        seen.append(json.loads(request.body.decode("utf-8"))["message"].splitlines()[-1])
        return json_response({"errcode": 0})

    notifier_env([{"channel": "ntfy", "topic": "t"}], transport=FakeTransport(handler=handler))
    for index in range(20):
        bt.send_message("m{0}".format(index))
    assert bt.flush_notifications(timeout=10.0) is True
    assert seen == ["m{0}".format(index) for index in range(20)]


def test_worker_survives_an_unexpected_driver_exception(notifier_env):
    """An exception escaping a driver is classified and does not kill the worker."""
    state = {"fail": True}

    def handler(request):
        if state["fail"]:
            raise ValueError("unexpected")
        return json_response({"errcode": 0})

    notifier_env([{"channel": "ntfy", "topic": "t"}], transport=FakeTransport(handler=handler))
    bt.send_message("first")
    assert bt.flush_notifications(timeout=5.0) is True
    assert bt.notification_stats()["ntfy"]["failed"] == 1

    state["fail"] = False
    bt.send_message("second")
    assert wait_until(lambda: bt.notification_stats()["ntfy"]["sent"] == 1, timeout=5.0)
    assert bt.flush_notifications(timeout=5.0) is True
