"""Event recorder for HFT simulation diagnostics.

Defines :class:`Recorder`, a small bounded-history collector of timestamped
per-symbol events used to capture and replay the matching engine's activity.
"""


class Recorder:
    def __init__(self, maxlen=None):
        self._maxlen = maxlen
        self._events = []

    def record(self, timestamp, symbol, payload):
        item = {
            "timestamp": timestamp,
            "symbol": symbol,
            "payload": dict(payload),
        }
        self._events.append(item)
        if self._maxlen is not None and len(self._events) > self._maxlen:
            self._events = self._events[-self._maxlen :]
        return item

    def snapshot(self):
        return list(self._events)

    def clear(self):
        self._events = []
