"""The factor author's complete implementation; no custom Strategy.next()."""

from factor_strategy import PanelFactorIndicator


class Alpha003Indicator(PanelFactorIndicator):
    """Alpha101 #3: negative time correlation of two daily cross-sectional ranks."""

    @classmethod
    def build(cls, ctx):
        return -ctx.correlation(ctx.rank(ctx.open), ctx.rank(ctx.volume), 10)
