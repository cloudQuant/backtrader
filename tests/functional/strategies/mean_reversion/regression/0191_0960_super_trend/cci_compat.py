from __future__ import annotations

import backtrader as bt


def ensure_safe_cci_indicator() -> None:
    class SafeCCI(bt.Indicator):
        lines = ("cci",)
        params = dict(period=20, factor=0.015)

        def __init__(self):
            self.addminperiod(int(self.p.period))

        def next(self):
            period = int(self.p.period)
            typicals = []
            for ago in range(period):
                typicals.append(
                    (
                        float(self.data.high[-ago])
                        + float(self.data.low[-ago])
                        + float(self.data.close[-ago])
                    )
                    / 3.0
                )
            mean = sum(typicals) / period
            mean_deviation = sum(abs(value - mean) for value in typicals) / period
            denominator = float(self.p.factor) * mean_deviation
            self.lines.cci[0] = (typicals[0] - mean) / denominator if denominator else 0.0

    bt.indicators.CCI = SafeCCI
    bt.indicators.CommodityChannelIndex = SafeCCI
