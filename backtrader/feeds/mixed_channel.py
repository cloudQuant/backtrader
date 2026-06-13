"""Mixed multi-source streaming channel.

Defines :class:`MixedChannel`, a :class:`~backtrader.channel.StreamingEventQueue`
that merges several event channels (generic, tick, order book, funding) into a
single time-ordered stream for tick-level backtesting, plus the
:func:`build_mixed_channel` convenience constructor.
"""

from backtrader.channel import StreamingEventQueue

__all__ = ["MixedChannel", "build_mixed_channel"]


class MixedChannel(StreamingEventQueue):
    """Streaming event queue that merges multiple channel groups into one stream.

    The constructor flattens the per-group channel lists
    (``channels``, ``tick_channels``, ``orderbook_channels``,
    ``funding_channels``) into a single ``merged_channels`` list and
    delegates to :class:`StreamingEventQueue`. The remaining keyword
    arguments (``preload_window``, ``max_memory_mb``, ``adaptive``,
    ``batch_size``) are forwarded unchanged.
    """

    def __init__(
        self,
        channels=None,
        bars=None,
        tick_channels=None,
        orderbook_channels=None,
        funding_channels=None,
        preload_window=300.0,
        max_memory_mb=200,
        adaptive=True,
        batch_size=10000,
    ):
        """Build a merged-channel streaming queue.

        Args:
            channels: Optional iterable of generic event channels.
            bars: Optional iterable of pre-built bar objects. Copied
                into a list before being forwarded to the base class.
            tick_channels: Optional iterable of tick event channels.
            orderbook_channels: Optional iterable of order-book event
                channels.
            funding_channels: Optional iterable of funding-rate event
                channels.
            preload_window: Preload window size in seconds, forwarded
                to :class:`StreamingEventQueue`.
            max_memory_mb: Soft memory cap (in MB) for the queue,
                forwarded to the base class.
            adaptive: Whether the queue should adapt its batching
                strategy, forwarded to the base class.
            batch_size: Default batch size, forwarded to the base
                class.
        """
        merged_channels: list = []
        for group in (
            channels or [],
            tick_channels or [],
            orderbook_channels or [],
            funding_channels or [],
        ):
            merged_channels.extend(group)

        super().__init__(
            channels=merged_channels,
            bars=list(bars or []),
            preload_window=preload_window,
            max_memory_mb=max_memory_mb,
            adaptive=adaptive,
            batch_size=batch_size,
        )


def build_mixed_channel(
    channels=None,
    bars=None,
    tick_channels=None,
    orderbook_channels=None,
    funding_channels=None,
    **kwargs,
):
    """Construct a :class:`MixedChannel` with the standard per-group arguments.

    All extra keyword arguments are forwarded to :class:`MixedChannel`
    so callers can pass ``preload_window``, ``max_memory_mb``,
    ``adaptive`` and ``batch_size`` without listing them explicitly.

    Args:
        channels: Optional iterable of generic event channels.
        bars: Optional iterable of pre-built bar objects.
        tick_channels: Optional iterable of tick event channels.
        orderbook_channels: Optional iterable of order-book channels.
        funding_channels: Optional iterable of funding-rate channels.
        **kwargs: Forwarded to :class:`MixedChannel`.

    Returns:
        MixedChannel: A new :class:`MixedChannel` instance.
    """
    return MixedChannel(
        channels=channels,
        bars=bars,
        tick_channels=tick_channels,
        orderbook_channels=orderbook_channels,
        funding_channels=funding_channels,
        **kwargs,
    )
