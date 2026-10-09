"""Outside-host Git postverification after the one normal R4 CUv2 close."""

import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path("D:/source_code/backtrader")
E = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
OUT = E / "iteration41-okx-m01-r7-five-module-root-gate-actual-r4-2026-10-09"
ATTESTER = ROOT / ".codex-tmp/okx_m01_r4_outside_git_attestation_root_r3_20261009.py"
ATTESTER_PIN = (4832, "fc7fd837124c799d82d3085a2e95a337da7230dc6d3dcc0fc72906826a82d281")


def pin(path):
    raw = path.read_bytes()
    return (len(raw), hashlib.sha256(raw).hexdigest())


def main():
    if pin(ATTESTER) != ATTESTER_PIN:
        raise RuntimeError("outside_attester_changed")
    before_path = OUT / "root-git-attestation-before-close.json"
    if pin(before_path) != (2556, "2db029f905d6f413b6762f1271fb7dd8ef3a8703879b2caed6562d64d7311227"):
        raise RuntimeError("pre_attestation_changed")
    before = json.loads(before_path.read_bytes())
    close_path = OUT / "source-close-root.json"
    close = json.loads(close_path.read_bytes())
    if not (
        close["status"] == "SOURCE_SCOPE_NORMAL_CLOSE_RETURNED"
        and close["normal_postverify_and_close"] is True
        and close["generator_closed"] is True
        and close["original_reference_and_result_preserved"] is True
        and close["retained_python_row_preserved"] is True
        and close["public_pins_rechecked_by_close_helper"] == 31
        and close["software_pins_rechecked_by_original_cuv2_normal_exit"] == 3
        and close["outside_git_pre_attestation_sha256"] == pin(before_path)[1]
        and close["host_exit_permitted_by_this_receipt"] is False
        and close["gate_result_status"] == "OUTPUT_MISMATCH"
        and close["formal_m01_pass_count"] == 0
    ):
        raise RuntimeError("normal_close_observation_not_exact")
    ns = runpy.run_path(str(ATTESTER), run_name="_root_r4_outside_git_postverify")
    after = ns["git_state"]()
    if after != before["git"] or pin(ATTESTER) != ATTESTER_PIN:
        raise RuntimeError("outside_git_postverification_failed")
    for row in before["source_pins"]:
        if pin(ROOT / row["path"]) != (row["bytes"], row["sha256"]):
            raise RuntimeError("outside_public_source_pin_changed")
    result = {
        "schema": "iteration41.okx.m01.r7.r4.source-close-outside-git-post.v1",
        "phase": "after_source_close",
        "observer": "root_outside_host",
        "host_id": 77310,
        "git_pre_post_equal": True,
        "git": after,
        "git_environment_explicit": True,
        "git_fsmonitor_disabled": True,
        "pre_attestation_pin": pin(before_path),
        "source_close_observation_pin": pin(close_path),
        "attester_pin": ATTESTER_PIN,
        "public_context_pins_checked": 7,
        "host_state_checked_by_this_postverification": False,
        "formal_m01_pass_count": 0,
    }
    raw = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    path = OUT / "root-git-attestation-after-close.json"
    with path.open("xb") as file:
        file.write(raw)
    print(json.dumps({"status": "OUTSIDE_GIT_POSTVERIFICATION_MATCHED", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "source_close_observation_pin": pin(close_path), "git": after}, sort_keys=True))


if __name__ == "__main__":
    main()
