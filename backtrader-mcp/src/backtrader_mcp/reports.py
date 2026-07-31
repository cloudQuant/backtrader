"""Canonical metric normalization, comparison, and report rendering."""

from __future__ import annotations

import math
from typing import Any

from .errors import InvalidRequest
from .util import sha256_json

INTEGER_METRICS = (
    "bar_num",
    "buy_count",
    "sell_count",
    "win_count",
    "loss_count",
    "trade_num",
)
FLOAT_METRICS = (
    "final_value",
    "sharpe_ratio",
    "annual_return",
    "max_drawdown",
    "return_rate",
)
STANDARD_METRICS = INTEGER_METRICS + FLOAT_METRICS
NULLABLE_METRICS = {"sharpe_ratio", "annual_return"}


def normalize_metrics(metrics: Any) -> dict[str, int | float | None]:
    if not isinstance(metrics, dict) or set(metrics) != set(STANDARD_METRICS):
        raise InvalidRequest("run metrics must contain exactly the 11 canonical fields")
    normalized: dict[str, int | float | None] = {}
    for name in INTEGER_METRICS:
        value = metrics[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise InvalidRequest(f"metric {name} must be a non-negative integer")
        normalized[name] = value
    for name in FLOAT_METRICS:
        value = metrics[name]
        if value is None and name in NULLABLE_METRICS:
            normalized[name] = None
        elif (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise InvalidRequest(f"metric {name} must be finite or contract-nullable")
        else:
            normalized[name] = float(value)
    return normalized


def compare_metrics(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    rel_tol: float = 1e-7,
    abs_tol: float = 1e-9,
) -> dict[str, Any]:
    left_normalized = normalize_metrics(left)
    right_normalized = normalize_metrics(right)
    diagnostics: list[dict[str, Any]] = []
    for name in INTEGER_METRICS:
        if left_normalized[name] != right_normalized[name]:
            diagnostics.append(
                {
                    "metric": name,
                    "code": "exact_mismatch",
                    "left": left_normalized[name],
                    "right": right_normalized[name],
                }
            )
    for name in FLOAT_METRICS:
        left_value = left_normalized[name]
        right_value = right_normalized[name]
        if left_value is None or right_value is None:
            if left_value is not None or right_value is not None:
                diagnostics.append(
                    {
                        "metric": name,
                        "code": "null_mismatch",
                        "left": left_value,
                        "right": right_value,
                    }
                )
        elif not math.isclose(left_value, right_value, rel_tol=rel_tol, abs_tol=abs_tol):
            diagnostics.append(
                {
                    "metric": name,
                    "code": "float_mismatch",
                    "left": left_value,
                    "right": right_value,
                    "relative_tolerance": rel_tol,
                    "absolute_tolerance": abs_tol,
                }
            )
    core = {
        "schema_version": "run-comparison-v1",
        "status": "matched" if not diagnostics else "mismatched",
        "diagnostics": diagnostics,
        "profile": {
            "id": "comparison-profile-v1",
            "integer_mode": "exact",
            "relative_tolerance": rel_tol,
            "absolute_tolerance": abs_tol,
            "null_mode": "null_equals_null_only",
        },
    }
    return {**core, "comparison_hash": sha256_json(core)}


def render_markdown(result: dict[str, Any]) -> str:
    metrics = normalize_metrics(result["metrics"])
    labels = {
        "annual_return": "annual_return (ratio)",
        "max_drawdown": "max_drawdown (percent)",
        "return_rate": "return_rate (percent)",
    }
    lines = [
        "# Backtrader MCP run report",
        "",
        f"- Run: `{result['run_id']}`",
        f"- Status: `{result['status']}`",
        f"- Result hash: `{result['result_hash']}`",
        "",
        "## Canonical metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for name in STANDARD_METRICS:
        lines.append(f"| {labels.get(name, name)} | {metrics[name]} |")
    diagnostics = result.get("diagnostics", [])
    lines.extend(["", "## Diagnostics", "", f"- Count: {len(diagnostics)}"])
    return "\n".join(lines) + "\n"
