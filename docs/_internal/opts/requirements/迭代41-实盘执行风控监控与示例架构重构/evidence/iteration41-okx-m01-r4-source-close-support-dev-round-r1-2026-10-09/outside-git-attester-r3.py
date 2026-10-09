"""Root outside-host attestation with fixed Git executable and explicit environment."""

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path("D:/source_code/backtrader")
HEAD = "716ca992dd8a05d7d997d25cd667f212eae5bb1c"
GIT = Path("C:/Program Files/Git/cmd/git.exe")
HELPER = ROOT / ".codex-tmp/okx_m01_r7_r4_source_scope_normal_close_root_20261009.py"
DRIVER = ROOT / ".codex-tmp/okx_m01_r7_r4_root_actual_r2_20261009.py"
EVIDENCE = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
OUTPUT = ROOT / (EVIDENCE + "iteration41-okx-m01-r7-five-module-root-gate-actual-r4-2026-10-09")
NONCE_HASH = "e847f0a6bf7d58b5b5e7ee262636900ff8fe674523a5610efa70c9c66249d949"
MAP_HASH = "468b1d5981951d16f08d294dee5d22e15c9728a9134a9be1c458074fde221e7b"
OLD_PIN = (2556, "2db029f905d6f413b6762f1271fb7dd8ef3a8703879b2caed6562d64d7311227")


def literals(path):
    result = {}
    for node in ast.parse(path.read_bytes()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    result[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
    return result


def git_state():
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    if not GIT.is_file() or set(key for key in env if key.startswith("GIT_")) != {"GIT_OPTIONAL_LOCKS"}:
        raise RuntimeError("fixed_git_environment_invalid")
    observations = []
    for operation in (["branch", "--show-current"], ["rev-parse", "HEAD"], ["diff", "--cached", "--name-only"]):
        command = [str(GIT), "-C", str(ROOT), "-c", "core.fsmonitor=false", *operation]
        proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, check=True)
        if proc.stderr:
            raise RuntimeError("git_stderr_not_empty")
        observations.append(proc.stdout.decode("utf-8"))
    if observations != ["dev\n", HEAD + "\n", ""]:
        raise RuntimeError("current_git_state_changed")
    return {"branch": "dev", "head": HEAD, "index_empty": True}


def main():
    value = literals(HELPER)
    driver = literals(DRIVER)
    rows = []
    for name, path, pin in [
        ("root_driver", value["DRIVER_REL"], value["DRIVER_PIN"]),
        ("caller", value["CALLER_REL"], value["CALLER_PIN"]),
        ("caller_test", value["CALLER_TEST_REL"], value["CALLER_TEST_PIN"]),
        ("cuv2_snapshot", value["CUV2_SNAPSHOT_REL"], value["CUV2_PIN"]),
        ("observation", value["OBSERVATION_REL"], value["OBSERVATION_PIN"]),
        ("candidate_manifest", EVIDENCE + "iteration41-okx-m01-r7-five-module-root-gate-preparation-r2-2026-10-09/candidate-pins.json", value["MANIFEST_PIN"]),
        ("caller_review", driver["R4_REVIEW_RELATIVE"], value["REVIEW_PIN"]),
    ]:
        raw = (ROOT / path).read_bytes()
        if (len(raw), hashlib.sha256(raw).hexdigest()) != tuple(pin):
            raise RuntimeError("public_source_pin_changed")
        rows.append({"name": name, "path": path, "bytes": pin[0], "sha256": pin[1]})
    observation = json.loads((ROOT / value["OBSERVATION_REL"]).read_bytes())
    if observation["root_nonce_sha256"] != NONCE_HASH:
        raise RuntimeError("public_nonce_binding_changed")
    receipt = {
        "schema": "iteration41.okx.m01.r7.r4.source-close-outside-git.v1",
        "phase": "before_source_close",
        "observer": "root_outside_host",
        "host_id": 77310,
        "repo_root": str(ROOT),
        "root_nonce_sha256": NONCE_HASH,
        "git": git_state(),
        "commands": ["git branch --show-current", "git rev-parse HEAD", "git diff --cached --name-only"],
        "source_pins": rows,
        "held_pin_map_sha256": MAP_HASH,
    }
    raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    if len(raw) > 16384:
        raise RuntimeError("attestation_size_limit")
    path = OUTPUT / "root-git-attestation-before-close.json"
    backup = OUTPUT / "root-git-attestation-before-close-r2-preserved.json"
    old = path.read_bytes()
    if (len(old), hashlib.sha256(old).hexdigest()) != OLD_PIN or backup.exists() or path.is_symlink():
        raise RuntimeError("prior_attestation_preservation_binding_invalid")
    path.rename(backup)
    with path.open("xb") as file:
        file.write(raw)
    print(json.dumps({"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git": receipt["git"], "prior_attestation_preserved": True, "git_environment_explicit": True, "git_fsmonitor_disabled": True}, sort_keys=True))


if __name__ == "__main__":
    main()
