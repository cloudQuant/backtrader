"""Native Backtrader implementation of Alpha101 #3 for a multi-feed panel."""

from collections import deque
from datetime import timezone
import math

from backtrader.research import FactorIndicator


class Alpha003Indicator(FactorIndicator):
    """Negative rolling correlation of cross-sectional open and volume ranks."""

    lines = ("factor",)
    panel_mode = "next"
    params = (("period", 10),)
    formula_fields = ("open", "volume")

    @classmethod
    def lookback_h(cls, period=10):
        """Return the historical span needed for a rolling period of grid rows."""
        if type(period) is not int or period < 2:
            raise ValueError("period must be an integer >= 2")
        return period - 1

    def __init__(self):
        super().__init__()
        period = self.p.period
        if type(period) is not int or period < 2:
            raise ValueError("period must be an integer >= 2")

        self._period = period
        self._open_ranks = {data: deque(maxlen=period) for data in self.datas}
        self._volume_ranks = {data: deque(maxlen=period) for data in self.datas}
        self.diagnostics = []
        self.grid_call_counts = {}
        self.evaluation_count = 0

    @staticmethod
    def _rank(values):
        """Return average-tie ranks divided by the number of finite values."""
        ranked = [(index, value) for index, value in enumerate(values) if math.isfinite(value)]
        count = len(ranked)
        result = [math.nan] * len(values)
        if not count:
            return result

        ranked.sort(key=lambda item: item[1])
        start = 0
        while start < count:
            end = start + 1
            while end < count and ranked[end][1] == ranked[start][1]:
                end += 1
            average_rank = ((start + 1) + end) / 2.0
            normalized_rank = average_rank / count
            for offset in range(start, end):
                result[ranked[offset][0]] = normalized_rank
            start = end
        return result

    @staticmethod
    def _pearson(left, right):
        if not left or len(left) != len(right):
            return None
        if not all(math.isfinite(value) for value in (*left, *right)):
            return None

        count = len(left)
        left_mean = math.fsum(left) / count
        right_mean = math.fsum(right) / count
        left_centered = [value - left_mean for value in left]
        right_centered = [value - right_mean for value in right]
        left_sum_squares = math.fsum(value * value for value in left_centered)
        right_sum_squares = math.fsum(value * value for value in right_centered)
        if left_sum_squares == 0.0 or right_sum_squares == 0.0:
            return None

        covariance = math.fsum(
            left_value * right_value
            for left_value, right_value in zip(left_centered, right_centered)
        )
        correlation = covariance / math.sqrt(left_sum_squares * right_sum_squares)
        if not math.isfinite(correlation):
            return None
        tolerance = 1e-12
        if correlation > 1.0:
            return 1.0 if correlation <= 1.0 + tolerance else None
        if correlation < -1.0:
            return -1.0 if correlation >= -1.0 - tolerance else None
        return correlation

    @staticmethod
    def _timestamp(data):
        timestamp = data.datetime.datetime(0)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
        return timestamp.isoformat()

    def prenext(self):
        self.next()

    def nextstart(self):
        self.next()

    def next(self):
        """Evaluate one complete Cerebro grid event for every bound feed."""
        if not self.datas:
            return

        timestamp = self._timestamp(self.datas[0])
        calls = self.grid_call_counts.get(timestamp, 0) + 1
        self.grid_call_counts[timestamp] = calls
        self.evaluation_count += 1

        opens = [float(data.open[0]) for data in self.datas]
        volumes = [float(data.volume[0]) for data in self.datas]
        open_ranks = self._rank(opens)
        volume_ranks = self._rank(volumes)

        for index, data in enumerate(self.datas):
            open_history = self._open_ranks[data]
            volume_history = self._volume_ranks[data]
            open_history.append(open_ranks[index])
            volume_history.append(volume_ranks[index])

            correlation = math.nan
            factor = math.nan
            if len(open_history) < self._period:
                reason = "NOT_READY"
            elif not all(
                math.isfinite(value) for value in (*open_history, *volume_history)
            ):
                reason = "INCOMPLETE_WINDOW"
            else:
                correlation_value = self._pearson(open_history, volume_history)
                if correlation_value is None:
                    reason = "DOMAIN_ERROR"
                else:
                    correlation = correlation_value
                    factor = -correlation_value
                    reason = "READY"

            self.outputs[data].factor[0] = factor
            self.diagnostics.append(
                {
                    "time": timestamp,
                    "asset": data._name,
                    "open": opens[index],
                    "volume": volumes[index],
                    "open_rank": open_ranks[index],
                    "volume_rank": volume_ranks[index],
                    "correlation": correlation,
                    "factor": factor,
                    "reason": reason,
                    "grid_call_count": calls,
                }
            )
