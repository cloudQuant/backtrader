"""Event recorder for HFT simulation diagnostics.

Defines :class:`Recorder`, a small bounded-history collector of timestamped
per-symbol events used to capture and replay the matching engine's activity.
"""


class Recorder:
    """Bounded-history collector of timestamped per-symbol events.

    The recorder is used by the HFT simulation stack to capture activity
    produced by the matching engine (orders, trades, cancels, etc.) so that
    it can be inspected or replayed later. Events are stored as plain
    dictionaries and trimmed to a configurable maximum length to keep memory
    usage predictable during long runs.

    Attributes:
        _maxlen: Optional maximum number of events to retain. ``None`` means
            unbounded (events accumulate for the lifetime of the recorder).
        _events: Internal list of recorded event dictionaries, in insertion
            order. Each entry has the shape
            ``{"timestamp": ..., "symbol": ..., "payload": {...}}``.
    """

    def __init__(self, maxlen=None):
        """Initialize the recorder with an optional retention cap.

        Args:
            maxlen: Maximum number of events to keep in memory. When the
                cap is exceeded, the oldest events are dropped. ``None``
                disables trimming and lets events accumulate indefinitely.
        """
        self._maxlen = maxlen
        self._events = []

    def record(self, timestamp, symbol, payload):
        """Append a new event to the recorder.

        The ``payload`` mapping is shallow-copied to insulate the recorder
        from later mutations made by the caller. When ``_maxlen`` is set and
        the new length would exceed it, the oldest entries are trimmed so
        that the internal list never grows past the cap.

        Args:
            timestamp: Event timestamp. Any value that the caller considers
                a valid time identifier (typically a ``float`` epoch second,
                but the recorder does not enforce a type).
            symbol: Trading symbol (e.g. ``"BTCUSDT"``) associated with the
                event. Used purely for indexing/inspection downstream.
            payload: Mapping describing the event body. The mapping is
                shallow-copied before being stored so that subsequent
                modifications to the caller's object do not affect the
                recorded history.

        Returns:
            dict: The recorded event dictionary as it was inserted (with
            ``timestamp``, ``symbol`` and the copied ``payload``).
        """
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
        """Return a shallow copy of the recorded events.

        The returned list is a fresh list, but the event dictionaries inside
        it are the same objects stored in the recorder. Callers that need to
        mutate individual events should copy them explicitly.

        Returns:
            list[dict]: Recorded events in insertion order (oldest first).
        """
        return list(self._events)

    def clear(self):
        """Drop every recorded event from the recorder.

        After this call :meth:`snapshot` returns an empty list and the
        recorder behaves as if it had just been constructed. The configured
        ``_maxlen`` is preserved.
        """
        self._events = []
