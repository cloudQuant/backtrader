"""Fail-closed staging entrypoint for future managed SimNow case wrappers.

This module validates a case-local schema-v4 configuration and then reports
that managed CTP certification is not registered. It is not an execution
route: every result is BLOCKED and the external action counters remain zero.
It deliberately does not import Backtrader, an SDK, or a provider.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Optional


_SUITE_DIR = Path(__file__).resolve().parent
_CASES_ROOT = _SUITE_DIR / "cases"
_CERTIFICATION_SOURCE = _SUITE_DIR / "common" / "certification.py"
_CASE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,3}$")
_REQUIRED_TOP_LEVEL_KEYS = frozenset(
    ("config_schema_version", "strategy", "runtime", "parameters")
)
_ALLOWED_TOP_LEVEL_KEYS = _REQUIRED_TOP_LEVEL_KEYS | frozenset(("secrets_ref",))
_MAX_CONFIG_BYTES = 64 * 1024


class _ScopeRejected(Exception):
    """A redacted, fail-closed validation rejection."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _load_code_owned_scenarios() -> dict[str, Any]:
    """Load the local certification mapping without importing its package."""

    try:
        source = _CERTIFICATION_SOURCE.resolve(strict=True)
        expected_source = (_SUITE_DIR / "common" / "certification.py").resolve(
            strict=True
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise _ScopeRejected("managed_ctp_certification_registry_invalid") from exc
    if source != expected_source or not source.is_file():
        raise _ScopeRejected("managed_ctp_certification_registry_invalid")

    module_name = "_iteration41_007_simnow_certification_mapping"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise _ScopeRejected("managed_ctp_certification_registry_invalid")

    module = importlib.util.module_from_spec(spec)
    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        rows = module.all_certification_scenarios()
        mapping = module.SCENARIOS_BY_CASE_ID
    except Exception as exc:
        raise _ScopeRejected("managed_ctp_certification_registry_invalid") from exc
    finally:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module

    if type(rows) is not list or len(rows) != 33 or type(mapping) is not dict:
        raise _ScopeRejected("managed_ctp_certification_registry_invalid")

    row_ids = [getattr(row, "case_id", None) for row in rows]
    if (
        any(type(case_id) is not str or not _CASE_ID_RE.fullmatch(case_id) for case_id in row_ids)
        or len(set(row_ids)) != 33
        or len(mapping) != 33
        or set(mapping) != set(row_ids)
    ):
        raise _ScopeRejected("managed_ctp_certification_registry_invalid")

    for row in rows:
        if mapping.get(row.case_id) != row:
            raise _ScopeRejected("managed_ctp_certification_registry_invalid")

    return mapping


def _expected_script(case_id: str) -> Path:
    """Return the sole accepted child path for a code-owned case ID."""

    return _CASES_ROOT / case_id / "run.py"


def _is_exact_direct_case_path(case_id: str, case_file: object) -> bool:
    """Require the supplied ``__file__`` to be the exact case-local run.py."""

    try:
        expected = _expected_script(case_id)
        supplied = Path(os.fspath(case_file))
        if not supplied.is_absolute():
            supplied = Path.cwd() / supplied

        cases_root = _CASES_ROOT.resolve(strict=True)
        case_dir = expected.parent
        if (
            case_dir.is_symlink()
            or case_dir.resolve(strict=True).parent != cases_root
            or expected.is_symlink()
            or not expected.is_file()
            or supplied.is_symlink()
        ):
            return False

        supplied_text = os.path.normcase(os.path.abspath(os.fspath(supplied)))
        expected_text = os.path.normcase(os.path.abspath(os.fspath(expected)))
        return supplied_text == expected_text and supplied.resolve(strict=True) == expected.resolve(
            strict=True
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _strict_yaml_mapping(raw: bytes) -> Any:
    """Parse one safe YAML document while rejecting duplicate/merged keys."""

    try:
        import yaml
    except ImportError as exc:
        raise _ScopeRejected("managed_ctp_certification_config_invalid") from exc

    class UniqueKeySafeLoader(yaml.SafeLoader):
        pass

    def construct_unique_mapping(loader: Any, node: Any, deep: bool = False) -> dict:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(
                None, None, "expected a mapping", node.start_mark
            )

        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise yaml.constructor.ConstructorError(
                    None, None, "YAML merge keys are not allowed", key_node.start_mark
                )
            key = loader.construct_object(key_node, deep=deep)
            if type(key) is not str or key in result:
                raise yaml.constructor.ConstructorError(
                    None, None, "mapping keys must be unique strings", key_node.start_mark
                )
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueKeySafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping
    )
    try:
        return yaml.load(raw, Loader=UniqueKeySafeLoader)
    except Exception as exc:
        raise _ScopeRejected("managed_ctp_certification_config_invalid") from exc


def _validated_case_config_digest(case_file: Path, case_id: str) -> Optional[str]:
    """Validate one read of the non-secret case config and return its digest."""

    config_path = case_file.parent / "config.yaml"
    try:
        if config_path.is_symlink() or not config_path.is_file():
            return None
        resolved_config = config_path.resolve(strict=True)
        if resolved_config != config_path.parent.resolve(strict=True) / "config.yaml":
            return None
        if config_path.stat().st_size > _MAX_CONFIG_BYTES:
            return None
        raw = config_path.read_bytes()
        if len(raw) > _MAX_CONFIG_BYTES:
            return None
    except (OSError, RuntimeError, ValueError):
        return None

    document = _strict_yaml_mapping(raw)
    if (
        type(document) is not dict
        or not _REQUIRED_TOP_LEVEL_KEYS.issubset(document)
        or not frozenset(document).issubset(_ALLOWED_TOP_LEVEL_KEYS)
    ):
        return None
    if "secrets_ref" in document and document["secrets_ref"] != "none":
        return None
    if type(document["config_schema_version"]) is not int or document[
        "config_schema_version"
    ] != 4:
        return None

    strategy = document["strategy"]
    runtime = document["runtime"]
    parameters = document["parameters"]
    if (
        type(strategy) is not dict
        or frozenset(strategy) != frozenset(("id",))
        or type(strategy["id"]) is not str
        or strategy["id"] != f"example.007_ctp.simnow_penetration.{case_id}"
    ):
        return None
    if (
        type(runtime) is not dict
        or frozenset(runtime) != frozenset(("mode", "preset"))
        or type(runtime["mode"]) is not str
        or runtime["mode"] != "simulation"
        or type(runtime["preset"]) is not str
        or runtime["preset"] != "sandbox"
    ):
        return None
    if not (
        type(parameters) is dict
        and frozenset(parameters) == frozenset(("scenario",))
        and type(parameters["scenario"]) is str
        and parameters["scenario"] == case_id
    ):
        return None
    return hashlib.sha256(raw).hexdigest()


def _has_exact_case_config(case_file: Path, case_id: str) -> bool:
    """Validate the exact non-secret case-local schema-v4 configuration."""

    return _validated_case_config_digest(case_file, case_id) is not None


def _emit_blocked(
    reason: str,
    *,
    case_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
) -> int:
    """Print only code-owned identifiers and zero-I/O staging facts."""

    result: dict[str, Any] = {
        "status": "BLOCKED",
        "reason": reason,
        "evidence_boundary": "STAGING_ONLY_NOT_AUTHORITY",
        "external_request_counts": {"network": 0, "order_write": 0},
    }
    if case_id is not None:
        result["case_id"] = case_id
    if scenario_id is not None:
        result["scenario_id"] = scenario_id
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2


def main(case_id: str, case_file: object) -> int:
    """Validate a staged case and always return a redacted BLOCKED result.

    Each future ``cases/<CASE_ID>/run.py`` wrapper should call
    ``main(CASE_ID, __file__)``. A well-formed case-local config reaches the
    explicit ``managed_ctp_certification_not_registered`` result; validation
    failures remain blocked with generic redacted reasons.
    """

    try:
        scenarios = _load_code_owned_scenarios()
    except _ScopeRejected as exc:
        return _emit_blocked(exc.reason)

    if type(case_id) is not str or case_id not in scenarios:
        return _emit_blocked("managed_ctp_certification_case_id_invalid")

    scenario = scenarios[case_id]
    if not _is_exact_direct_case_path(case_id, case_file):
        return _emit_blocked(
            "managed_ctp_certification_path_invalid", case_id=case_id
        )

    case_path = _expected_script(case_id)
    try:
        config_valid = _has_exact_case_config(case_path, case_id)
    except _ScopeRejected as exc:
        return _emit_blocked(
            exc.reason, case_id=case_id, scenario_id=scenario.scenario_id
        )
    if not config_valid:
        return _emit_blocked(
            "managed_ctp_certification_config_invalid",
            case_id=case_id,
            scenario_id=scenario.scenario_id,
        )

    return _emit_blocked(
        "managed_ctp_certification_not_registered",
        case_id=case_id,
        scenario_id=scenario.scenario_id,
    )


__all__ = ["main"]
