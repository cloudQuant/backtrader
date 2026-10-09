"""One focused fake-OS QA; candidate operations cannot reach private/native I/O."""
from __future__ import annotations

import ast
import ctypes
from ctypes import wintypes
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import types
import xml.etree.ElementTree

ROOT = Path("D:/source_code/backtrader")
EVIDENCE = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
PACKET = EVIDENCE + "iteration41-okx-m01-v3-protected-rebind-r2-source-candidate-r1-2026-10-09/"
REVIEW = EVIDENCE + "iteration41-okx-m01-v3-protected-rebind-r2-require-binding-independent-review-r1-2026-10-09/review.md"
TEST = "tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r2.py"
HELPER = "scripts/iteration41_okx_m01_v3_protected_rebind_r2.py"
RESULT = ROOT / ".codex-tmp/okx_m01_rebind_r2_root_source_qa_r2_20261009.json"
EXPECTED = {
    HELPER: (28418, "0baa2191b8d5b99b42e7a13ddc217f0d90291db8279b20f74a3d92c676649810"),
    TEST: (23557, "4268d340cae45dbcf7574c38f98f2546df78f9a7ff82049f0baecad2904b5eea"),
    PACKET + "candidate-pins.json": (2165, "dad69ff22275926d824b895a60b59995ecd7e8659f223c88d852cb01a6394043"),
    REVIEW: (1834, "fe530a9e8323a5ee492c1d7b1fc80028423df70ad5fd032143ce1790c965f2d4"),
}

def public_bytes(relative):
    path = ROOT / relative
    extended = Path(chr(92) * 2 + "?" + chr(92) + str(path.absolute()))
    data = extended.read_bytes()
    if len(data) > 2 * 1024 * 1024:
        raise RuntimeError("public_source_too_large")
    return data

def pin(relative, data):
    return {"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

if RESULT.exists():
    raise RuntimeError("fresh_result_required")
# The independent review and exact candidate pins are checked before imports.
for relative, (size, digest) in EXPECTED.items():
    data = public_bytes(relative)
    if (len(data), hashlib.sha256(data).hexdigest()) != (size, digest):
        raise RuntimeError("fixed_input_pin_mismatch: " + relative)
manifest = json.loads(public_bytes(PACKET + "candidate-pins.json"))
for row in manifest["candidate_files"] + manifest["source_dependencies"]:
    relative = PACKET + row["path"] if row["path"] == "README.md" else row["path"]
    EXPECTED[relative] = (row["bytes"], row["sha256"])
map_relative = manifest["source_dependencies"][0]["path"]
source_map = json.loads(public_bytes(map_relative))
for relative, digest in source_map["source_pins"].items():
    EXPECTED[relative] = (len(public_bytes(relative)), digest)
private_source = "backtrader_runtime/certification_roundtrip_private.py"
EXPECTED[private_source] = (len(public_bytes(private_source)), hashlib.sha256(public_bytes(private_source)).hexdigest())
before = {}
for relative, (size, digest) in EXPECTED.items():
    data = public_bytes(relative)
    if (len(data), hashlib.sha256(data).hexdigest()) != (size, digest):
        raise RuntimeError("dependency_pin_mismatch: " + relative)
    before[relative] = pin(relative, data)

# Harness/library preload precedes candidate guard installation.
sys.path.insert(0, "D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages")
sys.path.insert(0, str(ROOT))
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
import pytest
import colorama
from _pytest.config import get_config
preload_config = get_config([])
preload_config._ensure_unconfigure()

blocked = []
private_prefix = "d:/temp/iteration41-okx-m01-v3-deployment"
def audit(event, args):
    category = None
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        value = os.fsdecode(args[0]).replace(chr(92), "/").lower()
        value = value.removeprefix("//?/")
        leaf = value.rsplit("/", 1)[-1]
        if value.startswith(private_prefix) or leaf in {".env", "config.yaml", "secrets.yaml"}:
            category = "private_path"
    if event.startswith("socket."):
        category = "network"
    if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "_winapi.CreateProcess"}:
        category = "process"
    if event in {"ctypes.dlopen", "ctypes.dlsym"}:
        category = "native_library"
    if category:
        blocked.append(category)
        raise PermissionError(category)

class DenySdk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "bt_api_py" or fullname.startswith("bt_api_py.") or fullname.startswith("bt_api_"):
            blocked.append("sdk_import")
            raise ImportError("sdk_import_denied")
        return None

sys.addaudithook(audit)
sys.meta_path.insert(0, DenySdk())
checks = 0
for event, args in (("socket.connect", (None, None)), ("subprocess.Popen", ("synthetic", [], None, {})), ("ctypes.dlopen", ("synthetic",))):
    try:
        sys.audit(event, *args)
    except PermissionError:
        checks += 1
try:
    (ROOT / ".env").open("rb")
except PermissionError:
    checks += 1
assert checks == 4
guard_baseline = len(blocked)

class Record:
    def __init__(self):
        self.items = []
        self.outcomes = []
        self.snapshots = []
    def pytest_collection_finish(self, session):
        self.items = [item.nodeid for item in session.items]
        assert len(self.items) == 11
        module = session.items[0].module
        for actual, relative in ((module.rebind, HELPER), (module.current_reader, manifest["source_dependencies"][0]["path"])):
            if actual is module.current_reader:
                relative = "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py"
            assert Path(actual.__file__).resolve() == (ROOT / relative).resolve()
            tree = compile(public_bytes(relative), str(ROOT / relative), "exec")
            codes = {code.co_name: code for code in tree.co_consts if isinstance(code, types.CodeType)}
            snapshot = {}
            for name, fn in vars(actual).items():
                if isinstance(fn, types.FunctionType) and fn.__globals__ is vars(actual) and name in codes:
                    assert fn.__code__ == codes[name]
                    snapshot[name] = (fn, fn.__code__)
            self.snapshots.append((actual, snapshot))
    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.failed:
            self.outcomes.append((report.nodeid, report.when, report.outcome))

record = Record()
code = pytest.main([str(ROOT / TEST), "-q", "-c", "NUL", "--confcutdir=" + str(ROOT / "tests/unit/scripts"), "-p", "no:cacheprovider", "-p", "no:xdist", "--tb=short"], plugins=[record])
unchanged = all(pin(relative, public_bytes(relative)) == value for relative, value in before.items())
bindings = all(vars(module).get(name) is fn and fn.__code__ is fncode and fn.__globals__ is vars(module) for module, snapshot in record.snapshots for name, (fn, fncode) in snapshot.items())
passed = sum(phase == "call" and outcome == "passed" for _, phase, outcome in record.outcomes)
candidate_blocked = blocked[guard_baseline:]
accepted = code == 0 and passed == 11 and len(record.items) == 11 and unchanged and bindings and not candidate_blocked
result = {"status": "SOURCE_FAKE_COMPONENT_ONLY" if accepted else "HOLD", "pytest_exit": int(code), "collected": len(record.items), "passed": passed, "guard_selfchecks": checks, "candidate_blocked_categories": candidate_blocked, "inputs_unchanged": unchanged, "live_function_bindings_preserved": bindings, "input_pins": list(before.values()), "formal_m01_pass": False, "provider_account_acceptance": False}
RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({key: result[key] for key in ("status", "pytest_exit", "collected", "passed", "guard_selfchecks", "candidate_blocked_categories", "inputs_unchanged", "live_function_bindings_preserved")}))
raise SystemExit(0 if accepted else 2)
