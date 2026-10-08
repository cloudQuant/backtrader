"""Read-only Root verification of the accepted R4 source QA input closure."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess

ROOT = Path("D:/source_code/backtrader")
HEAD = "16d49d3ee40f9628ae461a38117201e90ee1483d"
QA_HEAD = "9617fb3280d92edd1eae0198877d9438fd8cce5c"
INVENTORY = ".codex-tmp/optional16_r4_delivery_inventory_draft.json"
INVENTORY_PIN = (39962, "1c4a0900a32eb1c692efef9181a4cff090eab78aa9a07ccb58641403b1af5933")
QA = ".codex-tmp/optional16_r4_sourcefake_guarded_r2/sourcefake-a037a1075326-6fc0d48af8e846f1970cc64a660b7105.json"
QA_PIN = (68351, "cb366f766fdcf0bed400bd892acf82a5395e143c22e63d425d5068cb45814ff7")
OUT = ROOT / ".codex-tmp/optional16_r4_root_delivery_precheck_r2_20261009.json"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args, allowed=(0,)):
    result = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args], cwd=ROOT,
        capture_output=True, check=False,
    )
    assert result.returncode in allowed, (args, result.returncode)
    return result.returncode, result.stdout


def public_bytes(relative, pin):
    assert type(relative) is str and not Path(relative).is_absolute()
    assert not relative.lower().endswith((".env", "config.yaml", ".exe", ".dll"))
    target = ROOT / relative
    assert target.resolve(strict=True).is_relative_to(ROOT)
    metadata = target.lstat()
    assert stat.S_ISREG(metadata.st_mode)
    assert not (getattr(metadata, "st_file_attributes", 0) & 0x400)
    assert 0 < metadata.st_size <= 8 * 1024 * 1024
    with target.open("rb") as stream:
        raw = stream.read(metadata.st_size + 1)
    assert (len(raw), sha(raw)) == pin, relative
    return raw


assert git("branch", "--show-current")[1].rstrip(b"\r\n") == b"dev"
assert git("rev-parse", "HEAD")[1].rstrip(b"\r\n").decode() == HEAD
assert not git("diff", "--cached", "--name-only", "-z")[1]
inventory = json.loads(public_bytes(INVENTORY, INVENTORY_PIN))
qa = json.loads(public_bytes(QA, QA_PIN))
assert qa["status"] == "SOURCEFAKE_QA_PASSED"
assert qa["pytest_exit_code"] == 0
assert qa["collected_tests"] == qa["passed_call_reports"] == 47
assert qa["skipped_reports"] == qa["failure_reports"] == 0
assert qa["actual_root_call"] is False
assert qa["historical_run_assignment_identity_proven"] is False
assert qa["pre_git"]["head"] == qa["post_git"]["head"] == QA_HEAD
assert qa["pre_git"] == qa["post_git"]
assert qa["pins"] == qa["post_pins"]
assert len(inventory["files"]) == len(qa["pins"]) == 51

rows = []
for row in inventory["files"]:
    relative = row["path"]
    pin = (row["bytes"], row["sha256"])
    current = public_bytes(relative, pin)
    qa_row = qa["pins"][relative]
    assert (qa_row["bytes"], qa_row["sha256"]) == pin
    tracked_rc, _ = git("ls-files", "--error-unmatch", "--", relative, allowed=(0, 1))
    status = git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", relative)[1]
    if tracked_rc == 0:
        assert not status, relative
        committed = git("show", "HEAD:" + relative)[1]
        if committed == current:
            state = "clean_inherited_head"
        else:
            assert relative == "tests/__init__.py"
            assert committed == b'"""Backtrader test suite."""\n'
            assert current == b'"""Backtrader test suite."""\r\n'
            state = "accepted_checkout_requires_exact_byte_preservation"
    else:
        assert status == b"?? " + relative.encode("utf-8") + b"\0", (relative, status)
        state = "untracked_required_input"
    rows.append({
        "path": relative, "bytes": pin[0], "sha256": pin[1],
        "current_state": state, "draft_state": row["state"],
        "classification_changed": (state != "untracked_required_input") != (row["state"] == "clean_head"),
        "head_blob_bytes": len(committed) if tracked_rc == 0 else None,
        "head_blob_sha256": sha(committed) if tracked_rc == 0 else None,
        "role": row["role"],
    })

assert git("rev-parse", "HEAD")[1].rstrip(b"\r\n").decode() == HEAD
assert not git("diff", "--cached", "--name-only", "-z")[1]
result = {
    "schema": "iteration41.optional16.r4.root_delivery_precheck.v2",
    "status": "ALL_51_ACCEPTED_SOURCE_QA_INPUT_PINS_MATCH",
    "repository": str(ROOT), "branch": "dev", "delivery_head": HEAD,
    "executed_source_qa_head": QA_HEAD, "source_qa_repeated": False,
    "clean_inherited_head_count": sum(r["current_state"] == "clean_inherited_head" for r in rows),
    "untracked_required_input_count": sum(r["current_state"] == "untracked_required_input" for r in rows),
    "draft_classification_corrections": sum(r["classification_changed"] for r in rows),
    "byte_preservation_member_count": sum(r["current_state"] == "accepted_checkout_requires_exact_byte_preservation" for r in rows),
    "rows": rows, "actual_reconciliation_invoked": False,
    "retained_host_state_checked": False, "formal_optional16_pass_count": 0,
    "historical_run_assignment_identity_proven": False,
}
assert result["clean_inherited_head_count"] == 22
assert result["byte_preservation_member_count"] == 1
assert result["untracked_required_input_count"] == 28
assert result["draft_classification_corrections"] == 9
with OUT.open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False))
