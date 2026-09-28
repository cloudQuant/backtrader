from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_STORE = ROOT / "input-sources" / "btapistore.py"
PATCH = ROOT / "r1-apply.patch"
TARGETS = (
    ("backtrader/stores/btapistore.py", "a25edc57d4a4ac225b1b152a2672ff2b108b3c497cef05cd46a8fb22c1e586b8"),
    ("backtrader/stores/ctp_account_actor_port.py", "19f5935bc6aabcde178f60f62619757b01fa51b99ff5389120a8404e00e70372"),
    (
        "tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py",
        "b04100bac2cd4fba6c132d3cfb44e18fa6e40a0896e602aa276a69b2daebb12c",
    ),
)
BASE_SHA256 = "dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str], cwd: Path, *, expect_success: bool = True) -> None:
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print("$", " ".join(args))
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if expect_success and result.returncode:
        raise SystemExit(result.returncode)
    if not expect_success and result.returncode == 0:
        raise SystemExit("command unexpectedly succeeded")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", required=True, type=Path)
    args = parser.parse_args()
    out_root = args.out_root.resolve()
    if out_root.exists():
        raise SystemExit(f"refusing to overwrite existing replay directory: {out_root}")
    if sha256(BASE_STORE) != BASE_SHA256:
        raise SystemExit("base Store hash mismatch")
    out_root.mkdir(parents=True)
    print("base_store_sha256=", sha256(BASE_STORE))
    print("patch_sha256=", sha256(PATCH))
    for autocrlf in ("false", "true"):
        work = out_root / f"autocrlf-{autocrlf}"
        store = work / TARGETS[0][0]
        store.parent.mkdir(parents=True)
        store.write_bytes(BASE_STORE.read_bytes())
        run(["git", "init", "-q"], work)
        run(["git", "config", "core.autocrlf", autocrlf], work)
        run(["git", "config", "user.name", "QA Replay"], work)
        run(["git", "config", "user.email", "qa@example.invalid"], work)
        run(["git", "add", TARGETS[0][0]], work)
        run(["git", "commit", "-q", "-m", "exact input Store snapshot"], work)
        run(["git", "-c", f"core.autocrlf={autocrlf}", "apply", "--check", "--ignore-whitespace", "--whitespace=nowarn", str(PATCH)], work)
        run(["git", "-c", f"core.autocrlf={autocrlf}", "apply", "--ignore-whitespace", "--whitespace=nowarn", str(PATCH)], work)
        exact = []
        normalized = []
        for rel, expected_sha in TARGETS:
            path = work / Path(rel)
            actual_sha = sha256(path)
            same = actual_sha == expected_sha
            text_same = path.read_text(encoding="utf-8") == (ROOT / Path(rel)).read_text(encoding="utf-8")
            exact.append(same)
            normalized.append(text_same)
            print(f"autocrlf={autocrlf} path={rel} bytes={path.stat().st_size} sha256={actual_sha} exact={same} normalized_text_equal={text_same}")
        if autocrlf == "false" and not all(exact):
            raise SystemExit("core.autocrlf=false replay did not reproduce all exact target hashes")
        if autocrlf == "true" and (not exact[0] or not all(normalized)):
            raise SystemExit("core.autocrlf=true replay changed Store or source text")
    print("PATCH_REPLAY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
