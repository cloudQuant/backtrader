"""Channel-to-LineSeries bridge for indicator compatibility.

ChannelBridge optionally bridges data from Channel events to LineSeries,
enabling the use of traditional backtrader indicators (SMA, RSI, etc.)
on tick-level data. This comes with a performance overhead warning.

Example::

    bridge = ChannelBridge(tick_channel, fields=['price', 'volume'])
    bridge.update(tick_event)
    # Now bridge.lines.price[0] contains the latest tick price
"""

import logging
from collections import deque

logger = logging.getLogger(__name__)

__all__ = ["ChannelBridge"]


class ChannelBridge:
    """Bridge between DataChannel events and a simple line-like interface.

    Buffers specified fields from channel events into deque-based lines
    that can be accessed with [0], [-1] indexing. This is a lightweight
    bridge - it does NOT create full LineSeries objects but provides
    a compatible enough interface for simple indicator usage.

    Note:
        Using ChannelBridge adds overhead. Only use it when you need
        indicators on channel data. For pure tick processing, use
        channel events directly.

    Args:
        channel: The DataChannel to bridge from.
        fields: List of field names to bridge (e.g., ['price', 'volume']).
        maxlen: Maximum number of values to retain per line.

    Example::

        bridge = ChannelBridge(tick_ch, fields=['price', 'volume'])
        bridge.update(tick_event)
        print(bridge['price'][0])   # latest price
        print(bridge['price'][-1])  # previous price
    """

    def __init__(self, channel, fields=None, maxlen=10000):
        """Initialize the channel bridge.

        Args:
            channel: The DataChannel instance to bridge.
            fields: Optional list of field names to extract.
            maxlen: Maximum deque length for each field.
        """
        self.channel = channel
        self._maxlen = maxlen
        self._fields = fields or self._default_fields(channel)
        self._lines = {f: deque(maxlen=maxlen) for f in self._fields}
        self._count = 0

    def _default_fields(self, channel):
        """Determine default fields based on channel type.

        Args:
            channel: The DataChannel instance to introspect.

        Returns:
            List of default field names for the channel type.
        """
        type_fields = {
            "tick": ["price", "volume", "timestamp"],
            "orderbook": ["timestamp"],
            "funding": ["rate", "mark_price", "timestamp"],
            "bar": ["open", "high", "low", "close", "volume", "timestamp"],
        }
        return type_fields.get(channel.channel_type, ["timestamp"])

    def update(self, event):
        """Update bridge lines with data from a new event.

        Args:
            event: An EventData instance whose fields are extracted.
        """
        for field in self._fields:
            value = getattr(event, field, None)
            if value is not None:
                self._lines[field].append(value)
            else:
                self._lines[field].append(float("nan"))
        self._count += 1

    @property
    def fields(self):
        """List of bridged field names."""
        return list(self._fields)

    @property
    def count(self):
        """Number of events bridged."""
        return self._count

    def __getitem__(self, field):
        """Get a line by field name.

        Args:
            field: Field name string.

        Returns:
            _BridgeLine accessor for the field.
        """
        if field not in self._lines:
            raise KeyError(f"Field '{field}' not bridged. Available: {list(self._lines.keys())}")
        return _BridgeLine(self._lines[field])

    def __len__(self):
        """Number of data points in the bridge."""
        if self._lines:
            return len(next(iter(self._lines.values())))
        return 0

    def __repr__(self):
        """Return a string representation of the bridge.

        Returns:
            str: Representation showing channel, fields, and event count.
        """
        return f"ChannelBridge(channel={self.channel!r}, fields={self._fields}, count={self._count})"


class _BridgeLine:
    """Accessor for a single bridged line with [-n] indexing.

    Supports [0] for latest, [-1] for previous, etc. Mimics
    backtrader's line indexing convention.
    """

    def __init__(self, data):
        """Initialize the bridge line accessor.

        Args:
            data: Deque containing the historical values for this line.
        """
        self._data = data

    def __getitem__(self, index):
        """Access line values with backtrader-style indexing.

        Supports backtrader's line indexing convention where:
            [0] = latest value (last element)
            [-1] = previous value (second to last)
            [-2] = two values back
            [n] = future offset from current (only 0 supported)

        Args:
            index: Integer index (0 for latest, negative for historical).

        Returns:
            float: The value at the specified index, or NaN if out of bounds.
        """
        if not self._data:
            return float("nan")
        if index == 0:
            return self._data[-1]
        elif index < 0:
            # -1 = previous, -2 = two back, etc.
            pos = len(self._data) + index - 1
            if 0 <= pos < len(self._data):
                return self._data[pos]
            return float("nan")
        else:
            return float("nan")

    def __len__(self):
        """Return the number of data points in the line."""
        return len(self._data)

    def __repr__(self):
        """Return a string representation of the bridge line.

        Returns:
            str: Representation showing data length.
        """
        return f"_BridgeLine(length={len(self._data)})"
