from __future__ import annotations
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "backtrader/stores/btapistore.py": (ROOT / "input-sources/r2/backtrader-stores-btapistore.py", ROOT / "backtrader/stores/btapistore.py"),
    "tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py": (ROOT / "input-sources/r2/test-ctp-account-actor-store-wiring-candidate.py", ROOT / "tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py"),
}
repo = Path(tempfile.mkdtemp(prefix="iter41-r2a-patch-"))
for relative, (base, _) in FILES.items():
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base, target)
subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=repo, check=True)
subprocess.run(["git", "config", "user.name", "QA Freeze"], cwd=repo, check=True)
subprocess.run(["git", "config", "user.email", "qa-freeze@example.invalid"], cwd=repo, check=True)
subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
subprocess.run(["git", "commit", "-qm", "frozen r2 baseline"], cwd=repo, check=True)
for relative, (_, candidate) in FILES.items():
    shutil.copyfile(candidate, repo / relative)
subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
diff = subprocess.run(["git", "diff", "--cached", "--binary", "--full-index", "--no-ext-diff", "--no-renames", "HEAD"], cwd=repo, check=True, stdout=subprocess.PIPE).stdout
PATCH = ROOT / "r2a-apply.patch"
PATCH.write_bytes(diff)
h = hashlib.sha256(PATCH.read_bytes()).hexdigest()
print(f"patch_sha256={h}")
print(f"patch_bytes={PATCH.stat().st_size}")
