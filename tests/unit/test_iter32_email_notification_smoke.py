"""Backtrader email notification channel, using an injected SMTP sender."""
import backtrader as bt
from backtrader.notifications.config import configure_notifications, reset_notifications


class _Sender:
    def __init__(self):
        self.envelopes = []

    def send(self, envelope):
        self.envelopes.append(envelope)


def test_email_channel_sends_through_injected_smtp_sender():
    sender = _Sender()
    try:
        bt.configure_notifications(
            [{"channel": "email", "host": "smtp.qq.com", "port": 465,
              "to": ["ops@example.test"], "user": "ops@example.test",
              "password": "unused-in-fake", "ssl": True}],
            smtp_sender=sender,
        )
        results = bt.send_message("smtp smoke", level="info", wait=True)
        assert results
        assert len(sender.envelopes) == 1
        envelope = sender.envelopes[0]
        assert envelope.host == "smtp.qq.com" and envelope.port == 465
        assert envelope.recipients == ("ops@example.test",)
    finally:
        reset_notifications()
