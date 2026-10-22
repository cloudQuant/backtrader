"""Backtrader adapter for fincore's bilingual factor HTML report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence


def write_factor_report(
    panel: Any,
    factor_name: str,
    output_path: Any,
    *,
    periods: Sequence[int] = (1, 5, 20),
    quantiles: int = 5,
    max_loss: float = 1.0,
    language: str = "zh",
    title: Optional[str] = None,
) -> Path:
    """Render one panel factor through fincore's public report entry point.

    The report keeps the raw open price frame and asks fincore for
    ``next_open=True``, so the single next-open shift happens inside fincore.
    """
    try:
        from fincore.report.factor import write_factor_report as _write_factor_report
    except ImportError as exc:
        raise RuntimeError(
            "the factor HTML report requires a fincore build with "
            "fincore.report.factor.write_factor_report"
        ) from exc

    if factor_name not in panel.factor_order:
        raise KeyError("factor %r is not in the panel" % factor_name)
    return _write_factor_report(
        panel.factor_values(factor_name).rename("factor"),
        panel.prices_open,
        output_path,
        periods=tuple(periods),
        quantiles=quantiles,
        max_loss=max_loss,
        title=title or factor_name,
        language=language,
        next_open=True,
    )


__all__ = ("write_factor_report",)
