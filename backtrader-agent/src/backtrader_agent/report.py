"""Run result normalization, comparison, and immutable report rendering."""

import html
import math
from pathlib import Path
from typing import Any, Dict

from .canonical import atomic_write_bytes, atomic_write_json, hash_object
from .errors import AgentError

METRIC_NAMES = (
    "bar_num",
    "buy_count",
    "sell_count",
    "win_count",
    "loss_count",
    "trade_num",
    "final_value",
    "sharpe_ratio",
    "annual_return",
    "max_drawdown",
    "return_rate",
)
INTEGER_METRICS = {
    "bar_num",
    "buy_count",
    "sell_count",
    "win_count",
    "loss_count",
    "trade_num",
}
NULLABLE_METRICS = {"sharpe_ratio", "annual_return"}
EVENT_FIELDS = (
    "sequence",
    "kind",
    "data",
    "size",
    "price",
    "status",
)


def normalize_metrics(raw: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for name in METRIC_NAMES:
        value = raw.get(name)
        if value is None:
            if name in NULLABLE_METRICS:
                normalized[name] = None
                continue
            raise AgentError("BTAG-RUN-METRIC", f"metric '{name}' is required")
        if name in INTEGER_METRICS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AgentError("BTAG-RUN-METRIC", f"metric '{name}' must be an integer")
            normalized[name] = int(value)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AgentError("BTAG-RUN-METRIC", f"metric '{name}' must be numeric or null")
        number = float(value)
        if not math.isfinite(number):
            raise AgentError("BTAG-RUN-METRIC", f"metric '{name}' must be finite")
        normalized[name] = number
    return normalized


def compare_metrics(
    left: Dict[str, Any],
    right: Dict[str, Any],
    *,
    rel_tol: float = 1e-7,
    abs_tol: float = 1e-9,
) -> Dict[str, Any]:
    differences = []
    for name in METRIC_NAMES:
        first = left.get(name)
        second = right.get(name)
        if first is None or second is None:
            equal = first is None and second is None
        elif name in INTEGER_METRICS:
            equal = first == second
        else:
            equal = math.isclose(float(first), float(second), rel_tol=rel_tol, abs_tol=abs_tol)
        if not equal:
            differences.append({"metric": name, "left": first, "right": second})
    return {
        "status": "passed" if not differences else "failed",
        "profile": {
            "profile_version": "comparison-profile-v1",
            "integer_metrics": sorted(INTEGER_METRICS),
            "float_metrics": [name for name in METRIC_NAMES if name not in INTEGER_METRICS],
            "nullable_metrics": sorted(NULLABLE_METRICS),
            "default_float_tolerance": {
                "rel_tol": rel_tol,
                "abs_tol": abs_tol,
            },
            "non_finite": "fail",
            "missing_required": "fail",
            "null_comparison": "only_equal_to_null",
            "event_fields": list(EVENT_FIELDS),
        },
        "differences": differences,
    }


class ReportRenderer:
    def render(self, run_root: Path, result: Dict[str, Any]) -> Dict[str, str]:
        run_root = Path(run_root)
        metrics = result.get("metrics", {})
        extension = result.get("extensions", {}).get("backtrader_agent", {})
        rows = "\n".join(
            f"| {name} | {metrics.get(name) if metrics.get(name) is not None else 'null'} |"
            for name in METRIC_NAMES
        )
        limitations = extension.get("limitations", [])
        limitation_lines = "\n".join(f"- {item}" for item in limitations) or "- None recorded"
        markdown = f"""# Backtrader Agent Run Report

- Run ID: `{result['run_id']}`
- Status: `{result['status']}`
- Mode: `{extension.get('mode')}`
- Dataset manifest: `{extension.get('dataset_manifest_hash')}`
- Applied artifact: `{extension.get('applied_artifact_hash')}`

## Metrics

| Metric | Value |
| --- | ---: |
{rows}

## Provenance

- Run manifest: `{extension.get('manifest_hash')}`
- Validation token: `{extension.get('validation_token_id')}`
- Run token: `{extension.get('run_token_id')}`
- Command profile: `controlled-runner-v1`

## Honest limitations

{limitation_lines}
"""
        html_rows = "".join(
            f"<tr><th>{html.escape(name)}</th><td>{html.escape(str(metrics.get(name)))}</td></tr>"
            for name in METRIC_NAMES
        )
        html_limitations = "".join(f"<li>{html.escape(item)}</li>" for item in limitations)
        document = (
            '<!doctype html><html><head><meta charset="utf-8">'
            "<title>Backtrader Agent Run Report</title></head><body>"
            f"<h1>Run {html.escape(result['run_id'])}</h1>"
            f"<p>Status: {html.escape(result['status'])}; "
            f"mode: {html.escape(str(extension.get('mode')))}</p>"
            f"<table>{html_rows}</table><h2>Limitations</h2><ul>{html_limitations}</ul>"
            "</body></html>"
        )
        result_path = run_root / "run-result.json"
        markdown_path = run_root / "report.md"
        html_path = run_root / "report.html"
        atomic_write_json(result_path, result, create_only=True)
        atomic_write_bytes(markdown_path, markdown.encode("utf-8"), create_only=True)
        atomic_write_bytes(html_path, document.encode("utf-8"), create_only=True)
        return {
            "result": result_path.name,
            "markdown": markdown_path.name,
            "html": html_path.name,
            "report_hash": hash_object(
                {
                    "result": result,
                    "markdown": markdown,
                    "html": document,
                }
            ),
        }
