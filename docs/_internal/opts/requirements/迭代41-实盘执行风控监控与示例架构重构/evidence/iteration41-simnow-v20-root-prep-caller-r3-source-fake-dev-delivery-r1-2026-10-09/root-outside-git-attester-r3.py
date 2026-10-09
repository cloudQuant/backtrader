"""Root-only public-input and Git metadata attestation; does not run a candidate."""
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT = Path("D:/source_code/backtrader")
GIT = "C:/Program Files/Git/cmd/git.exe"
EXPECTED_HEAD = "313b057b7304f5bf443152648a397f71b0a2b463"
EXPECTED_PARENT = "a17c49d19efbed72c61225c77ae42e4e51050281"
PREFIX = ".codex-tmp/simnow_r3_root_source_qa_r3_20261009_outside_"
CAP = 2097152


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def pin(raw):
    return [len(raw), hashlib.sha256(raw).hexdigest()]


def read_public(relative):
    require(type(relative) is str and "\\" not in relative and ":" not in relative, "public_relative_path")
    parts = PurePosixPath(relative).parts
    require(type(relative) is str and parts and not PurePosixPath(relative).is_absolute()
            and ".." not in parts and ".env" not in parts
            and not any(p in ("config.yaml", "secrets.yaml") for p in parts), "public_path")
    path = Path("\\\\?\\" + str(ROOT.joinpath(*parts)))
    resolved = path.resolve(strict=True)
    fixed_root = Path("\\\\?\\" + str(ROOT)).resolve(strict=True)
    require(fixed_root in resolved.parents, "public_containment")
    for ancestor in (path, *path.parents):
        if ancestor == fixed_root:
            break
        require(not ancestor.is_symlink()
                and not (getattr(ancestor.lstat(), "st_file_attributes", 0) & 0x400), "public_reparse")
    require(not path.is_symlink() and path.stat().st_size <= CAP, "public_file")
    with path.open("rb") as stream:
        raw = stream.read(CAP + 1)
    require(len(raw) <= CAP, "public_cap")
    return raw


def git(*args):
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run([GIT, "--no-optional-locks", "-c", "core.fsmonitor=false", *args],
                          cwd=ROOT, env=environment, check=True, capture_output=True).stdout


def snapshot(harness, harness_pin):
    actual_root = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve(strict=True)
    index_path = Path(git("rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip()).resolve(strict=True)
    require(actual_root == ROOT.resolve(strict=True)
            and index_path == (ROOT / ".git/index").resolve(strict=True), "fixed_git_paths")
    raw = read_public(harness)
    require(pin(raw) == harness_pin, "harness_pin")
    values = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.endswith(("_RELATIVE", "_PIN")):
                values[name] = ast.literal_eval(node.value)
    specs = {}
    for base in ("CALLER", "TEST", "PREPARATION", "PRECHECK", "CORE_CALLER", "MANIFEST"):
        specs[values[base + "_RELATIVE"]] = list(values[base + "_PIN"])
    manifest = json.loads(read_public(values["MANIFEST_RELATIVE"]))
    require(len(manifest["public_source_rows"]) == 26, "manifest_rows")
    for row in manifest["public_source_rows"]:
        require(row["path"] not in specs, "duplicate_public_input")
        specs[row["path"]] = [row["bytes"], row["sha256"]]
    require(len(specs) == 32, "public_input_count")
    for path, expected in specs.items():
        require(pin(read_public(path)) == expected, "public_input_pin")
    require(git("branch", "--show-current").decode().strip() == "dev", "branch")
    head = git("rev-parse", "HEAD").decode().strip()
    parent = git("rev-parse", "HEAD^").decode().strip()
    require(head == EXPECTED_HEAD and parent == EXPECTED_PARENT, "head_parent")
    require(not git("diff", "--cached", "--name-only", "-z"), "index_not_empty")
    return {"head": head, "parent": parent, "branch": "dev", "harness": harness,
            "harness_pin": harness_pin, "public_input_pins": specs,
            "raw_index_pin": pin((ROOT / ".git/index").read_bytes()),
            "tracked_status_pin": pin(git("status", "--porcelain=v1", "-z", "--untracked-files=no")),
            "tracked_diff_pin": pin(git("diff", "--binary", "--no-ext-diff", "--no-textconv")),
            "input_status_pin": pin(git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *specs))}


require(len(sys.argv) == 5 and sys.argv[1] in ("pre", "post"), "arguments")
mode, harness, size, digest = sys.argv[1:]
harness_pin = [int(size), digest]
current = snapshot(harness, harness_pin)
target = ROOT / (PREFIX + mode + ".json")
require(not target.exists(), "receipt_freshness")
if mode == "post":
    previous = json.loads(read_public(PREFIX + "pre.json"))
    require(previous["snapshot"] == current, "git_or_public_inputs_changed")
record = {"schema": "iteration41.simnow.r3.root.outside.source.qa.attestation.v1",
          "status": "PASS_PUBLIC_INPUT_AND_GIT_METADATA_ONLY", "mode": mode,
          "snapshot": current, "candidate_executed_by_attester": False,
          "retained_host_state_checked": False, "provider_or_account_action": False}
with target.open("xb") as stream:
    stream.write((json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
print(json.dumps({"status": record["status"], "mode": mode,
                  "public_inputs": len(current["public_input_pins"]), "receipt_pin": pin(target.read_bytes())}))
