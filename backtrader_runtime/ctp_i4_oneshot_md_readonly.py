"""I4-named entry to the reviewed one-shot, read-only MD probe.

I4 keeps the same SDK class names and callback contract as I3. Its additional
public in-flight callback counter satisfies the I3 adapter's shutdown gate, so
the protocol stays shared while the composition and installed artifact pin
remain independently I4-scoped.
"""

from __future__ import annotations

from typing import Any

from .ctp_i3_oneshot_md_readonly import (
    CtpI3OneShotMdObservation,
    probe_i3_oneshot_md_readonly,
)


CtpI4OneShotMdObservation = CtpI3OneShotMdObservation


def probe_i4_oneshot_md_readonly(**kwargs: Any) -> CtpI4OneShotMdObservation:
    """Run the I4-compatible one-shot protocol through the shared adapter."""

    return probe_i3_oneshot_md_readonly(**kwargs)


__all__ = ["CtpI4OneShotMdObservation", "probe_i4_oneshot_md_readonly"]
