#!/usr/bin/env python
"""Build the deterministic Iteration 42 tracker from pinned public sources only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

SEED_SCHEMA = "iteration42-public-status-v2"
OUTPUT_SCHEMA = "iteration42-public-tracker-v3"
SOURCE_POLICY = "FIXED_HASH_PINNED_PUBLIC_RECORDS_ONLY"
SEED_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代42-示例策略模拟盘贯通与四件套标准化/evidence/iteration42-public-status.json"
)
OUTPUT_RELATIVE = (
    "docs/_internal/opts/requirements/"
    "迭代42-示例策略模拟盘贯通与四件套标准化/evidence"
)
JSON_NAME = "iteration42-example-tracker.json"
MARKDOWN_NAME = "iteration42-example-tracker.md"
EXAMPLE_IDS = (
    "012_1_midfreq_cross_exchange",
    "012_2_event_driven_cross_exchange",
    "013_1_midfreq_cross_arbitrage",
    "013_2_highfreq_calendar_arbitrage",
    "013_3_sa_midfreq_simnow",
    "014_1_ctp_options_lowfreq",
    "014_2_ctp_options_midfreq",
    "015_ctp_options_highfreq",
)
CURRENT_PATHS = {name: "examples/unified/" + name for name in EXAMPLE_IDS}
REQ42 = "docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/"
REQ43 = "docs/_internal/opts/requirements/迭代43-examples目录三类重构与config选层/"
REFERENCE_PATHS = {
    "audit_md": REQ42 + "evidence/acceptance-audit-2026-10-12.md",
    "audit_json": REQ42 + "evidence/acceptance-audit-2026-10-12.json",
    "r1_progress": REQ42 + "evidence/r1-live-run-progress-2026-10-10.md",
    "r2_acceptance": REQ42 + "evidence/r2-acceptance-record-2026-10-10.md",
    "r3_acceptance": REQ42 + "evidence/r3-acceptance-record-2026-10-10.md",
    "r4_record": REQ42 + "evidence/r4-implementation-and-smoke-record-2026-10-10.md",
    "r5_record": REQ42 + "evidence/r5-implementation-record-2026-10-10.md",
    "r6_record": REQ42 + "evidence/r6-0141-strict-live-adapter-2026-10-10.md",
    "r7_record": REQ42 + "evidence/r7-0142-observation-tier-2026-10-10.md",
    "r8_record": REQ42 + "evidence/r8-015-observation-tier-2026-10-10.md",
    "r9_checklist": REQ42 + "evidence/r9-acceptance-audit-checklist-2026-10-10.md",
    "monday_plan": REQ42 + "evidence/monday-live-run-plan-2026-10-12.md",
    "i43_plan": REQ43 + "迭代计划.md",
    "i43_relocation": REQ43 + "evidence/r2-unified-relocation-2026-10-11.md",
    "i43_manifest_qa": REQ42 + "evidence/repair-i42manifeste-2026-10-12/result.json",
    "i43_binding_review": REQ42 + "evidence/source-binding-review-2026-10-12.json",
    "approval_policy": "examples/_support/strategy_candidate_approval.py",
    "approval_trust_root": "examples/_support/demo-approval-trust-root.pem",
}
REFERENCE_IDS = tuple(REFERENCE_PATHS)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^live-[A-Za-z0-9T-]+$")
REPARSE_ATTRIBUTE = 0x400
ATTEMPT_STATUSES = {
    "MECHANICAL_DEMO_SMOKE_PASS", "PASS", "FAIL", "BLOCKED", "OBSERVATION_PASS"
}
CAPABILITY_STATUSES = {
    "BLOCKED", "PARTIAL", "HISTORICAL_PASS_ONLY", "UNACCEPTED_FAIL", "OBSERVATION_ONLY",
    "SOURCE_BINDING_REPAIRED_QUALIFICATION_NOT_ACCEPTED"
}
REPLAY_STATUSES = {"FORMULA_CHECK_PASS", "LOCAL_REPLAY_PASS"}


class TrackerInputError(ValueError):
    """Invalid seed schema, path, or public source pin."""


def _unique_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrackerInputError("duplicate JSON key")
        result[key] = value
    return result


def _keys(value: Any, expected: Iterable[str], where: str) -> None:
    if type(value) is not dict:
        raise TrackerInputError(where + " must be an object")
    wanted, actual = set(expected), set(value)
    if wanted != actual:
        raise TrackerInputError(
            "{} keys mismatch (missing={}, unknown={})".format(
                where, sorted(wanted - actual), sorted(actual - wanted)
            )
        )


def _text(value: Any, where: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise TrackerInputError(where + " must be a non-empty trimmed string")
    return value


def _safe_path(value: Any, expected: str, where: str, allow_directory: bool = False) -> str:
    path = _text(value, where)
    if "\\" in path or path.startswith("/") or ":" in path:
        raise TrackerInputError(where + " must be a repository-relative POSIX path")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise TrackerInputError(where + " has an unsafe path component")
    if path != expected:
        raise TrackerInputError(where + " is outside the fixed public path allowlist")
    if not allow_directory and PurePosixPath(path).suffix not in {".md", ".json", ".py", ".pem"}:
        raise TrackerInputError(where + " has an unsupported file type")
    return path


def _ref_ids(value: Any, known: set, where: str) -> List[str]:
    if type(value) is not list or not value:
        raise TrackerInputError(where + " must be a non-empty list")
    if any(type(item) is not str or item not in known for item in value):
        raise TrackerInputError(where + " contains an unknown reference")
    if len(set(value)) != len(value):
        raise TrackerInputError(where + " contains a duplicate reference")
    return list(value)


def _attempt(value: Any, where: str, known: set) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    _keys(value, {"status", "run_id", "tier", "summary", "reference_ids"}, where)
    if type(value["status"]) is not str or value["status"] not in ATTEMPT_STATUSES:
        raise TrackerInputError(where + " has an unknown attempt status")
    run_id = value["run_id"]
    if run_id is not None and (type(run_id) is not str or not RUN_ID_RE.fullmatch(run_id)):
        raise TrackerInputError(where + " has an invalid sanitized run id")
    if value["tier"] is not None:
        _text(value["tier"], where + ".tier")
    _text(value["summary"], where + ".summary")
    _ref_ids(value["reference_ids"], known, where + ".reference_ids")
    return value


def validate_seed(seed: Any) -> Dict[str, Any]:
    """Reject unknown schemas, fields, rows, evidence paths, and ref identities."""
    _keys(
        seed,
        {"schema", "source_policy", "audit_snapshot", "schedule_state",
         "source_references", "examples", "formal_account_pass_delta"},
        "seed",
    )
    if seed["schema"] != SEED_SCHEMA:
        raise TrackerInputError("unknown public status schema")
    if seed["source_policy"] != SOURCE_POLICY:
        raise TrackerInputError("unsupported source policy")
    if type(seed["formal_account_pass_delta"]) is not int or seed["formal_account_pass_delta"] != 0:
        raise TrackerInputError("this source/doc review cannot add a formal account PASS")

    audit = seed["audit_snapshot"]
    _keys(
        audit,
        {"audit_date", "reviewed_head", "branch", "conclusion", "scope",
         "markdown_reference_id", "structured_reference_id"},
        "audit_snapshot",
    )
    if audit["audit_date"] != "2026-10-12":
        raise TrackerInputError("audit date differs from the pinned audit")
    if type(audit["reviewed_head"]) is not str or not re.fullmatch(
        r"[0-9a-f]{40}", audit["reviewed_head"]
    ):
        raise TrackerInputError("reviewed_head must be a historical commit id")
    for key in ("branch", "conclusion", "scope"):
        _text(audit[key], "audit_snapshot." + key)
    if (audit["branch"], audit["conclusion"]) != ("dev", "PARTIAL_NOT_COMPLETE"):
        raise TrackerInputError("unsupported audit conclusion")
    if audit["markdown_reference_id"] != "audit_md":
        raise TrackerInputError("audit Markdown reference is invalid")
    if audit["structured_reference_id"] != "audit_json":
        raise TrackerInputError("audit JSON reference is invalid")

    schedule = seed["schedule_state"]
    _keys(schedule, {"status", "cancelled_date", "summary", "reference_ids"}, "schedule_state")
    if (schedule["status"], schedule["cancelled_date"]) != ("CANCELLED", "2026-10-11"):
        raise TrackerInputError("the superseded Monday schedule must remain cancelled")
    _text(schedule["summary"], "schedule_state.summary")

    refs = seed["source_references"]
    if type(refs) is not list or len(refs) != len(REFERENCE_IDS):
        raise TrackerInputError("public reference catalog has the wrong size")
    refs_by_id: Dict[str, Dict[str, Any]] = {}
    for index, ref in enumerate(refs):
        where = "source_references[{}]".format(index)
        _keys(ref, {"id", "path", "sha256", "locator", "claim_scope"}, where)
        ref_id = ref["id"]
        if ref_id != REFERENCE_IDS[index]:
            raise TrackerInputError(where + " has unknown or out-of-order reference id")
        _safe_path(ref["path"], REFERENCE_PATHS[ref_id], where + ".path")
        if type(ref["sha256"]) is not str or not SHA256_RE.fullmatch(ref["sha256"]):
            raise TrackerInputError(where + ".sha256 must be lowercase SHA-256")
        _text(ref["locator"], where + ".locator")
        _text(ref["claim_scope"], where + ".claim_scope")
        refs_by_id[ref_id] = ref
    known = set(REFERENCE_IDS)

    rows = seed["examples"]
    if type(rows) is not list or len(rows) != len(EXAMPLE_IDS):
        raise TrackerInputError("seed must contain exactly eight rows")
    used = {"audit_md", "audit_json"}
    used.update(_ref_ids(schedule["reference_ids"], known, "schedule_state.reference_ids"))
    for index, row in enumerate(rows):
        where = "examples[{}]".format(index)
        _keys(
            row,
            {"id", "current_path", "dry_replay", "historical_best",
             "latest_known_attempt", "current_capability", "admission_bounds"},
            where,
        )
        example_id = EXAMPLE_IDS[index]
        if row["id"] != example_id:
            raise TrackerInputError(where + " does not match fixed example order")
        _safe_path(
            row["current_path"], CURRENT_PATHS[example_id],
            where + ".current_path", allow_directory=True,
        )

        offline = row["dry_replay"]
        _keys(offline, {"dry", "replay", "reference_ids"}, where + ".dry_replay")
        if (
            offline["dry"] != "DRY"
            or type(offline["replay"]) is not str
            or offline["replay"] not in REPLAY_STATUSES
        ):
            raise TrackerInputError(where + " has an unsupported offline status")
        used.update(_ref_ids(offline["reference_ids"], known, where + ".dry_replay.refs"))

        best = _attempt(row["historical_best"], where + ".historical_best", known)
        latest = _attempt(row["latest_known_attempt"], where + ".latest_known_attempt", known)
        if latest is None:
            raise TrackerInputError(where + " must record its latest known attempt")
        if best is not None:
            used.update(best["reference_ids"])
        used.update(latest["reference_ids"])

        capability = row["current_capability"]
        _keys(capability, {"status", "as_of", "summary", "reference_ids"},
              where + ".current_capability")
        if (
            type(capability["status"]) is not str
            or capability["status"] not in CAPABILITY_STATUSES
        ):
            raise TrackerInputError(where + " has an unknown current capability status")
        if capability["as_of"] != audit["audit_date"]:
            raise TrackerInputError(where + " capability must be audit-dated")
        if example_id in {"012_1_midfreq_cross_exchange", "012_2_event_driven_cross_exchange"}:
            required_cap_refs = {"i43_manifest_qa", "i43_binding_review"}
            if capability["status"] != "SOURCE_BINDING_REPAIRED_QUALIFICATION_NOT_ACCEPTED":
                raise TrackerInputError(where + " overstates the accepted source-only capability")
            if not required_cap_refs.issubset(set(capability["reference_ids"])):
                raise TrackerInputError(where + " omits post-43 source evidence")
            if "qualification-v3.json" not in capability["summary"] or "no live 012 invocation was reverified" not in capability["summary"].lower():
                raise TrackerInputError(where + " omits qualification or live-verification boundary")
        _text(capability["summary"], where + ".current_capability.summary")
        used.update(_ref_ids(capability["reference_ids"], known, where + ".current.refs"))

        bounds = row["admission_bounds"]
        _keys(
            bounds,
            {"research_status", "hft_status", "approval_status", "signature_boundary",
             "reference_ids"},
            where + ".admission_bounds",
        )
        for key in ("research_status", "hft_status", "approval_status", "signature_boundary"):
            _text(bounds[key], where + ".admission_bounds." + key)
        if example_id in {
            "012_1_midfreq_cross_exchange",
            "012_2_event_driven_cross_exchange",
        }:
            expected_hft = (
                "NOT_APPLICABLE_TO_MIDFREQ"
                if example_id == "012_1_midfreq_cross_exchange"
                else "HFT_FAILED/NOT_ADMITTED"
            )
            if (
                bounds["research_status"] != "RESEARCH_REJECTED"
                or bounds["hft_status"] != expected_hft
                or bounds["approval_status"] != "NOT_APPROVED"
            ):
                raise TrackerInputError(
                    where + " changes a fixed 012 research, HFT, or approval boundary"
                )
        expected_latest = {
            "013_3_sa_midfreq_simnow": "FAIL",
            "014_1_ctp_options_lowfreq": "BLOCKED",
            "014_2_ctp_options_midfreq": "BLOCKED",
        }.get(example_id)
        if expected_latest is not None and latest["status"] != expected_latest:
            raise TrackerInputError(where + " overwrites the latest known blocked result")
        used.update(_ref_ids(bounds["reference_ids"], known, where + ".admission.refs"))

    if used != known:
        raise TrackerInputError("public reference catalog contains unused entries")
    return seed


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & REPARSE_ATTRIBUTE
    )


def _checked_public_path(repo_root: Path, relative_path: str, final_is_directory: bool) -> Path:
    path = Path(repo_root)
    parts = relative_path.split("/")
    for index, part in enumerate(parts):
        path = path / part
        try:
            info = os.lstat(str(path))
        except OSError as exc:
            raise TrackerInputError("pinned public file is unavailable") from exc
        if _is_reparse(info):
            raise TrackerInputError("pinned public path contains a reparse point")
        final = index == len(parts) - 1
        valid_type = stat.S_ISDIR if (not final or final_is_directory) else stat.S_ISREG
        if not valid_type(info.st_mode):
            raise TrackerInputError("pinned public path has an invalid component")
    return path


def _checked_public_file(repo_root: Path, relative_path: str) -> Path:
    return _checked_public_path(repo_root, relative_path, final_is_directory=False)


def _checked_public_directory(repo_root: Path, relative_path: str) -> Path:
    return _checked_public_path(repo_root, relative_path, final_is_directory=True)


def verify_public_references(
    repo_root: Path, seed: Mapping[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """Verify each fixed public file by path and SHA-256 without discovery scans."""
    refs_by_id = {ref["id"]: ref for ref in seed["source_references"]}
    for ref_id in REFERENCE_IDS:
        ref = refs_by_id[ref_id]
        path = _checked_public_file(repo_root, ref["path"])
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise TrackerInputError("pinned public source could not be read") from exc
        if digest != ref["sha256"]:
            raise TrackerInputError("public source hash mismatch: " + ref_id)
    for row in seed["examples"]:
        _checked_public_directory(repo_root, row["current_path"])
    return refs_by_id


def _expand(ids: Iterable[str], refs: Mapping[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    fields = ("id", "path", "sha256", "locator", "claim_scope")
    return [{key: refs[item][key] for key in fields} for item in ids]


def _expand_attempt(
    attempt: Optional[Mapping[str, Any]], refs: Mapping[str, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if attempt is None:
        return None
    return {
        "status": attempt["status"], "run_id": attempt["run_id"],
        "tier": attempt["tier"], "summary": attempt["summary"],
        "evidence": _expand(attempt["reference_ids"], refs),
    }


def _build_payload(seed: Mapping[str, Any], seed_sha256: str) -> Dict[str, Any]:
    refs = {ref["id"]: ref for ref in seed["source_references"]}
    audit, schedule = seed["audit_snapshot"], seed["schedule_state"]
    examples = []
    for row in seed["examples"]:
        offline, cap, bounds = row["dry_replay"], row["current_capability"], row["admission_bounds"]
        examples.append({
            "id": row["id"], "current_path": row["current_path"],
            "dry_replay": {
                "dry": offline["dry"], "replay": offline["replay"],
                "evidence": _expand(offline["reference_ids"], refs),
            },
            "historical_best": _expand_attempt(row["historical_best"], refs),
            "latest_known_attempt": _expand_attempt(row["latest_known_attempt"], refs),
            "current_capability": {
                "status": cap["status"], "as_of": cap["as_of"],
                "summary": cap["summary"], "evidence": _expand(cap["reference_ids"], refs),
            },
            "admission_bounds": {
                "research_status": bounds["research_status"],
                "hft_status": bounds["hft_status"],
                "approval_status": bounds["approval_status"],
                "signature_boundary": bounds["signature_boundary"],
                "evidence": _expand(bounds["reference_ids"], refs),
            },
        })
    return {
        "schema": OUTPUT_SCHEMA,
        "source_policy": SOURCE_POLICY,
        "formal_account_pass_delta": seed["formal_account_pass_delta"],
        "status_source": {"path": SEED_RELATIVE, "sha256": seed_sha256},
        "audit_snapshot": {
            "audit_date": audit["audit_date"], "reviewed_head": audit["reviewed_head"],
            "branch": audit["branch"], "conclusion": audit["conclusion"],
            "scope": audit["scope"],
            "evidence": _expand(
                [audit["markdown_reference_id"], audit["structured_reference_id"]], refs
            ),
        },
        "schedule_state": {
            "status": schedule["status"], "cancelled_date": schedule["cancelled_date"],
            "summary": schedule["summary"], "evidence": _expand(schedule["reference_ids"], refs),
        },
        "public_references": _expand(REFERENCE_IDS, refs),
        "examples": examples,
    }


def load_seed_bytes(raw: bytes) -> Tuple[Dict[str, Any], bytes]:
    if type(raw) is not bytes:
        raise TrackerInputError("public status seed must be bytes")
    try:
        seed = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrackerInputError("public status seed could not be parsed") from exc
    return validate_seed(seed), raw


def load_seed(repo_root: Path) -> Tuple[Dict[str, Any], bytes]:
    path = _checked_public_file(repo_root, SEED_RELATIVE)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise TrackerInputError("public status seed could not be read") from exc
    return load_seed_bytes(raw)


def build_tracker(
    repo_root: Optional[Path] = None, seed_bytes: Optional[bytes] = None
) -> Dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
    root = root.resolve(strict=True)
    if seed_bytes is None:
        seed, raw = load_seed(root)
    else:
        seed, raw = load_seed_bytes(seed_bytes)
    verify_public_references(root, seed)
    return _build_payload(seed, hashlib.sha256(raw).hexdigest())


def render_json(tracker: Mapping[str, Any]) -> bytes:
    return (json.dumps(tracker, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _cell(value: Any) -> str:
    text = "none recorded" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _attempt_cell(attempt: Optional[Mapping[str, Any]]) -> str:
    if attempt is None:
        return "none recorded"
    return "{} ({}, {})".format(
        attempt["status"], attempt.get("tier") or "tier not stated",
        attempt.get("run_id") or "run id not stated",
    )


def render_markdown(tracker: Mapping[str, Any]) -> bytes:
    audit = tracker["audit_snapshot"]
    lines = [
        "# Iteration 42 public example status tracker", "",
        "This deterministic snapshot uses fixed, hash-pinned public records. It does not scan",
        "live-evidence directories or read ignored captures.", "",
        "Source policy: {}. This reports fixed path/hash verification, not Git tracking status.".format(
            tracker["source_policy"]
        ),
        "Formal account PASS delta in this review: {}.".format(
            tracker["formal_account_pass_delta"]
        ),
        "Audit snapshot: {} | branch {} | reviewed HEAD {} | {}.".format(
            audit["audit_date"], audit["branch"], audit["reviewed_head"], audit["conclusion"]
        ),
        "The reviewed HEAD is historical provenance, not a current-checkout pin.",
        "Public seed SHA-256: {}.".format(tracker["status_source"]["sha256"]),
        "Superseded schedule: {} on {}. {}.".format(
            tracker["schedule_state"]["status"], tracker["schedule_state"]["cancelled_date"],
            tracker["schedule_state"]["summary"],
        ), "",
        "| Example | Current path | Dry | Replay | Historical best | Latest known attempt | Current capability |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in tracker["examples"]:
        lines.append("| {} | {} | {} | {} | {} | {} | {}: {} |".format(
            _cell(row["id"]), _cell(row["current_path"]),
            _cell(row["dry_replay"]["dry"]), _cell(row["dry_replay"]["replay"]),
            _cell(_attempt_cell(row["historical_best"])),
            _cell(_attempt_cell(row["latest_known_attempt"])),
            _cell(row["current_capability"]["status"]),
            _cell(row["current_capability"]["summary"]),
        ))
    lines.extend([
        "", "## Boundaries and public evidence", "",
        "Historical best, latest known attempt, and audit-date capability are independent fields. A latest BLOCKED result remains BLOCKED even when an earlier historical result passed. This tracker grants no runner, strategy, or write authority.", "",
    ])
    for row in tracker["examples"]:
        bounds = row["admission_bounds"]
        lines.extend([
            "### " + row["id"], "",
            "- Admission labels: research={}, HFT={}, approval={}.".format(
                bounds["research_status"], bounds["hft_status"], bounds["approval_status"]
            ),
            "- Signature boundary: " + bounds["signature_boundary"],
            "- Current capability as of {}: {} — {}.".format(
                row["current_capability"]["as_of"], row["current_capability"]["status"],
                row["current_capability"]["summary"],
            ),
        ])
        evidence_groups = (
            ("offline", row["dry_replay"]["evidence"]),
            ("historical best", (row["historical_best"] or {}).get("evidence", [])),
            ("latest known attempt", row["latest_known_attempt"]["evidence"]),
            ("current capability", row["current_capability"]["evidence"]),
            ("admission boundary", bounds["evidence"]),
        )
        for label, evidence in evidence_groups:
            if evidence:
                lines.append("- " + label + " evidence:")
                for ref in evidence:
                    lines.append("  - {} — {}#{} — SHA-256 {} — {}".format(
                        ref["id"], ref["path"], ref["locator"], ref["sha256"], ref["claim_scope"]
                    ))
        lines.append("")
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        raise TrackerInputError("the public tracker generator accepts no path overrides")
    root = Path(__file__).resolve().parents[1].resolve(strict=True)
    tracker = build_tracker(root)
    json_bytes, markdown_bytes = render_json(tracker), render_markdown(tracker)
    out = _checked_public_directory(root, OUTPUT_RELATIVE)
    json_path, markdown_path = out / JSON_NAME, out / MARKDOWN_NAME
    for path in (json_path, markdown_path):
        try:
            info = os.lstat(str(path))
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise TrackerInputError("tracker output path could not be inspected") from exc
        if _is_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise TrackerInputError("tracker output path is not a regular public file")
    json_path.write_bytes(json_bytes)
    markdown_path.write_bytes(markdown_bytes)
    print(json.dumps({
        "json": str(json_path),
        "json_sha256": hashlib.sha256(json_bytes).hexdigest(),
        "markdown": str(markdown_path),
        "markdown_sha256": hashlib.sha256(markdown_bytes).hexdigest(),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
