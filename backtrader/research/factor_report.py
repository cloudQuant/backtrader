"""Backtrader adapter for fincore's bilingual factor HTML report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from ..errors import DependencyError, ResearchConfigError


_REPORT_LABELS = ("next_open_to_open", "close_to_close")


def write_factor_report(
    panel: Any,
    factor_name: str,
    output_path: Any,
    *,
    periods: Sequence[int] = (1, 5, 20),
    quantiles: int = 5,
    max_loss: float = 1.0,
    label: str = "next_open_to_open",
    language: str = "zh",
    title: Optional[str] = None,
) -> Path:
    """Render one panel factor through fincore's public report entry point.

    The report supports ``next_open_to_open`` and ``close_to_close`` labels.
    It applies the selected factor's declared direction. Next-open reports pass
    raw open prices with ``next_open=True``; close-to-close reports pass raw
    close prices with ``next_open=False`` so fincore computes each label once.
    """
    if factor_name not in panel.factor_order:
        raise KeyError("factor %r is not in the panel" % factor_name)
    if not isinstance(label, str) or label not in _REPORT_LABELS:
        raise ResearchConfigError(
            "factor reports support only next_open_to_open and close_to_close labels",
            code="INVALID_CONFIG",
            report={"field": "label", "supported": _REPORT_LABELS},
        )

    try:
        from fincore.report.factor import write_factor_report as _write_factor_report
    except ImportError as exc:
        raise DependencyError(
            "the factor HTML report requires a fincore build with "
            "fincore.report.factor.write_factor_report",
            code="DEPENDENCY_UNAVAILABLE",
        ) from exc

    factor = panel.factor_values(factor_name).mul(panel.directions[factor_name]).rename("factor")
    if label == "next_open_to_open":
        prices = panel.prices_open
        next_open = True
    else:
        prices = panel.prices_close
        next_open = False
    return _write_factor_report(
        factor,
        prices,
        output_path,
        periods=tuple(periods),
        quantiles=quantiles,
        max_loss=max_loss,
        title=title or factor_name,
        language=language,
        next_open=next_open,
    )


__all__ = ("write_factor_report",)
