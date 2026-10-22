"""Backtrader adapter for fincore's bilingual factor HTML report."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence


def write_factor_report(
    dataset: Any,
    factor_name: str,
    output_path: Any,
    *,
    periods: Sequence[int] = (1, 5, 20),
    quantiles: int = 5,
    max_loss: float = 1.0,
    language: str = "zh",
    title: Optional[str] = None,
) -> Path:
    """Render one dataset factor through fincore's public report entry point."""
    try:
        from fincore.report.factor import write_factor_report as _write_factor_report
    except ImportError as exc:
        raise RuntimeError(
            "the factor HTML report requires a fincore build with "
            "fincore.report.factor.write_factor_report"
        ) from exc

    factors = dataset.raw_factors
    if factor_name not in factors.columns:
        raise KeyError("factor %r is not in the dataset" % factor_name)
    prices = (dataset.prices or {}).get("open")
    if prices is None:
        raise ValueError("the dataset must retain open prices for a factor report")
    return _write_factor_report(
        factors[factor_name].rename("factor"),
        prices,
        output_path,
        periods=tuple(periods),
        quantiles=quantiles,
        max_loss=max_loss,
        title=title or factor_name,
        language=language,
        next_open=True,
    )
