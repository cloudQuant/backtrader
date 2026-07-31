"""ComparisonProfile v1 implementation for metrics and normalized events."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

from .canonical import canonical_hash
from .errors import ContractError
from .resources import resource_path


def load_comparison_profile(path: Path | None = None) -> dict[str, Any]:
    selected = path or resource_path("policies", "comparison-profile-v1.json")
    with selected.open("r", encoding="utf-8") as handle:
        profile = json.load(handle)
    if profile.get("profile_version") != "comparison-profile-v1":
        raise ContractError("unsupported comparison profile")
    profile["profile_hash"] = canonical_hash(profile)
    return cast(dict[str, Any], profile)


def _valid_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def validate_metrics(
    metrics: dict[str, Any], profile: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    profile = profile or load_comparison_profile()
    diagnostics: list[dict[str, Any]] = []
    nullable = set(profile["nullable_metrics"])
    required = [*profile["integer_metrics"], *profile["float_metrics"]]
    for key in required:
        if key not in metrics:
            diagnostics.append(
                {"code": "METRIC_MISSING", "metric": key, "message": "required metric is missing"}
            )
            continue
        value = metrics[key]
        if value is None:
            if key not in nullable:
                diagnostics.append(
                    {
                        "code": "METRIC_NULL_FORBIDDEN",
                        "metric": key,
                        "message": "metric is not nullable",
                    }
                )
            continue
        if key in profile["integer_metrics"]:
            if not isinstance(value, int) or isinstance(value, bool):
                diagnostics.append(
                    {
                        "code": "METRIC_INTEGER_REQUIRED",
                        "metric": key,
                        "message": "integer metric has the wrong type",
                    }
                )
        elif not _valid_number(value):
            diagnostics.append(
                {
                    "code": "METRIC_NON_FINITE",
                    "metric": key,
                    "message": "float metric must be finite",
                }
            )
    return diagnostics


def compare_metrics(
    left: dict[str, Any],
    right: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = profile or load_comparison_profile()
    diagnostics = [
        *[{"side": "left", **item} for item in validate_metrics(left, profile)],
        *[{"side": "right", **item} for item in validate_metrics(right, profile)],
    ]
    differences: list[dict[str, Any]] = []
    if not diagnostics:
        for key in profile["integer_metrics"]:
            if left[key] != right[key]:
                differences.append(
                    {
                        "metric": key,
                        "left": left[key],
                        "right": right[key],
                        "rule": "exact",
                    }
                )
        default_tolerance = profile["default_float_tolerance"]
        for key in profile["float_metrics"]:
            left_value = left[key]
            right_value = right[key]
            if left_value is None or right_value is None:
                if left_value is not None or right_value is not None:
                    differences.append(
                        {
                            "metric": key,
                            "left": left_value,
                            "right": right_value,
                            "rule": "null-only-equals-null",
                        }
                    )
                continue
            tolerance = profile.get("metric_overrides", {}).get(key, default_tolerance)
            if not math.isclose(
                float(left_value),
                float(right_value),
                rel_tol=float(tolerance["rel_tol"]),
                abs_tol=float(tolerance["abs_tol"]),
            ):
                differences.append(
                    {
                        "metric": key,
                        "left": left_value,
                        "right": right_value,
                        "rule": {
                            "rel_tol": tolerance["rel_tol"],
                            "abs_tol": tolerance["abs_tol"],
                        },
                    }
                )
    result = {
        "profile_version": profile["profile_version"],
        "profile_hash": profile["profile_hash"],
        "diagnostics": diagnostics,
        "differences": differences,
        "passed": not diagnostics and not differences,
    }
    result["comparison_hash"] = canonical_hash(result)
    return result


def compare_events(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = profile or load_comparison_profile()
    fields = profile["event_fields"]
    normalized_left = [{key: event.get(key) for key in fields} for event in left]
    normalized_right = [{key: event.get(key) for key in fields} for event in right]
    differences = []
    length = max(len(normalized_left), len(normalized_right))
    for index in range(length):
        left_event = normalized_left[index] if index < len(normalized_left) else None
        right_event = normalized_right[index] if index < len(normalized_right) else None
        if left_event != right_event:
            differences.append({"index": index, "left": left_event, "right": right_event})
            if len(differences) >= 50:
                break
    result = {
        "fields": fields,
        "left_count": len(normalized_left),
        "right_count": len(normalized_right),
        "differences": differences,
        "truncated": len(differences) == 50,
        "passed": not differences,
    }
    result["comparison_hash"] = canonical_hash(result)
    return result
