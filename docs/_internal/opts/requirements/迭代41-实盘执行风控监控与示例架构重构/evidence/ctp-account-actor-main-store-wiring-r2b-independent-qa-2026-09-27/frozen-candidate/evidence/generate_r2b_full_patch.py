from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_FILES = {
    "backtrader/stores/btapistore.py": ROOT
    / "input-sources/r2/backtrader-stores-btapistore.py",
    "tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py": ROOT
    / "input-sources/r2/test-ctp-account-actor-store-wiring-candidate.py",
    "tests/unit/stores/test_managed_ctp_store_adapter.py": Path(
        r"D:\source_code\backtrader\tests\unit\stores\test_managed_ctp_store_adapter.py"
    ),
}
BASE_MANAGED_CTP_SHA256 = "2b5f929cac960ed6a7105eb2cc0b7401961fdb7c7b97761288d279b415b15e3f"
R2_ACTOR_MODULE_SHA256 = "2e4b04d00c45ba9c6524c5ad0364273e6ecc1a1f653f595d21c3891be2644ee3"
CHANGED_FILES = (
    "backtrader/stores/btapistore.py",
    "tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py",
    "tests/unit/stores/test_managed_ctp_store_adapter.py",
    "tests/unit/stores/test_ctp_non_authorizing_contracts.py",
)
PATCH = ROOT / "r2b-apply.patch"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str], *, cwd: Path, output=None) -> bytes:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE if output is None else output,
        stderr=subprocess.STDOUT,
    )
    return result.stdout or b""


def baseline_tree() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="iter41-r2b-exact-r2a-base-"))
    for relative, source in BASE_FILES.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    actor_module = ROOT / "backtrader/stores/ctp_account_actor_port.py"
    if sha256(actor_module) != R2_ACTOR_MODULE_SHA256:
        raise RuntimeError("R2 actor module no longer matches the frozen parent identity")
    actor_target = repo / "backtrader/stores/ctp_account_actor_port.py"
    actor_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(actor_module, actor_target)
    if sha256(repo / "tests/unit/stores/test_managed_ctp_store_adapter.py") != (
        BASE_MANAGED_CTP_SHA256
    ):
        raise RuntimeError("frozen R2a managed CTP test base hash mismatch")
    run(["git", "init", "-q"], cwd=repo)
    run(["git", "config", "core.autocrlf", "false"], cwd=repo)
    run(["git", "config", "user.name", "Candidate Freeze"], cwd=repo)
    run(["git", "config", "user.email", "candidate-freeze@example.invalid"], cwd=repo)
    run(["git", "add", "-A"], cwd=repo)
    run(["git", "commit", "-qm", "exact main-base selected inputs"], cwd=repo)
    run(["git", "apply", str(ROOT / "r2a-apply.patch")], cwd=repo)
    run(["git", "add", "-A"], cwd=repo)
    run(["git", "commit", "-qm", "frozen R2a parent"], cwd=repo)
    return repo


baseline = baseline_tree()
for relative in CHANGED_FILES:
    candidate = ROOT / relative
    target = baseline / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, target)
run(["git", "add", "-A"], cwd=baseline)
PATCH.write_bytes(
    run(
        [
            "git",
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--no-renames",
            "HEAD",
        ],
        cwd=baseline,
    )
)

replay = baseline_tree()
run(["git", "apply", "--check", str(PATCH)], cwd=replay)
run(["git", "apply", str(PATCH)], cwd=replay)
for relative in CHANGED_FILES:
    candidate_hash = sha256(ROOT / relative)
    replay_hash = sha256(replay / relative)
    if candidate_hash != replay_hash:
        raise RuntimeError(f"patch replay hash mismatch: {relative}")
    print(f"{relative}_sha256={candidate_hash}")
print(f"r2b_parent_manifest_sha256={sha256(ROOT / 'evidence/candidate-manifest.json')}")
print(f"patch_sha256={sha256(PATCH)}")
print(f"patch_bytes={PATCH.stat().st_size}")
print("exact_r2a_patch_replay=PASS")
print("core.autocrlf=false")
