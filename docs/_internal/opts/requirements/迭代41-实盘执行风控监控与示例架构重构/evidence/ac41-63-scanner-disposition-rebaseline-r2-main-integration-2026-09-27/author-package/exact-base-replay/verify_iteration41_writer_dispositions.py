"""Verify the review disposition checklist for Iteration 41 write candidates.

This tool is deliberately static: it imports only the AST inventory collector,
reads source text and JSON, and never imports a runtime, provider, SDK, or
strategy.  A passing result proves that every currently discovered candidate
has an accountable review record.  It does not prove reachability, zero I/O,
or an admitted live route.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "iteration41.writer-disposition-checklist.v1"
CHECKLIST_STATUS = "REVIEW_REQUIRED"
CHECKLIST_CLOSURE_STATUS = "NOT_CLOSED_STATIC_REVIEW_REQUIRED"
DEFAULT_EVIDENCE_REF = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/"
    "evidence/live-execution-inventory-candidates.json"
)
CHECKLIST_TEST_NODE = (
    "tests/unit/scripts/test_verify_iteration41_writer_dispositions.py::"
    "test_checked_in_disposition_checklist_covers_current_inventory"
)
UNRESOLVED_LIVE_ROUTE = "UNRESOLVED_POTENTIAL_LIVE_WRITE"
STATIC_TRACE_DISPOSITION = "STATIC_AST_CANDIDATE_NO_RUNTIME_TRACE"
REQUIRED_ENTRY_FIELDS = (
    "candidate_id",
    "candidate",
    "owner",
    "route",
    "test_node",
    "trace_evidence_disposition",
    "evidence_ref",
    "disposition",
    "availability",
)
LOCATOR_FIELDS = (
    "kind",
    "path",
    "class_name",
    "function_name",
    "call",
    "method",
    "dynamic_reason",
    "ordinal",
)
ALLOWED_DISPOSITIONS = frozenset(
    ("REVIEW_REQUIRED", "NO_EXTERNAL_WRITE", "LIVE_NO_GO", "NOT_APPLICABLE")
)
ALLOWED_AVAILABILITY = frozenset(("NOT_AVAILABLE", "REPLAY_ONLY", "AVAILABLE"))


class DispositionChecklistError(ValueError):
    """A deterministic reason code for an invalid local disposition checklist."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _load_inventory_collector():
    """Load the static collector without importing Backtrader runtime code."""

    script_path = Path(__file__).with_name("collect_iteration41_writer_inventory.py")
    spec = importlib.util.spec_from_file_location("_iteration41_writer_inventory", script_path)
    if spec is None or spec.loader is None:  # pragma: no cover - filesystem invariant
        raise DispositionChecklistError("writer_inventory_collector_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _semantic_locator(candidate: Mapping[str, object]) -> Dict[str, object]:
    """Return identity fields that survive a line-only source edit."""

    return {
        "kind": candidate.get("kind"),
        "path": candidate.get("path"),
        "class_name": candidate.get("class_name"),
        "function_name": candidate.get("function_name"),
        "call": candidate.get("call"),
        "method": candidate.get("method"),
        "dynamic_reason": candidate.get("dynamic_reason"),
    }


def _sort_key(candidate: Mapping[str, object]) -> Tuple[str, int, int, str, str]:
    return (
        str(candidate.get("path") or ""),
        int(candidate.get("line") or 0),
        int(candidate.get("column") or 0),
        str(candidate.get("kind") or ""),
        str(candidate.get("call") or ""),
    )


def candidate_records(inventory: Mapping[str, object]) -> List[Dict[str, object]]:
    """Derive stable candidate IDs from the current static discovery result."""

    raw_candidates: List[Mapping[str, object]] = []
    for field in ("writer_candidates", "dynamic_execution_candidates"):
        values = inventory.get(field)
        if not isinstance(values, list):
            raise DispositionChecklistError("inventory_candidates_invalid")
        for value in values:
            if not isinstance(value, Mapping):
                raise DispositionChecklistError("inventory_candidate_invalid")
            raw_candidates.append(value)

    counters: Dict[str, int] = {}
    records: List[Dict[str, object]] = []
    for candidate in sorted(raw_candidates, key=_sort_key):
        locator = _semantic_locator(candidate)
        semantic_key = _canonical_json(locator)
        ordinal = counters.get(semantic_key, 0)
        counters[semantic_key] = ordinal + 1
        locator["ordinal"] = ordinal
        digest = hashlib.sha256(_canonical_json(locator).encode("ascii")).hexdigest()
        records.append(
            {
                "candidate_id": "i41-writer-" + digest[:20],
                "candidate": {
                    **locator,
                    "line": candidate.get("line"),
                    "column": candidate.get("column"),
                },
            }
        )
    return records


def _records_digest(records: Iterable[Mapping[str, object]]) -> str:
    payload = [str(record["candidate_id"]) for record in records]
    return hashlib.sha256(_canonical_json(payload).encode("ascii")).hexdigest()


def _default_owner(path: object) -> str:
    normalized = str(path or "")
    if normalized.startswith("backtrader_runtime/"):
        return "runtime-maintainers"
    if normalized.startswith(("backtrader/stores/", "backtrader/brokers/")):
        return "core-execution-maintainers"
    if normalized.startswith(("examples/007_ctp/", "examples/010_live_examples/")):
        return "legacy-ctp-runtime-maintainers"
    if normalized.startswith("examples/"):
        return "example-runtime-maintainers"
    return "iteration41-writer-inventory-review"


def build_review_required_checklist(inventory: Mapping[str, object]) -> Dict[str, object]:
    """Create the conservative checked-in starting point for human disposition.

    New or changed candidates are deliberately not silently accepted: callers
    must regenerate this skeleton and then review each record before changing
    its route or availability.
    """

    records = candidate_records(inventory)
    counts = inventory.get("counts")
    if not isinstance(counts, Mapping):
        raise DispositionChecklistError("inventory_counts_invalid")
    entries = []
    for record in records:
        candidate = record["candidate"]
        assert isinstance(candidate, Mapping)  # local construction invariant
        entries.append(
            {
                "candidate_id": record["candidate_id"],
                "candidate": dict(candidate),
                "owner": _default_owner(candidate.get("path")),
                "route": UNRESOLVED_LIVE_ROUTE,
                "test_node": CHECKLIST_TEST_NODE,
                "trace_evidence_disposition": STATIC_TRACE_DISPOSITION,
                "evidence_ref": DEFAULT_EVIDENCE_REF,
                "disposition": "REVIEW_REQUIRED",
                "availability": "NOT_AVAILABLE",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": CHECKLIST_STATUS,
        "closure_status": CHECKLIST_CLOSURE_STATUS,
        "source_inventory_schema_version": inventory.get("schema_version"),
        "source_inventory_counts": dict(counts),
        "source_inventory_candidate_digest": _records_digest(records),
        "historical_ctp_candidate_scopes": inventory.get("historical_ctp_candidate_scopes", []),
        "entries": entries,
        "limitations": [
            "Each record is a static AST candidate, not reachability or provider-I/O proof.",
            "All current candidates remain REVIEW_REQUIRED and NOT_AVAILABLE for live use.",
            "A passing checklist verifier does not grant replay, sandbox, production, or live admission.",
        ],
    }


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _candidate_id_list(value: object, expected_count: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == expected_count
        and all(_nonempty_string(candidate_id) for candidate_id in value)
    )


def _route_is_live(route: str) -> bool:
    normalized = route.upper()
    return "LIVE" in normalized or "POTENTIAL_LIVE" in normalized


def validate_disposition_checklist(
    inventory: Mapping[str, object], checklist: Mapping[str, object]
) -> Dict[str, object]:
    """Validate complete, conservative dispositions for current candidates."""

    reasons: List[str] = []
    if checklist.get("schema_version") != SCHEMA_VERSION:
        reasons.append("checklist_schema_version_invalid")
    if checklist.get("status") != CHECKLIST_STATUS:
        reasons.append("checklist_status_must_remain_review_required")
    if checklist.get("closure_status") != CHECKLIST_CLOSURE_STATUS:
        reasons.append("checklist_closure_status_invalid")
    if checklist.get("source_inventory_schema_version") != inventory.get("schema_version"):
        reasons.append("checklist_inventory_schema_mismatch")

    try:
        records = candidate_records(inventory)
    except DispositionChecklistError as error:
        reasons.append(error.reason_code)
        records = []
    expected_by_id = {str(record["candidate_id"]): record for record in records}
    counts = inventory.get("counts")
    if checklist.get("source_inventory_counts") != counts:
        reasons.append("checklist_inventory_counts_mismatch")
    if checklist.get("source_inventory_candidate_digest") != _records_digest(records):
        reasons.append("checklist_inventory_digest_mismatch")
    if checklist.get("historical_ctp_candidate_scopes") != inventory.get(
        "historical_ctp_candidate_scopes", []
    ):
        reasons.append("checklist_historical_scope_notes_mismatch")

    entries = checklist.get("entries")
    if not isinstance(entries, list):
        reasons.append("checklist_entries_invalid")
        entries = []

    actual_by_id: Dict[str, Mapping[str, object]] = {}
    for index, entry in enumerate(entries):
        label = str(index)
        if not isinstance(entry, Mapping):
            reasons.append("checklist_entry_invalid:" + label)
            continue
        missing_fields = [field for field in REQUIRED_ENTRY_FIELDS if field not in entry]
        if missing_fields:
            reasons.append("checklist_entry_missing_fields:" + label)
            continue
        candidate_id = entry.get("candidate_id")
        if not _nonempty_string(candidate_id):
            reasons.append("checklist_candidate_id_invalid:" + label)
            continue
        candidate_id = str(candidate_id)
        if candidate_id in actual_by_id:
            reasons.append("checklist_candidate_duplicate:" + candidate_id)
            continue
        actual_by_id[candidate_id] = entry

        for field in (
            "owner",
            "route",
            "test_node",
            "trace_evidence_disposition",
            "evidence_ref",
            "disposition",
            "availability",
        ):
            if not _nonempty_string(entry.get(field)):
                reasons.append("checklist_field_invalid:{0}:{1}".format(candidate_id, field))

        disposition = entry.get("disposition")
        availability = entry.get("availability")
        route = str(entry.get("route") or "")
        if disposition not in ALLOWED_DISPOSITIONS:
            reasons.append("checklist_disposition_invalid:" + candidate_id)
        if availability not in ALLOWED_AVAILABILITY:
            reasons.append("checklist_availability_invalid:" + candidate_id)
        if (
            entry.get("trace_evidence_disposition") == STATIC_TRACE_DISPOSITION
            and disposition != "REVIEW_REQUIRED"
        ):
            reasons.append("static_trace_candidate_not_review_required:" + candidate_id)
        if "UNRESOLVED" in route.upper() and disposition != "REVIEW_REQUIRED":
            reasons.append("unresolved_candidate_not_review_required:" + candidate_id)
        if disposition == "REVIEW_REQUIRED" and availability != "NOT_AVAILABLE":
            reasons.append("review_required_candidate_marked_available:" + candidate_id)
        if _route_is_live(route) and (
            disposition not in {"REVIEW_REQUIRED", "LIVE_NO_GO"}
            or availability != "NOT_AVAILABLE"
        ):
            reasons.append("live_candidate_marked_available:" + candidate_id)

        expected = expected_by_id.get(candidate_id)
        if expected is not None:
            candidate = entry.get("candidate")
            if not isinstance(candidate, Mapping):
                reasons.append("checklist_candidate_locator_invalid:" + candidate_id)
            else:
                expected_locator = expected["candidate"]
                assert isinstance(expected_locator, Mapping)  # local construction invariant
                for field in LOCATOR_FIELDS:
                    if candidate.get(field) != expected_locator.get(field):
                        reasons.append("checklist_candidate_locator_mismatch:" + candidate_id)
                        break

    archived = checklist.get("historical_tombstones", [])
    archived_by_id: dict[str, Mapping[str, object]] = {}
    if not isinstance(archived, list):
        reasons.append("checklist_historical_tombstones_invalid")
        archived = []
    for index, entry in enumerate(archived):
        label = str(index)
        if not isinstance(entry, Mapping):
            reasons.append("historical_tombstone_invalid:" + label)
            continue
        missing_fields = [field for field in REQUIRED_ENTRY_FIELDS if field not in entry]
        if missing_fields:
            reasons.append("historical_tombstone_missing_fields:" + label)
            continue
        candidate_id = entry.get("candidate_id")
        if not _nonempty_string(candidate_id):
            reasons.append("historical_tombstone_id_invalid:" + label)
            continue
        candidate_id = str(candidate_id)
        if candidate_id in archived_by_id:
            reasons.append("historical_tombstone_duplicate:" + candidate_id)
            continue
        archived_by_id[candidate_id] = entry
        if candidate_id in expected_by_id or candidate_id in actual_by_id:
            reasons.append("historical_tombstone_is_current_candidate:" + candidate_id)
        if (
            entry.get("disposition") != "REVIEW_REQUIRED"
            or entry.get("availability") != "NOT_AVAILABLE"
            or entry.get("route") != UNRESOLVED_LIVE_ROUTE
        ):
            reasons.append("historical_tombstone_not_conservative:" + candidate_id)

    lineage = checklist.get("tombstone_lineage", [])
    if archived_by_id:
        if not isinstance(lineage, list):
            reasons.append("checklist_tombstone_lineage_invalid")
        else:
            lineage_ids = [
                str(row.get("candidate_id"))
                for row in lineage
                if isinstance(row, Mapping) and _nonempty_string(row.get("candidate_id"))
            ]
            if len(lineage_ids) != len(lineage) or set(lineage_ids) != set(archived_by_id):
                reasons.append("checklist_tombstone_lineage_mismatch")

    preservation = checklist.get("baseline_preservation")
    preservation_required = len(expected_by_id) >= 445 or any(
        key in checklist
        for key in ("baseline_preservation", "historical_tombstones", "tombstone_lineage")
    )
    if preservation_required or preservation is not None:
        if not isinstance(preservation, Mapping):
            reasons.append("checklist_baseline_preservation_invalid")
        else:
            historical_by_id = dict(actual_by_id)
            historical_by_id.update(archived_by_id)
            baseline_ids = preservation.get("baseline_candidate_ids_in_order")
            if not _candidate_id_list(baseline_ids, 389):
                reasons.append("checklist_baseline_389_ids_invalid")
                baseline_ids = []
            elif len(set(baseline_ids)) != 389:
                reasons.append("checklist_baseline_389_ids_duplicate")
            baseline_rows = [historical_by_id.get(value) for value in baseline_ids]
            if any(row is None for row in baseline_rows):
                reasons.append("checklist_baseline_389_record_missing")
            else:
                baseline_hash = hashlib.sha256(
                    json.dumps(
                        baseline_rows,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()
                if baseline_hash.upper() != preservation.get("baseline_disposition_payload_sha256"):
                    reasons.append("checklist_baseline_389_payload_mismatch")
                if _records_digest([{"candidate_id": value} for value in baseline_ids]) != (
                    "e482c7b95050c4573e10d0ee46829470877936cdd9f87f228772f82cf0327f7e"
                ):
                    reasons.append("checklist_baseline_389_id_digest_mismatch")
            previous_ids = preservation.get("previous_445_candidate_ids_in_order")
            previous_ids_valid = _candidate_id_list(previous_ids, 445)
            if not previous_ids_valid:
                reasons.append("checklist_previous_445_ids_invalid")
            else:
                if len(set(previous_ids)) != 445:
                    reasons.append("checklist_previous_445_ids_duplicate")
                previous_rows = [historical_by_id.get(value) for value in previous_ids]
                if any(row is None for row in previous_rows):
                    reasons.append("checklist_previous_445_record_missing")
                else:
                    previous_hash = hashlib.sha256(
                        json.dumps(
                            previous_rows,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                    ).hexdigest()
                    if previous_hash.upper() != preservation.get(
                        "previous_445_disposition_payload_sha256"
                    ):
                        reasons.append("checklist_previous_445_payload_mismatch")
            removed_ids = preservation.get("removed_to_historical_tombstones")
            if not _candidate_id_list(removed_ids, len(archived_by_id)):
                reasons.append("checklist_tombstone_archive_ids_invalid")
            elif len(set(removed_ids)) != len(removed_ids):
                reasons.append("checklist_tombstone_archive_ids_duplicate")
            elif set(removed_ids) != set(archived_by_id):
                reasons.append("checklist_tombstone_archive_id_mismatch")
            new_ids = preservation.get("new_g6_candidate_ids")
            if not _candidate_id_list(new_ids, 21):
                reasons.append("checklist_new_g6_candidate_ids_invalid")
            elif len(set(new_ids)) != len(new_ids):
                reasons.append("checklist_new_g6_candidate_ids_duplicate")
            elif previous_ids_valid and set(new_ids) != (set(expected_by_id) - set(previous_ids)):
                reasons.append("checklist_new_g6_candidate_ids_mismatch")

    for candidate_id in sorted(set(expected_by_id) - set(actual_by_id)):
        reasons.append("candidate_disposition_missing:" + candidate_id)
    for candidate_id in sorted(set(actual_by_id) - set(expected_by_id)):
        reasons.append("candidate_disposition_unexpected:" + candidate_id)

    reasons = sorted(set(reasons))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not reasons else "REJECTED",
        "reason_codes": reasons,
        "discovered_candidate_count": len(records),
        "checklist_entry_count": len(entries),
        "historical_tombstone_count": len(archived_by_id),
        "review_required_count": sum(
            1
            for entry in actual_by_id.values()
            if entry.get("disposition") == "REVIEW_REQUIRED"
        ),
        "live_route_count": sum(
            1 for entry in actual_by_id.values() if _route_is_live(str(entry.get("route") or ""))
        ),
        "evidence_boundary": "STATIC_DISPOSITION_INTEGRITY_ONLY_NOT_LIVE_ADMISSION",
    }


def _load_json(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise DispositionChecklistError("disposition_checklist_unreadable") from error
    if not isinstance(value, Mapping):
        raise DispositionChecklistError("disposition_checklist_invalid")
    return value


def _write_json_atomically(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".iteration41-writer-dispositions-", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="verify Iteration 41 static writer candidate dispositions without runtime imports"
    )
    parser.add_argument("--source-root", required=True, type=Path)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--checklist", type=Path)
    target.add_argument("--write-review-required-checklist", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        collector = _load_inventory_collector()
        inventory = collector.collect_inventory(args.source_root)
        if args.write_review_required_checklist is not None:
            checklist = build_review_required_checklist(inventory)
            _write_json_atomically(args.write_review_required_checklist, checklist)
            result = validate_disposition_checklist(inventory, checklist)
            result["output"] = str(args.write_review_required_checklist)
            result["status"] = "GENERATED_REVIEW_REQUIRED"
        else:
            checklist = _load_json(args.checklist)
            result = validate_disposition_checklist(inventory, checklist)
    except DispositionChecklistError as error:
        print(json.dumps({"status": "REJECTED", "reason_codes": [error.reason_code]}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"PASS", "GENERATED_REVIEW_REQUIRED"} else 2


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI contract.
    raise SystemExit(main())
