from backtrader.channel import StreamingEventQueue

__all__ = ["MixedChannel", "build_mixed_channel"]


class MixedChannel(StreamingEventQueue):
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
        merged_channels = []
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
    return MixedChannel(
        channels=channels,
        bars=bars,
        tick_channels=tick_channels,
        orderbook_channels=orderbook_channels,
        funding_channels=funding_channels,
        **kwargs,
    )
