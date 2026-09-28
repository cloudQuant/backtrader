from __future__ import annotations
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "r2a-apply.patch"
FILES = {
    "backtrader/stores/btapistore.py": (ROOT / "input-sources/r2/backtrader-stores-btapistore.py", ROOT / "backtrader/stores/btapistore.py"),
    "tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py": (ROOT / "input-sources/r2/test-ctp-account-actor-store-wiring-candidate.py", ROOT / "tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py"),
}
def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
repo = Path(tempfile.mkdtemp(prefix="iter41-r2a-replay-"))
for relative, (base, _) in FILES.items():
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base, target)
subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo, check=True)
subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
subprocess.run(["git", "-c", "user.name=QA", "-c", "user.email=qa@example.invalid", "commit", "-qm", "frozen r2 base"], cwd=repo, check=True)
subprocess.run(["git", "apply", "--check", str(PATCH)], cwd=repo, check=True)
subprocess.run(["git", "apply", str(PATCH)], cwd=repo, check=True)
lines = [f"patch_sha256={sha(PATCH)}", f"core.autocrlf=false scratch={repo}"]
for relative, (_, candidate) in FILES.items():
    actual = sha(repo / relative)
    expected = sha(candidate)
    lines.append(f"{relative} sha256={actual} expected={expected}")
    if actual != expected:
        raise SystemExit(f"exact replay mismatch for {relative}")
lines.append("R2A_PATCH_REPLAY_PASS")
(ROOT / "evidence/r2a-patch-replay.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
