from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_FILES = {
    "backtrader/stores/btapistore.py": ROOT / "input-sources/btapistore.py",
    "tests/unit/stores/test_managed_ctp_store_adapter.py": Path(
        r"D:\source_code\backtrader\tests\unit\stores\test_managed_ctp_store_adapter.py"
    ),
}
EXPECTED_BASE_HASHES = {
    "backtrader/stores/btapistore.py": "dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826",
    "tests/unit/stores/test_managed_ctp_store_adapter.py": "2b5f929cac960ed6a7105eb2cc0b7401961fdb7c7b97761288d279b415b15e3f",
}
TARGET_FILES = (
    "backtrader/stores/btapistore.py",
    "backtrader/stores/ctp_account_actor_port.py",
    "tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py",
    "tests/unit/stores/test_managed_ctp_store_adapter.py",
    "tests/unit/stores/test_ctp_non_authorizing_contracts.py",
)
PATCH = ROOT / "r2b-main-base-apply.patch"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str], *, cwd: Path) -> bytes:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout or b""


def main_base_tree() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="iter41-r2b-main-base-"))
    for relative, source in BASE_FILES.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        actual = sha256(target)
        if actual != EXPECTED_BASE_HASHES[relative]:
            raise RuntimeError(f"main-base hash mismatch for {relative}: {actual}")
    run(["git", "init", "-q"], cwd=repo)
    run(["git", "config", "core.autocrlf", "false"], cwd=repo)
    run(["git", "config", "user.name", "Candidate Freeze"], cwd=repo)
    run(["git", "config", "user.email", "candidate-freeze@example.invalid"], cwd=repo)
    run(["git", "add", "-A"], cwd=repo)
    run(["git", "commit", "-qm", "exact main-base selected inputs"], cwd=repo)
    return repo


repo = main_base_tree()
for relative in TARGET_FILES:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / relative, target)
run(["git", "add", "-A"], cwd=repo)
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
        cwd=repo,
    )
)

replay = main_base_tree()
run(["git", "apply", "--check", str(PATCH)], cwd=replay)
run(["git", "apply", str(PATCH)], cwd=replay)
for relative in TARGET_FILES:
    candidate_hash = sha256(ROOT / relative)
    replay_hash = sha256(replay / relative)
    if candidate_hash != replay_hash:
        raise RuntimeError(f"main-base patch replay hash mismatch: {relative}")
    print(f"{relative}_sha256={candidate_hash}")
print(f"main_base_store_sha256={EXPECTED_BASE_HASHES['backtrader/stores/btapistore.py']}")
print(f"patch_sha256={sha256(PATCH)}")
print(f"patch_bytes={PATCH.stat().st_size}")
print("main_base_git_apply_check=PASS")
print("main_base_patch_replay=PASS")
print("core.autocrlf=false")
