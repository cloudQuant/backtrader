"""Local pre-trade rule checks used by the V/L validation cases.

A rejection raised here means nothing was sent to the venue
(``dispatch_absent=True``).  Callers pass venue metadata observed through the
session's own queries, so the checks remain tied to the live instrument set.
"""

from __future__ import annotations


class LocalReject(ValueError):
    def __init__(self, rule, facts=None):
        self.rule = str(rule)
        self.facts = dict(facts or {})
        super().__init__(self.rule)


def check_instrument(row):
    if row is None:
        raise LocalReject("unknown_instrument")


def check_price_tick(price, tick):
    tick = float(tick or 0)
    if tick <= 0:
        raise LocalReject("invalid_price_tick", {"tick": tick})
    ratio = float(price) / tick
    if abs(ratio - round(ratio)) > 1e-6:
        raise LocalReject("price_tick_mismatch", {"price": float(price), "tick": tick})


def check_price_band(price, lower, upper):
    price = float(price)
    if not (float(lower) <= price <= float(upper)):
        raise LocalReject(
            "price_out_of_band", {"price": price, "lower": float(lower), "upper": float(upper)}
        )


def check_volume(volume, *, max_volume=None, min_volume=1):
    volume = int(volume)
    if volume < int(min_volume or 1):
        raise LocalReject("volume_below_min", {"volume": volume, "min": min_volume})
    if max_volume and volume > int(max_volume):
        raise LocalReject("volume_above_max", {"volume": volume, "max": int(max_volume)})


def validate_order(*, instrument_row, price, volume, lower=None, upper=None):
    """Run the local rules; returns the observed metadata used by the checks."""
    check_instrument(instrument_row)
    tick = float(instrument_row.get("PriceTick") or 0)
    check_price_tick(price, tick)
    if lower is not None and upper is not None:
        check_price_band(price, lower, upper)
    check_volume(
        volume,
        max_volume=instrument_row.get("MaxLimitOrderVolume"),
        min_volume=instrument_row.get("MinLimitOrderVolume") or 1,
    )
    return {"tick": tick}
