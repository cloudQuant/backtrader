"""Collect a sealed, local-only metadata bundle for Iteration 41 evidence.

The collector deliberately has a small and code-owned read surface.  It reads
only named JSON and JUnit artifacts below the current source tree, never a
runtime ``config.yaml``, environment variable, credential, command, network
endpoint, provider, SDK, or strategy module.  A successful collection says
only that the listed local artifacts are structurally present and internally
consistent enough to be reviewed; it is never a deployment or trading
admission.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import platform
import stat
import xml.etree.ElementTree as _element_tree
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple


EVIDENCE_SCHEMA_VERSION = "iteration41.local-evidence-bundle.v1"
EVIDENCE_KIND = "implementation_acceptance"
BASELINE_ID = "iteration41.local_metadata"
EVIDENCE_BOUNDARY = "LOCAL_METADATA_COLLECTION_ONLY_NOT_LIVE_ADMISSION"

_ITERATION41_REQUIREMENTS = (
    "docs/_internal/opts/requirements/"
    "\u8fed\u4ee341-\u5b9e\u76d8\u6267\u884c\u98ce\u63a7\u76d1\u63a7\u4e0e\u793a\u4f8b\u67b6\u6784\u91cd\u6784"
)

# These paths are deliberately code-owned.  The public CLI accepts no input
# path, glob, command, manifest, or configuration file which could expand the
# collector's read surface.
DEFAULT_ARTIFACT_SPECS: Tuple[Tuple[str, str, str], ...] = (
    (
        "runtime_inventory",
        "examples/iteration41-runtime-inventory.json",
        "json",
    ),
    (
        "writer_candidate_inventory",
        _ITERATION41_REQUIREMENTS + "/evidence/live-execution-inventory-candidates.json",
        "json",
    ),
    (
        "implementation_document_checks",
        _ITERATION41_REQUIREMENTS + "/evidence/implementation-document-checks.json",
        "json",
    ),
    (
        "cpython38_core_runtime_local_windows",
        _ITERATION41_REQUIREMENTS + "/evidence/cpython38-core-runtime-local-windows.json",
        "json",
    ),
)


class EvidenceCollectionError(ValueError):
    """A safe reason code for a rejected collector input."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _source_root() -> Path:
    """Return this package's repository root without inspecting the CWD."""

    return Path(__file__).resolve().parents[1]


def _safe_artifact_path(source_root: Path, relative_path: str) -> Path:
    """Resolve one code-owned, regular, non-link artifact below ``source_root``.

    The implementation refuses traversal and link/reparse components before
    reading any bytes.  This does not attempt to prove a hostile local Python
    process cannot modify files concurrently; it only keeps this local
    metadata collector from following an unexpected path supplied by a file.
    """

    if "\\" in relative_path:
        raise EvidenceCollectionError("artifact_path_not_code_owned")
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in ("", ".", "..") for part in relative.parts)
    ):
        raise EvidenceCollectionError("artifact_path_not_code_owned")

    try:
        root = source_root.resolve(strict=True)
    except OSError as error:
        raise EvidenceCollectionError("source_root_unavailable") from error

    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            metadata = os.lstat(str(cursor))
        except FileNotFoundError as error:
            raise EvidenceCollectionError("required_artifact_missing") from error
        except OSError as error:
            raise EvidenceCollectionError("required_artifact_unavailable") from error
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or (reparse_point and attributes & reparse_point):
            raise EvidenceCollectionError("artifact_link_or_reparse_not_allowed")

    if not stat.S_ISREG(metadata.st_mode):
        raise EvidenceCollectionError("required_artifact_not_regular")
    try:
        resolved = cursor.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise EvidenceCollectionError("artifact_outside_source_root") from error
    return resolved


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_summary(value: bytes) -> Mapping[str, object]:
    try:
        decoded = value.decode("utf-8")
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, ValueError) as error:
        raise EvidenceCollectionError("invalid_json_artifact") from error
    if not isinstance(parsed, dict):
        raise EvidenceCollectionError("json_artifact_must_be_object")

    # Preserve only a small, non-secret structural description.  Raw values
    # and arbitrary nested data deliberately never leave the collector.
    summary: Dict[str, object] = {"top_level_key_count": len(parsed)}
    for key in ("schema_version", "status", "evidence_kind", "evidence_scope"):
        value_at_key = parsed.get(key)
        if isinstance(value_at_key, (str, int, float, bool)) or value_at_key is None:
            summary[key] = value_at_key
    return summary


def _junit_summary(value: bytes) -> Mapping[str, int]:
    try:
        root = _element_tree.fromstring(value)
    except _element_tree.ParseError as error:
        raise EvidenceCollectionError("invalid_junit_artifact") from error

    testcases = list(root.iter("testcase"))
    failures = list(root.iter("failure"))
    errors = list(root.iter("error"))
    skipped = list(root.iter("skipped"))
    if not testcases:
        raise EvidenceCollectionError("junit_has_zero_testcases")
    if failures or errors:
        raise EvidenceCollectionError("junit_reports_failures")
    return {
        "testcases": len(testcases),
        "failures": len(failures),
        "errors": len(errors),
        "skipped": len(skipped),
    }


def _artifact_record(
    source_root: Path, name: str, relative_path: str, artifact_type: str
) -> Mapping[str, object]:
    """Collect safe metadata for one code-owned evidence artifact."""

    record: Dict[str, object] = {
        "name": name,
        "relative_path": relative_path,
        "artifact_type": artifact_type,
    }
    try:
        artifact = _safe_artifact_path(source_root, relative_path)
        raw = artifact.read_bytes()
        if artifact_type == "json":
            record["summary"] = _json_summary(raw)
        elif artifact_type == "junit":
            record["summary"] = _junit_summary(raw)
        else:
            raise EvidenceCollectionError("unsupported_code_owned_artifact_type")
        record["sha256"] = _sha256(raw)
        record["status"] = "PASS"
        record["reason_code"] = "structural_metadata_collected"
    except EvidenceCollectionError as error:
        record["status"] = "NOT_RUN" if error.reason_code == "required_artifact_missing" else "FAIL"
        record["reason_code"] = error.reason_code
    except OSError:
        record["status"] = "FAIL"
        record["reason_code"] = "required_artifact_read_failed"
    return record


def _bundle_status(records: Iterable[Mapping[str, object]]) -> Tuple[str, str]:
    statuses = {str(record["status"]) for record in records}
    if "FAIL" in statuses:
        return "FAIL", "artifact_validation_failed"
    if "NOT_RUN" in statuses:
        return "NOT_RUN", "required_local_artifact_missing"
    return "PASS", "local_metadata_collected"


def _bundle_digest(records: Sequence[Mapping[str, object]]) -> str:
    stable = []
    for record in records:
        stable.append(
            {
                "name": record["name"],
                "relative_path": record["relative_path"],
                "status": record["status"],
                "reason_code": record["reason_code"],
                "sha256": record.get("sha256"),
            }
        )
    encoded = json.dumps(stable, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return _sha256(encoded.encode("ascii"))


def collect_iteration41_evidence(
    source_root: Optional[Path] = None,
    artifact_specs: Sequence[Tuple[str, str, str]] = DEFAULT_ARTIFACT_SPECS,
) -> Mapping[str, object]:
    """Return a redacted structural bundle for the fixed Iteration 41 scope.

    ``source_root`` and ``artifact_specs`` exist for unit tests and reviewed
    embedding only.  The public CLI intentionally exposes neither control.
    No result from this function represents provider, account, deployment,
    AI authorization, sandbox, production, or live-trading evidence.
    """

    root = source_root or _source_root()
    records = [
        _artifact_record(root, name, relative_path, artifact_type)
        for name, relative_path, artifact_type in artifact_specs
    ]
    status, reason_code = _bundle_status(records)
    generated_at = _datetime.datetime.now(_datetime.timezone.utc).isoformat()
    digest = _bundle_digest(records)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "config_schema_version": 4,
        "evidence_kind": EVIDENCE_KIND,
        "baseline_id": BASELINE_ID,
        "evidence_id": "iteration41-local-" + digest[:16],
        "generated_at": generated_at,
        "repository": {
            "logical_path": ".",
            "commit": None,
            "wheel_sha256": None,
            "source_dirty_manifest": None,
            "identity_status": "NOT_COLLECTED_NO_GIT_OR_WHEEL_PROCESS",
        },
        "FR_ids": [],
        "NFR_ids": [],
        "WP_ids": ["WP41-A", "WP41-H"],
        "AC_id": None,
        "test_node_id": None,
        "fixture_id": None,
        "stage": "local_metadata_collection",
        "runtime_id": None,
        "mode": None,
        "preset": None,
        "preset_registry_version": None,
        "config_seal_digest": None,
        "effective_order_route": None,
        "effective_account_access": None,
        "effective_plugins": [],
        "profile": "offline_metadata_only",
        "platform": platform.platform(),
        "interpreter": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "expected": (
            "all code-owned local metadata artifacts parse; any code-owned JUnit artifact "
            "listed by the collector reports nonzero passing testcases"
        ),
        "actual": {
            "artifact_count": len(records),
            "pass_count": sum(1 for record in records if record["status"] == "PASS"),
            "not_run_count": sum(1 for record in records if record["status"] == "NOT_RUN"),
            "fail_count": sum(1 for record in records if record["status"] == "FAIL"),
        },
        "network_attempt_count": 0,
        "fake_dispatch_count": 0,
        "external_provider_write_count": 0,
        "external_sandbox_write_count": 0,
        "external_production_write_count": 0,
        "status": status,
        "reason_code": reason_code,
        "command": ["bt-runtime", "collect-evidence"],
        "exit_code": 0 if status == "PASS" else 2,
        "artifact_refs": records,
        "reviewer_role": None,
        "expires_at": None,
        "evidence_boundary": EVIDENCE_BOUNDARY,
        "limitations": [
            "The collector reads code-owned local metadata only and never executes a test or command.",
            "It does not inspect config.yaml, credentials, provider state, account state, network traffic, or runtime dispatch.",
            "PASS means only local structural collection succeeded; it never grants deployment, execution, control, sandbox, production, or live admission.",
            "Git commit, wheel, and dirty-worktree provenance remain NOT_COLLECTED until a separate reviewed release collector records them.",
        ],
    }


__all__ = [
    "BASELINE_ID",
    "DEFAULT_ARTIFACT_SPECS",
    "EVIDENCE_BOUNDARY",
    "EVIDENCE_KIND",
    "EVIDENCE_SCHEMA_VERSION",
    "EvidenceCollectionError",
    "collect_iteration41_evidence",
]
