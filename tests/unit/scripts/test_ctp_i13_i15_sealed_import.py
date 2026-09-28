"""Fresh-process fake tests for the offline I13/I15 sealed importer."""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest


_BOOTSTRAP_PATH = Path(__file__).resolve().parents[3] / "scripts" / "ctp_i13_i15_sealed_import.py"
_BOOTSTRAP_BYTES = _BOOTSTRAP_PATH.read_bytes()
_PARENT_LAUNCHER_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "ctp_i13_i15_parent_launcher.py"
)
_PARENT_LAUNCHER_BYTES = _PARENT_LAUNCHER_PATH.read_bytes()
pytestmark = pytest.mark.skipif(
    sys.version_info[:3] != (3, 11, 5) or sys.platform != "win32",
    reason="I13/I15 offline bootstrap slice targets pinned Windows CPython 3.11.5",
)


def _fresh_python(code: str, *, pycache_prefix: Path) -> subprocess.CompletedProcess[str]:
    assert not pycache_prefix.exists()
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        "-X",
        f"pycache_prefix={pycache_prefix}",
        "-c",
        "exec(compile(__import__('sys').stdin.buffer.read(), '<captured-bytes>', 'exec'))",
    ]
    completed = subprocess.run(
        command,
        input=code.encode("utf-8"),
        capture_output=True,
        text=False,
        check=False,
        timeout=20,
    )
    assert not pycache_prefix.exists(), "-B must leave the unique pycache prefix absent"
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        completed.stdout.decode("utf-8", errors="replace"),
        completed.stderr.decode("utf-8", errors="replace"),
    )


def _normal_harness() -> str:
    return r"""
import hashlib
import importlib
import importlib.util
import json
import os
import pathlib
import sys
import _frozen_importlib_external

def _write_tree():
    prefix_path = pathlib.Path(sys.pycache_prefix)
    suffix = f"{os.getpid()}-{sys.modules['time'].time_ns()}"
    root = prefix_path.parent / (prefix_path.name + "-source-tree-" + suffix)
    root.mkdir()
    package = root / "backtrader_runtime"
    package.mkdir()
    sources = {
        "backtrader_runtime/__init__.py": b"from . import nested\nPACKAGE = 'sealed'\n",
        "backtrader_runtime/nested.py": b"VALUE = 'nested-import'\n",
        "backtrader_runtime/ctp_i13_md_oneshot_supervisor.py": b"VALUE = 'source'\n",
        "backtrader_runtime/probe.py": b"VALUE = 'before-seal'\n",
        "backtrader_runtime/probe2.py": b"VALUE = 'reparse-probe'\n",
        "backtrader_runtime/swap_probe.py": b"VALUE = 'swap-probe'\n",
        "backtrader_runtime/after_close.py": b"VALUE = 'must-not-load'\n",
        "backtrader_runtime/raises.py": b"raise RuntimeError('fixture failure')\n",
        "backtrader_runtime/ctp_i13_source_identity_pin.py": b"PIN = 'i13'\n",
        "backtrader_runtime/ctp_i15_source_identity_pin.py": b"PIN = 'i15'\n",
        "backtrader_runtime/ctp_i13_worker_dependency_seal.py": b"DEPENDENCY_SEAL = True\n",
        "scripts/ctp_i13_i15_readonly_preflight_worker.py": b"WORKER = 'fixed-readonly'\n",
        "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py": b"BOOTSTRAP = 'fixed-readonly'\n",
        "scripts/ctp_i13_i15_readonly_request_coordinator.py": (
            b"from dataclasses import dataclass\n"
            b"@dataclass(frozen=True)\n"
            b"class _Marker:\n"
            b"    value: int\n"
            b"def main(binding, runtime):\n"
            b"    runtime.call_token_helper(binding, _Marker(31).value)\n"
            b"    return runtime.record('coordinator', binding['request_id'], 17)\n"
        ),
        "scripts/ctp_i13_i15_readonly_receipt_writer.py": (
            b"from dataclasses import dataclass\n"
            b"@dataclass(frozen=True)\n"
            b"class _Marker:\n"
            b"    value: int\n"
            b"def main(binding, runtime):\n"
            b"    return runtime.record('receipt_writer', binding['request_id'], _Marker(23).value)\n"
        ),
        "scripts/ctp_i13_i15_readonly_token_bootstrap.py": (
            b"from dataclasses import dataclass\n"
            b"@dataclass(frozen=True)\n"
            b"class _Transfer:\n"
            b"    request_id: str\n"
            b"    nonce: str\n"
            b"    owner_sid: str\n"
            b"def parse_token_bootstrap_frame(raw, *, expected_request_id, expected_nonce, expected_owner_sid):\n"
            b"    return _Transfer(expected_request_id, expected_nonce, expected_owner_sid)\n"
            b"def apply_owner_token_session_zero(transfer, *, api):\n"
            b"    return api.apply_transfer(transfer)\n"
        ),
    }
    for relative, source in sources.items():
        target = root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source)
    manifested = {
        path: hashlib.sha256(source).hexdigest()
        for path, source in sorted(sources.items())
        if path not in {
            "backtrader_runtime/ctp_i13_source_identity_pin.py",
            "backtrader_runtime/ctp_i15_source_identity_pin.py",
        }
    }
    raw = json.dumps(
        {"schema": 1, "source_files": manifested},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    (package / "ctp_i13_source_manifest.json").write_bytes(raw)
    pins = {
        "i13": hashlib.sha256(sources["backtrader_runtime/ctp_i13_source_identity_pin.py"]).hexdigest(),
        "i15": hashlib.sha256(sources["backtrader_runtime/ctp_i15_source_identity_pin.py"]).hexdigest(),
    }
    return root, sources, raw, pins

def _seal(root, raw, pins):
    return seal_candidate_source_tree(
        "i13_md",
        root,
        expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
        expected_pin_sha256s=pins,
        stdlib_paths=tuple(sys.path),
    )

i15_files = [
    {"path": "backtrader_runtime/__init__.py", "sha256": "1" * 64},
    {"path": "backtrader_runtime/ctp_i15_td_only_readonly.py", "sha256": "2" * 64},
]
i15_raw = json.dumps(
    {"files": i15_files, "schema": "ctp_i15_source_manifest.v2"},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
assert set(
    parse_candidate_manifest(
        "i15_td",
        i15_raw,
        expected_manifest_sha256=hashlib.sha256(i15_raw).hexdigest(),
    )
) == {row["path"] for row in i15_files}

bad_path_raw = json.dumps(
    {
        "files": [
            {"path": "backtrader_runtime/../escape.py", "sha256": "1" * 64},
            {"path": "backtrader_runtime/ctp_i15_td_only_readonly.py", "sha256": "2" * 64},
        ],
        "schema": "ctp_i15_source_manifest.v2",
    },
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
try:
    parse_candidate_manifest(
        "i15_td",
        bad_path_raw,
        expected_manifest_sha256=hashlib.sha256(bad_path_raw).hexdigest(),
    )
except SealedImportError as error:
    assert str(error) == "manifest_path_invalid"
else:
    raise AssertionError("manifest path traversal was accepted")

duplicate = b'{"schema":1,"source_files":{},"schema":1}'
try:
    parse_candidate_manifest(
        "i13_md",
        duplicate,
        expected_manifest_sha256=hashlib.sha256(duplicate).hexdigest(),
    )
except SealedImportError as error:
    assert str(error) == "manifest_duplicate_key"
else:
    raise AssertionError("duplicate manifest key was accepted")

root, sources, raw, pins = _write_tree()
package = root / "backtrader_runtime"
candidate = package / "ctp_i13_md_oneshot_supervisor.py"
original_platform = sys.platform
sys.platform = "linux"
try:
    seal_candidate_source_tree(
        "i13_md",
        root,
        expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
        expected_pin_sha256s=pins,
        stdlib_paths=tuple(sys.path),
    )
except SealedImportError as error:
    assert str(error) == "windows_source_lease_required"
else:
    raise AssertionError("non-Windows source sealing did not fail closed")
finally:
    sys.platform = original_platform

cache = package / "__pycache__" / (
    candidate.stem + "." + sys.implementation.cache_tag + ".pyc"
)
cache.parent.mkdir(parents=True, exist_ok=True)
marker = root / "pyc-executed"
evil = compile(
    "VALUE = 'pyc'\nopen(" + repr(str(marker)) + ", 'w').write('bad')\n",
    "stale-pyc-sentinel",
    "exec",
)
cache_bytes = _frozen_importlib_external._code_to_timestamp_pyc(
    evil, int(candidate.stat().st_mtime), candidate.stat().st_size
)
assert cache_bytes[:4] == importlib.util.MAGIC_NUMBER
cache.write_bytes(cache_bytes)
seal = _seal(root, raw, pins)
unleased = SealedSourceTree(
    candidate=seal.candidate,
    source_root=seal.source_root,
    manifest_sha256=seal.manifest_sha256,
    files=seal.files,
    stdlib_paths=seal.stdlib_paths,
    source_lease=None,
)
try:
    install_sealed_source_finder(unleased)
except SealedImportError as error:
    assert str(error) == "source_lease_unavailable"
else:
    raise AssertionError("source tree without a live lease was accepted")
fractions_spec = importlib.util.find_spec("fractions")
assert fractions_spec is not None
finder = install_sealed_source_finder(seal)
try:
    run_fixed_readonly_service_role(
        seal,
        finder,
            "request_coordinator",
            {
                "schema": "ctp_i13_i15_readonly_request_coordinator_binding.v1",
                "request_id": "b" * 32,
            },
        )
except SealedImportError as error:
    assert str(error) == "readonly_role_runtime_factory_unavailable"
else:
    raise AssertionError("service role ran without the fixed runtime factory")
fake_fractions = type(sys)("fractions")
fake_fractions.__spec__ = fractions_spec
fake_fractions.__loader__ = fractions_spec.loader
fake_fractions.__file__ = fractions_spec.origin
sys.modules["fractions"] = fake_fractions
try:
    import_sealed_candidate_module(seal, finder)
except SealedImportError as error:
    assert str(error) == "bootstrap_module_outside_snapshot"
else:
    raise AssertionError("uncaptured stdlib cache object bypassed the sealed closure")
del sys.modules["fractions"]
entrypoint = CANDIDATES["i13_md"].entrypoint
sys.modules[entrypoint] = sys.modules["__main__"]
try:
    import_sealed_candidate_module(seal, finder)
except SealedImportError as error:
    assert str(error) == "bootstrap_runtime_module_invalid"
else:
    raise AssertionError("entrypoint aliased to __main__ bypassed the sealed loader")
del sys.modules[entrypoint]
fake_spec = finder.find_spec(entrypoint)
assert fake_spec is not None
fake_entrypoint = type(sys)(entrypoint)
fake_entrypoint.__spec__ = fake_spec
fake_entrypoint.__loader__ = fake_spec.loader
fake_entrypoint.__file__ = fake_spec.origin
fake_entrypoint.__cached__ = None
sys.modules[entrypoint] = fake_entrypoint
try:
    import_sealed_candidate_module(seal, finder)
except SealedImportError as error:
    assert str(error) == "bootstrap_runtime_module_invalid"
else:
    raise AssertionError("cached module with an unexecuted legal spec was accepted")
assert not hasattr(fake_entrypoint, "VALUE")
del sys.modules[entrypoint]
module = import_sealed_candidate_module(seal, finder)
assert module.VALUE == "source"
assert module.__cached__ is None and module.__spec__.cached is None
assert sys.modules["backtrader_runtime.nested"].VALUE == "nested-import"
assert not marker.exists()
worker_relative = "scripts/ctp_i13_i15_readonly_preflight_worker.py"
assert seal.worker_sha256 == hashlib.sha256(sources[worker_relative]).hexdigest()
assert seal.read_worker_source() == sources[worker_relative]
bootstrap_relative = "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
assert seal.bootstrap_sha256 == hashlib.sha256(sources[bootstrap_relative]).hexdigest()
assert seal.read_bootstrap_source() == sources[bootstrap_relative]
coordinator_relative = "scripts/ctp_i13_i15_readonly_request_coordinator.py"
receipt_writer_relative = "scripts/ctp_i13_i15_readonly_receipt_writer.py"
token_bootstrap_relative = "scripts/ctp_i13_i15_readonly_token_bootstrap.py"
assert seal.read_request_coordinator_source() == sources[coordinator_relative]
assert seal.read_receipt_writer_source() == sources[receipt_writer_relative]
assert seal.read_token_bootstrap_source() == sources[token_bootstrap_relative]
seal.source_lease.verify_current()

try:
    importlib.import_module("scripts.ctp_i13_i15_readonly_preflight_worker")
except ModuleNotFoundError as error:
    assert "unsealed_external_module" in str(error)
else:
    raise AssertionError("pinned worker source became importable as a module")
try:
    importlib.import_module("scripts.ctp_i13_i15_readonly_preflight_bootstrap")
except ModuleNotFoundError as error:
    assert "unsealed_external_module" in str(error)
else:
    raise AssertionError("pinned bootstrap source became importable as a module")
for role_relative in (coordinator_relative, receipt_writer_relative, token_bootstrap_relative):
    role_module = role_relative[:-3].replace("/", ".")
    try:
        importlib.import_module(role_module)
    except ModuleNotFoundError as error:
        assert "unsealed_external_module" in str(error)
    else:
        raise AssertionError("service role source became importable as a module")

worker_only_files = dict(json.loads(raw.decode("utf-8"))["source_files"])
worker_only_files.pop(bootstrap_relative)
worker_only_files.pop(coordinator_relative)
worker_only_files.pop(receipt_writer_relative)
worker_only_files.pop(token_bootstrap_relative)
worker_only_raw = json.dumps(
    {"schema": 1, "source_files": worker_only_files},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
assert _FIXED_READONLY_WORKER_RELATIVE_PATH in parse_candidate_manifest(
    "i13_md",
    worker_only_raw,
    expected_manifest_sha256=hashlib.sha256(worker_only_raw).hexdigest(),
)
helper_missing_files = dict(json.loads(raw.decode("utf-8"))["source_files"])
helper_missing_files.pop(_FIXED_WORKER_DEPENDENCY_HELPER_RELATIVE_PATH)
helper_missing_raw = json.dumps(
    {"schema": 1, "source_files": helper_missing_files},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
try:
    parse_candidate_manifest(
        "i13_md",
        helper_missing_raw,
        expected_manifest_sha256=hashlib.sha256(helper_missing_raw).hexdigest(),
    )
except SealedImportError as error:
    assert str(error) == "readonly_dependency_helper_unpinned"
else:
    raise AssertionError("bootstrap manifest omitted its dependency-seal helper")
bootstrap_only_files = dict(worker_only_files)
bootstrap_only_files.pop(worker_relative)
bootstrap_only_files[bootstrap_relative] = hashlib.sha256(
    sources[bootstrap_relative]
).hexdigest()
bootstrap_only_raw = json.dumps(
    {"schema": 1, "source_files": bootstrap_only_files},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
try:
    parse_candidate_manifest(
        "i13_md",
        bootstrap_only_raw,
        expected_manifest_sha256=hashlib.sha256(bootstrap_only_raw).hexdigest(),
    )
except SealedImportError as error:
    assert str(error) == "readonly_worker_source_unpinned"
else:
    raise AssertionError("bootstrap-only manifest omitted its required worker")

legacy_bootstrap_files = dict(json.loads(raw.decode("utf-8"))["source_files"])
legacy_bootstrap_files.pop(coordinator_relative)
legacy_bootstrap_files.pop(receipt_writer_relative)
legacy_bootstrap_files.pop(token_bootstrap_relative)
legacy_bootstrap_raw = json.dumps(
    {"schema": 1, "source_files": legacy_bootstrap_files},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
parse_candidate_manifest(
    "i13_md",
    legacy_bootstrap_raw,
    expected_manifest_sha256=hashlib.sha256(legacy_bootstrap_raw).hexdigest(),
)

incomplete_service_role_files = dict(json.loads(raw.decode("utf-8"))["source_files"])
incomplete_service_role_files.pop(receipt_writer_relative)
incomplete_service_role_raw = json.dumps(
    {"schema": 1, "source_files": incomplete_service_role_files},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
try:
    parse_candidate_manifest(
        "i13_md",
        incomplete_service_role_raw,
        expected_manifest_sha256=hashlib.sha256(incomplete_service_role_raw).hexdigest(),
    )
except SealedImportError as error:
    assert str(error) == "readonly_service_role_sources_incomplete"
else:
    raise AssertionError("incomplete service-role source pair was accepted")

bad_worker_path = dict(json.loads(raw.decode("utf-8"))["source_files"])
bad_worker_path["scripts/unreviewed.py"] = hashlib.sha256(b"x").hexdigest()
bad_worker_raw = json.dumps(
    {"schema": 1, "source_files": bad_worker_path},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
try:
    parse_candidate_manifest(
        "i13_md",
        bad_worker_raw,
        expected_manifest_sha256=hashlib.sha256(bad_worker_raw).hexdigest(),
    )
except SealedImportError as error:
    assert str(error) == "manifest_path_invalid"
else:
    raise AssertionError("unreviewed scripts source path was accepted")

rogue = package / "rogue.py"
try:
    rogue.write_text("VALUE = 'unlisted'\n", encoding="utf-8")
except OSError:
    pass
try:
    importlib.import_module("backtrader_runtime.rogue")
except ModuleNotFoundError as error:
    assert "runtime_module_not_allowlisted" in str(error)
else:
    raise AssertionError("unlisted runtime sibling reached a fallback finder")

def _install_lease_fault(relative, mode):
    api = seal.source_lease._api
    original_open = api.open
    original_attributes = api.attributes
    original_identity = api.identity
    original_read = api.read
    rooted_relative = (
        relative if relative.startswith("scripts/") else "backtrader_runtime/" + relative
    )
    target = os.path.normcase(os.path.normpath(str(root.joinpath(*rooted_relative.split("/")))))
    opened = []
    def _recording_open(path, *, is_directory, lease, read_data=False):
        handle = original_open(path, is_directory=is_directory, lease=lease, read_data=read_data)
        opened.append((handle, os.path.normcase(os.path.normpath(path))))
        return handle
    def _opened_path(handle):
        for seen_handle, seen_path in reversed(opened):
            if seen_handle == handle:
                return seen_path
        return None
    api.open = _recording_open
    if mode == "reparse":
        def _attributes(handle):
            if _opened_path(handle) == target:
                return _FILE_ATTRIBUTE_REPARSE_POINT
            return original_attributes(handle)
        api.attributes = _attributes
    elif mode == "swap":
        def _identity(handle):
            identity = original_identity(handle)
            if _opened_path(handle) == target:
                return WindowsFileIdentity(
                    identity.volume_serial,
                    bytes(value ^ 1 for value in identity.file_id),
                )
            return identity
        api.identity = _identity
    elif mode == "same-size-tamper":
        def _read(handle, size):
            if _opened_path(handle) == target:
                return b"X" * size
            return original_read(handle, size)
        api.read = _read
    else:
        raise AssertionError("unknown lease fault")
    def _restore():
        api.open = original_open
        api.attributes = original_attributes
        api.identity = original_identity
        api.read = original_read
    return _restore

for relative, mode, reason in (
    ("probe.py", "same-size-tamper", "source_content_changed"),
    ("probe2.py", "reparse", "source_path_reparse_point"),
    ("swap_probe.py", "swap", "source_file_identity_mismatch"),
):
    restore = _install_lease_fault(relative, mode)
    try:
        importlib.import_module("backtrader_runtime." + relative[:-3])
    except WindowsSourceLeaseError as error:
        assert str(error) == reason
    else:
        raise AssertionError(f"lease source fault was accepted: {relative} ({mode})")
    finally:
        restore()

restore = _install_lease_fault("probe.py", "swap")
try:
    seal.source_lease.verify_current()
except WindowsSourceLeaseError as error:
    assert str(error) == "source_file_identity_mismatch"
else:
    raise AssertionError("retained source lease ignored an identity swap")
finally:
    restore()

restore = _install_lease_fault(worker_relative, "same-size-tamper")
try:
    seal.read_worker_source()
except SealedImportError as error:
    assert str(error) == "readonly_worker_source_unavailable"
    assert isinstance(error.__cause__, WindowsSourceLeaseError)
    assert str(error.__cause__) == "source_content_changed"
else:
    raise AssertionError("same-size worker source tampering was accepted")
finally:
    restore()

restore = _install_lease_fault(bootstrap_relative, "same-size-tamper")
try:
    seal.read_bootstrap_source()
except SealedImportError as error:
    assert str(error) == "readonly_bootstrap_source_unavailable"
    assert isinstance(error.__cause__, WindowsSourceLeaseError)
    assert str(error.__cause__) == "source_content_changed"
else:
    raise AssertionError("same-size bootstrap source tampering was accepted")
finally:
    restore()

assert importlib.import_module("backtrader_runtime.probe").VALUE == "before-seal"
assert importlib.import_module("backtrader_runtime.probe2").VALUE == "reparse-probe"
assert importlib.import_module("backtrader_runtime.swap_probe").VALUE == "swap-probe"
try:
    importlib.import_module("backtrader_runtime.raises")
except RuntimeError as error:
    assert str(error) == "fixture failure"
else:
    raise AssertionError("raising fake module unexpectedly imported")
assert "backtrader_runtime.raises" not in sys.modules
assert "backtrader_runtime.raises" not in finder._in_progress_modules
assert "backtrader_runtime.raises" not in finder._executed_modules

probe = package / "probe.py"
try:
    probe.write_text("VALUE = 'changed-after-seal'\n", encoding="utf-8")
except OSError:
    pass
else:
    raise AssertionError("source replacement succeeded under active lease")

try:
    importlib.import_module("backtrader_runtime.not_an_identifier-")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("invalid runtime module name was accepted")

try:
    importlib.import_module("backtrader")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("core backtrader fallback was accepted")

try:
    importlib.import_module("yaml")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("non-stdlib fallback was accepted")

class _FakeDependencyFinder:
    top_level_roots = ("yaml", "bt_api_base", "bt_api_ctp")

    def __init__(self):
        self.spec = object()
        self.validate_calls = 0
        self.owned = {}

    def validate_current(self):
        self.validate_calls += 1

    def find_spec(self, fullname, path=None, target=None):
        del path, target
        return self.spec if fullname == "yaml" else None

    def owns_module(self, fullname, module):
        return self.owned.get(fullname) is module

dependency_finder = _FakeDependencyFinder()
finder.attach_dependency_finder(dependency_finder)
assert sys.meta_path[0] is finder
assert finder.find_spec("yaml") is dependency_finder.spec
assert dependency_finder.validate_calls >= 1
fake_yaml = type(sys)("yaml")
sys.modules["yaml"] = fake_yaml
dependency_finder.owned["yaml"] = fake_yaml
_require_clean_after_install(seal, finder=finder)
dependency_finder.owned["yaml"] = object()
try:
    _require_clean_after_install(seal, finder=finder)
except SealedImportError as error:
    assert str(error) == "bootstrap_dependency_module_invalid"
else:
    raise AssertionError("unowned dependency module bypassed source-state validation")
dependency_finder.owned["yaml"] = fake_yaml
try:
    finder.detach_dependency_finder(object())
except SealedImportError as error:
    assert str(error) == "dependency_finder_identity_mismatch"
else:
    raise AssertionError("a different dependency finder detached the attached finder")
finder.detach_dependency_finder(dependency_finder)
del sys.modules["yaml"]
try:
    finder.find_spec("yaml")
except ModuleNotFoundError as error:
    assert "sealed_dependency_finder_unavailable" in str(error)
else:
    raise AssertionError("dependency import survived identity-checked detach")

assert "fractions" not in sys.modules
extension_name = next(
    (
        name
        for name in ("_sqlite3", "_elementtree", "_tkinter", "_ssl")
        if name in sys.stdlib_module_names
        and name not in sys.modules
        and name not in sys.builtin_module_names
    ),
    None,
)
assert type(extension_name) is str
external = sys.modules["_frozen_importlib_external"]
zipimport_module = sys.modules["zipimport"]
runtime_entries = {}
for original_name, module in _BOOTSTRAP_MODULE_OBJECTS.items():
    if type(module) is not type(sys):
        continue
    module_spec = getattr(module, "__spec__", None)
    origin = getattr(module_spec, "origin", None)
    if type(origin) is not str or origin in {"built-in", "frozen"}:
        continue
    if not any(_path_is_root_or_beneath(origin, root) for root in seal.stdlib_paths):
        continue
    loader = getattr(module_spec, "loader", None)
    if type(loader) is external.SourceFileLoader or type(loader) is zipimport_module.zipimporter:
        kind = "source"
    elif type(loader) is external.ExtensionFileLoader:
        kind = "extension"
    else:
        continue
    fullname = _MODULE_NAME_ALIASES.get(original_name, original_name)
    root = next(root for root in seal.stdlib_paths if _path_is_root_or_beneath(origin, root))
    relative = ntpath.relpath(origin, root).replace("\\", "/")
    runtime_entries.setdefault(
        fullname,
        type("RuntimeEntry", (), {})(),
    )
    entry = runtime_entries[fullname]
    entry.fullname = fullname
    entry.origin = origin
    entry.kind = kind
    entry.is_package = hasattr(module, "__path__")
    entry.root_kind = "base"
    entry.relative_path = relative
    entry.sha256 = "a" * 64
    entry.size = 1

fraction_bytes = b"VALUE = 'runtime-stdlib-source'\n"
fraction_entry = type("RuntimeEntry", (), {})()
fraction_entry.fullname = "fractions"
fraction_entry.origin = ntpath.join(seal.stdlib_paths[2], "fractions.py")
fraction_entry.kind = "source"
fraction_entry.is_package = False
fraction_entry.root_kind = "base"
fraction_entry.relative_path = "fractions.py"
fraction_entry.sha256 = hashlib.sha256(fraction_bytes).hexdigest()
fraction_entry.size = len(fraction_bytes)
runtime_entries["fractions"] = fraction_entry
extension_entry = type("RuntimeEntry", (), {})()
extension_entry.fullname = extension_name
extension_entry.origin = ntpath.join(seal.stdlib_paths[1], extension_name + ".pyd")
extension_entry.kind = "extension"
extension_entry.is_package = False
extension_entry.root_kind = "base"
extension_entry.relative_path = extension_name + ".pyd"
extension_entry.sha256 = "b" * 64
extension_entry.size = 1
runtime_entries[extension_name] = extension_entry

class _FakeRuntimeClosure:
    def __init__(self, entries):
        self.stdlib_modules = tuple(entries.values())
        self.entries = dict(entries)
        self.verify_calls = 0

    def stdlib_entry(self, fullname):
        return self.entries.get(fullname)

    def verify_stdlib_entry(self, fullname):
        return self.entries.get(fullname)

    def read_stdlib_source(self, fullname):
        assert fullname == "fractions"
        return fraction_bytes

    def verify_current(self):
        self.verify_calls += 1

runtime_closure = _FakeRuntimeClosure(runtime_entries)
finder.attach_runtime_closure(runtime_closure)
role_dependency_finder = _FakeDependencyFinder()
finder.attach_dependency_finder(role_dependency_finder)
assert finder._dependency_finder is role_dependency_finder
assert finder._runtime_closure is runtime_closure
assert finder._runtime_closure_identity is runtime_closure
assert sys.meta_path[0] is finder
assert type(seal) is SealedSourceTree
assert type(finder) is SealedSourceFinder
assert seal.candidate == "i13_md"
assert finder._seal is seal

coordinator_binding = {
    "schema": "ctp_i13_i15_readonly_request_coordinator_binding.v1",
    "request_id": "b" * 32,
}
try:
    run_fixed_readonly_service_role(seal, finder, "request_coordinator", coordinator_binding)
except SealedImportError as error:
    assert str(error) == "readonly_role_runtime_factory_unavailable"
else:
    raise AssertionError("service role dispatched without a code-owned runtime factory")
try:
    run_fixed_readonly_service_role(
        seal, finder, "request_coordinator", coordinator_binding, runtime=object()
    )
except TypeError:
    pass
else:
    raise AssertionError("caller supplied service-role runtime object was accepted")
receipt_binding = {
    "schema": "ctp_i13_i15_readonly_receipt_writer_binding.v1",
    "request_id": "c" * 32,
}
try:
    run_fixed_readonly_service_role(seal, finder, "receipt_writer", receipt_binding)
except SealedImportError as error:
    assert str(error) == "readonly_role_runtime_factory_unavailable"
else:
    raise AssertionError("receipt writer dispatched without a code-owned runtime factory")
assert not any(name.startswith("_i13_fixed_readonly_") for name in sys.modules)
try:
    run_fixed_readonly_service_role(
        seal,
        finder,
        "request_coordinator",
        {"schema": "ctp_i13_i15_readonly_receipt_writer_binding.v1"},
    )
except SealedImportError as error:
    assert str(error) == "readonly_role_binding_invalid"
else:
    raise AssertionError("coordinator dispatcher accepted the writer schema")
try:
    run_fixed_readonly_token_bootstrap(
        seal,
        finder,
        b"fixed token frame fixture",
        request_id="b" * 32,
        nonce="a" * 32,
        owner_sid="S-1-5-21-100-200-300-1001",
    )
except SealedImportError as error:
    assert str(error) == "readonly_token_helper_outside_coordinator"
else:
    raise AssertionError("token helper compiled outside coordinator role")
try:
    run_fixed_readonly_token_bootstrap(
        seal,
        finder,
        b"fixed token frame fixture",
        request_id="b" * 32,
        nonce="a" * 32,
        owner_sid="S-1-5-21-100-200-300-1001",
        api=object(),
    )
except TypeError:
    pass
else:
    raise AssertionError("caller supplied token OS adapter was accepted")
fraction_spec = finder.find_spec("fractions")
assert fraction_spec.origin == fraction_entry.origin and fraction_spec.cached is None
assert type(fraction_spec.loader) is _SealedRuntimeStdlibLoader
fractions = importlib.import_module("fractions")
assert fractions.VALUE == "runtime-stdlib-source"
assert sys.modules["fractions"] is fractions
assert finder._owns_runtime_stdlib_module("fractions", fractions)
assert runtime_closure.verify_calls > 0
extension_spec = finder.find_spec(extension_name)
assert extension_spec.origin == extension_entry.origin and extension_spec.cached is None
assert type(extension_spec.loader) is _SealedRuntimeStdlibLoader
assert type(extension_spec.loader._extension_loader) is external.ExtensionFileLoader
assert extension_spec.loader._extension_loader.path == extension_entry.origin
assert extension_name not in sys.modules
try:
    finder.find_spec("decimal")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("an unlisted stdlib module used PathFinder fallback")
fake_fraction = type(sys)("fractions")
fake_fraction.__spec__ = fraction_spec
fake_fraction.__loader__ = fraction_spec.loader
fake_fraction.__file__ = fraction_spec.origin
fake_fraction.__cached__ = None
sys.modules["fractions"] = fake_fraction
try:
    _require_clean_after_install(seal, finder=finder)
except SealedImportError as error:
    assert str(error) == "bootstrap_module_outside_snapshot"
else:
    raise AssertionError("unexecuted runtime stdlib spec bypassed module identity")
sys.modules["fractions"] = fractions
finder.detach_runtime_closure(runtime_closure)
del sys.modules["fractions"]

lease_api = seal.source_lease._api
original_close = lease_api.close
fail_handle = seal.source_lease._handles[-1]
close_failed = False
def _fail_one_close(handle):
    global close_failed
    if handle == fail_handle and not close_failed:
        close_failed = True
        raise OSError("injected retained-handle close failure")
    original_close(handle)
lease_api.close = _fail_one_close
try:
    seal.close()
except WindowsSourceLeaseError as error:
    assert str(error) == "source_lease_close_failed"
else:
    raise AssertionError("sealed tree ignored retained-handle close failure")
assert seal.source_lease._handles == [fail_handle]
assert seal.source_lease._poisoned and not seal.source_lease._closed
assert seal.source_lease in _PENDING_WINDOWS_SOURCE_LEASES
try:
    import_sealed_candidate_module(seal, finder)
except SealedImportError as error:
    assert str(error) == "source_lease_unavailable"
else:
    raise AssertionError("poisoned lease allowed cached candidate re-import")
lease_api.close = original_close
retry_pending_windows_source_lease_cleanup()
assert seal.source_lease._closed and not seal.source_lease._handles
assert not _PENDING_WINDOWS_SOURCE_LEASES
try:
    importlib.import_module("backtrader_runtime.after_close")
except SealedImportError as error:
    assert str(error) == "source_lease_unavailable"
else:
    raise AssertionError("closed lease allowed a new runtime import")

legacy_root, legacy_sources, _new_raw, legacy_pins = _write_tree()
legacy_manifest = {
    path: hashlib.sha256(source).hexdigest()
    for path, source in sorted(legacy_sources.items())
    if path not in {
        "backtrader_runtime/ctp_i13_source_identity_pin.py",
        "backtrader_runtime/ctp_i15_source_identity_pin.py",
        worker_relative,
        bootstrap_relative,
        coordinator_relative,
        receipt_writer_relative,
        token_bootstrap_relative,
    }
}
legacy_raw = json.dumps(
    {"schema": 1, "source_files": legacy_manifest},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
(legacy_root / "backtrader_runtime" / "ctp_i13_source_manifest.json").write_bytes(legacy_raw)
legacy_seal = _seal(legacy_root, legacy_raw, legacy_pins)
assert worker_relative not in legacy_seal.files
assert bootstrap_relative not in legacy_seal.files
try:
    legacy_seal.read_worker_source()
except SealedImportError as error:
    assert str(error) == "readonly_worker_source_unpinned"
else:
    raise AssertionError("legacy runtime-only manifest exposed unpinned worker bytes")
legacy_seal.close()

print("sealed-import-fake-checks-passed")
"""


def test_fresh_isolated_import_uses_source_and_blocks_unlisted_and_replaced_files(
    tmp_path: Path,
) -> None:
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    cache_prefix = tmp_path / f"pycache-absent-{uuid.uuid4().hex}"
    result = _fresh_python(source + _normal_harness(), pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sealed-import-fake-checks-passed" in result.stdout


def test_embedded_scripts_support_uses_exact_single_module_identity(tmp_path: Path) -> None:
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    harness = r'''
import hashlib
import importlib
import sys

outer_path = "scripts/ctp_i13_i15_outer_watchdog.py"
channel_path = "scripts/ctp_i13_i15_worker_output_channel.py"
backend_path = "scripts/ctp_i13_i15_windows_job_backend.py"
outer_source = b"class OuterBackendCreationError(Exception): pass"
channel_source = (
    b"from scripts.ctp_i13_i15_outer_watchdog import OuterBackendCreationError; "
    b"CHANNEL_ERROR = OuterBackendCreationError"
)
backend_source = (
    b"from scripts.ctp_i13_i15_outer_watchdog import OuterBackendCreationError; "
    b"BACKEND_ERROR = OuterBackendCreationError"
)
registration = _FIXED_BOOTSTRAP_SUPPORT_REGISTRATION_TOKEN

fake = type(sys)("scripts")
sys.modules["scripts"] = fake
try:
    finder._begin_fixed_bootstrap_support_package(fake, capability=registration)
except SealedImportError as error:
    assert str(error) == "bootstrap_support_package_invalid"
else:
    raise AssertionError("preloaded scripts package was accepted")
del sys.modules["scripts"]

fake_child = type(sys)("scripts.ctp_i13_i15_outer_watchdog")
sys.modules["scripts.ctp_i13_i15_outer_watchdog"] = fake_child
try:
    finder._begin_fixed_bootstrap_support_package(type(sys)("scripts"), capability=registration)
except SealedImportError as error:
    assert str(error) == "bootstrap_support_package_invalid"
else:
    raise AssertionError("preloaded support module cache was accepted")
del sys.modules["scripts.ctp_i13_i15_outer_watchdog"]

finder._begin_fixed_bootstrap_support_package(type(sys)("scripts"), capability=registration)
try:
    finder._load_fixed_bootstrap_support_module(
        "scripts/unreviewed.py", b"VALUE=1", expected_sha256=hashlib.sha256(b"VALUE=1").hexdigest(),
        capability=registration,
    )
except SealedImportError as error:
    assert str(error) == "bootstrap_support_module_binding_invalid"
else:
    raise AssertionError("unreviewed support alias was accepted")

try:
    finder._load_fixed_bootstrap_support_module(
        outer_path, outer_source, expected_sha256="0" * 64, capability=registration,
    )
except SealedImportError as error:
    assert str(error) == "bootstrap_support_module_digest_mismatch"
else:
    raise AssertionError("wrong support digest was accepted")

try:
    finder._load_fixed_bootstrap_support_module(
        channel_path, channel_source,
        expected_sha256=hashlib.sha256(channel_source).hexdigest(), capability=registration,
    )
except ModuleNotFoundError as error:
    assert str(error) == "unsealed_external_module"
else:
    raise AssertionError("out-of-order support dependency was imported")
assert "scripts.ctp_i13_i15_worker_output_channel" not in sys.modules

outer = finder._load_fixed_bootstrap_support_module(
    outer_path, outer_source,
    expected_sha256=hashlib.sha256(outer_source).hexdigest(), capability=registration,
)
channel = finder._load_fixed_bootstrap_support_module(
    channel_path, channel_source,
    expected_sha256=hashlib.sha256(channel_source).hexdigest(), capability=registration,
)
backend = finder._load_fixed_bootstrap_support_module(
    backend_path, backend_source,
    expected_sha256=hashlib.sha256(backend_source).hexdigest(), capability=registration,
)
assert channel.OuterBackendCreationError is outer.OuterBackendCreationError
assert backend.BACKEND_ERROR is outer.OuterBackendCreationError
assert importlib.import_module("scripts.ctp_i13_i15_outer_watchdog") is outer
assert importlib.import_module("scripts.ctp_i13_i15_worker_output_channel") is channel
assert importlib.import_module("scripts.ctp_i13_i15_windows_job_backend") is backend
assert len(finder._fixed_bootstrap_support_modules) == 3

sys.modules["scripts.ctp_i13_i15_outer_watchdog_alias"] = outer
try:
    _require_clean_after_install(seal, finder=finder)
except SealedImportError as error:
    assert str(error) == "bootstrap_module_outside_snapshot"
else:
    raise AssertionError("duplicate module alias escaped identity checks")
del sys.modules["scripts.ctp_i13_i15_outer_watchdog_alias"]

try:
    importlib.import_module("scripts.unreviewed")
except ModuleNotFoundError as error:
    assert str(error) == "unsealed_external_module"
else:
    raise AssertionError("scripts namespace fallback was enabled")
print("embedded-support-single-identity-passed")
'''
    cache_prefix = tmp_path / "p"
    normal = _normal_harness()
    insertion = "finder = install_sealed_source_finder(seal)\ntry:\n    run_fixed_readonly_service_role("
    assert normal.count(insertion) == 1
    normal = normal.replace(
        insertion,
        "finder = install_sealed_source_finder(seal)\n" + harness + "\ntry:\n    run_fixed_readonly_service_role(",
        1,
    )
    result = _fresh_python(source + normal, pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "embedded-support-single-identity-passed" in result.stdout


def test_public_clean_bootstrap_gate_checks_import_closure_before_source_seal(
    tmp_path: Path,
) -> None:
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    harness = r"""
validate_clean_bootstrap_import_state()
print("clean-bootstrap-import-state-passed")
sys.modules["backtrader"] = type(sys)("backtrader")
try:
    validate_clean_bootstrap_import_state()
except SealedImportError as error:
    assert str(error) == "unsealed_backtrader_namespace"
else:
    raise AssertionError("uncaptured Backtrader module survived clean-state check")
del sys.modules["backtrader"]
"""
    cache_prefix = tmp_path / f"pycache-clean-import-{uuid.uuid4().hex}"
    result = _fresh_python(source + harness, pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "clean-bootstrap-import-state-passed" in result.stdout


def test_combined_parent_launcher_preserves_captured_import_closure(tmp_path: Path) -> None:
    source = _BOOTSTRAP_BYTES.decode("utf-8") + _PARENT_LAUNCHER_BYTES.decode("utf-8")
    harness = r"""
validate_clean_bootstrap_import_state()
print("combined-parent-bootstrap-clean")
sys.modules["backtrader"] = type(sys)("backtrader")
try:
    validate_clean_bootstrap_import_state()
except SealedImportError as error:
    assert str(error) == "unsealed_backtrader_namespace"
else:
    raise AssertionError("combined launcher accepted an injected runtime namespace")
del sys.modules["backtrader"]
"""
    cache_prefix = tmp_path / f"pycache-combined-{uuid.uuid4().hex}"
    result = _fresh_python(source + harness, pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "combined-parent-bootstrap-clean" in result.stdout


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("sys.meta_path.append(object())", "bootstrap_meta_path_invalid"),
        ("sys.path_hooks.append(object())", "bootstrap_path_hooks_invalid"),
    ],
)
def test_fresh_isolated_import_rejects_preexisting_hooks_before_runtime_import(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    prefix = f"""
import sys
{mutation}
def _report(error_type, error, traceback):
    print(str(error))
    print(any(name == "backtrader_runtime" or name.startswith("backtrader_runtime.") for name in sys.modules))
sys.excepthook = _report
"""
    cache_prefix = tmp_path / f"pycache-hook-{uuid.uuid4().hex}"
    result = _fresh_python(prefix + source, pycache_prefix=cache_prefix)
    assert result.returncode == 1
    assert reason in result.stdout
    assert result.stdout.rstrip().endswith("False")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            'sys.modules["json"] = type(sys)("json")',
            "bootstrap_preloaded_module_set_invalid",
        ),
        (
            "sys.path_importer_cache[sys.path[2]] = object()",
            "bootstrap_importer_cache_invalid",
        ),
    ],
)
def test_fresh_isolated_import_rejects_injected_module_and_importer_cache(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    prelude = f"""
import sys
{mutation}
def _report(error_type, error, traceback):
    print(str(error))
    print(any(name == "backtrader_runtime" or name.startswith("backtrader_runtime.") for name in sys.modules))
sys.excepthook = _report
"""
    cache_prefix = tmp_path / f"pycache-contamination-{uuid.uuid4().hex}"
    result = _fresh_python(prelude + source, pycache_prefix=cache_prefix)
    assert result.returncode == 1
    assert reason in result.stdout
    assert result.stdout.rstrip().endswith("False")


def test_fixed_venv_root_mismatch_fails_before_any_runtime_import(tmp_path: Path) -> None:
    harness = r"""
import os
import pathlib
import sys
root = pathlib.Path(sys.pycache_prefix).parent / "sealed-venv-fixed"
wrong = root.parent / "different-venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
try:
    validate_fixed_venv_binding(
        venv_root=str(root),
        python_executable=str(wrong),
        python_sha256="a" * 64,
        python_version="3.11.5",
        venv_home=str(root.parent),
        actual_executable=str(wrong),
        actual_version="3.11.5",
    )
except SealedImportError as error:
    assert str(error) == "venv_executable_path_mismatch"
else:
    raise AssertionError("wrong fixed venv root was accepted")
assert not any(name == "backtrader_runtime" or name.startswith("backtrader_runtime.") for name in sys.modules)
print("fixed-venv-root-negative-passed")
"""
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    cache_prefix = tmp_path / f"pycache-venv-{uuid.uuid4().hex}"
    result = _fresh_python(source + harness, pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "fixed-venv-root-negative-passed" in result.stdout


def _lease_harness() -> str:
    return r"""
import hashlib
import os
import pathlib
import sys

original_platform = sys.platform
sys.platform = "linux"
try:
    acquire_windows_source_lease("D:\\offline-fake-root", ("module.py",))
except WindowsSourceLeaseError as error:
    assert str(error) == "windows_file_id_api_unavailable"
else:
    raise AssertionError("non-Windows lease request did not fail closed")
finally:
    sys.platform = original_platform

base = pathlib.Path(sys.pycache_prefix).parent / (pathlib.Path(sys.pycache_prefix).name + "-lease")
root_a = base / "root-a"
root_b = base / "root-b"
root_a.mkdir(parents=True)
root_b.mkdir()
for root, content in ((root_a, b"trusted source bytes\n"), (root_b, b"other source bytes\n")):
    package = root / "backtrader_runtime"
    package.mkdir()
    (package / "module.py").write_bytes(content)

source_a = root_a / "backtrader_runtime" / "module.py"
package_a = source_a.parent
root_digest = hashlib.sha256(source_a.read_bytes()).hexdigest()
lease = acquire_windows_source_lease(root_a, ("backtrader_runtime/module.py",))
assert lease.read_source("backtrader_runtime/module.py", expected_sha256=root_digest) == source_a.read_bytes()

file_key = os.path.normcase(os.path.normpath(str(source_a)))
package_key = os.path.normcase(os.path.normpath(str(package_a)))
root_key = os.path.normcase(os.path.normpath(str(root_a)))
file_entry = lease._entries[file_key]
package_entry = lease._entries[package_key]
root_entry = lease._entries[root_key]
source_b = root_b / "backtrader_runtime" / "module.py"
package_b = source_b.parent

class SameIdentityTamperApi:
    def __init__(self, entries):
        self.entries = entries
    def open(self, path, *, is_directory, lease, read_data=False):
        assert not lease
        return os.path.normcase(os.path.normpath(path))
    def attributes(self, handle):
        return _FILE_ATTRIBUTE_DIRECTORY if self.entries[handle].is_directory else 0
    def identity(self, handle):
        return self.entries[handle].identity
    def size(self, handle):
        return self.entries[handle].size
    def read(self, handle, size):
        assert size == len(b"trusted source bytes\n")
        return b"X" * size
    def close(self, handle):
        pass

tamper_probe = WindowsSourceLease(str(root_a), SameIdentityTamperApi(lease._entries))
tamper_probe._entries = dict(lease._entries)
try:
    tamper_probe.read_source("backtrader_runtime/module.py", expected_sha256=root_digest)
except WindowsSourceLeaseError as error:
    assert str(error) == "source_content_changed"
else:
    raise AssertionError("same-file-ID, same-size source tampering was accepted")

for alternate, expected in (
    (source_b, file_entry),
    (package_b, package_entry),
    (root_b, root_entry),
):
    try:
        lease._open_verified_path(alternate, expected, read_data=not expected.is_directory)
    except WindowsSourceLeaseError as error:
        assert str(error) == "source_file_identity_mismatch"
    else:
        raise AssertionError("path/file-ID swap was accepted")

for operation in (
    lambda: source_a.write_bytes(b"attacker replacement\n"),
    lambda: os.replace(source_a, package_a / "renamed.py"),
    lambda: os.replace(package_a, root_a / "renamed-package"),
    lambda: os.replace(root_a, base / "renamed-root"),
):
    try:
        operation()
    except OSError:
        pass
    else:
        raise AssertionError("write/delete/rename succeeded while lease held")

assert lease.read_source("backtrader_runtime/module.py", expected_sha256=root_digest) == b"trusted source bytes\n"
lease.close()
print("windows-source-lease-fake-checks-passed")
"""


def test_windows_source_lease_denies_writes_renames_and_detects_identity_swaps(
    tmp_path: Path,
) -> None:
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    cache_prefix = tmp_path / f"pycache-lease-{uuid.uuid4().hex}"
    result = _fresh_python(source + _lease_harness(), pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "windows-source-lease-fake-checks-passed" in result.stdout


def test_dependency_lease_lists_only_from_retained_directory_handle(tmp_path: Path) -> None:
    harness = r"""
import ctypes
import ntpath
import os
import sys

root = r"C:\\sealed-dependencies"
relative = "yaml"
target = ntpath.join(root, relative)
identity = WindowsFileIdentity(9, b"I" * 16)
calls = []
buffer_size = 64 * 1024

def write_rows(buffer, rows):
    ctypes.memset(ctypes.addressof(buffer), 0, buffer_size)
    offset = 0
    for index, (encoded, attributes, next_override) in enumerate(rows):
        row = _FileIdBothDirectoryInfo.from_buffer(buffer, offset)
        row.FileAttributes = attributes
        row.FileNameLength = len(encoded)
        name_offset = offset + _FileIdBothDirectoryInfo.FileName.offset
        ctypes.memmove(ctypes.addressof(buffer) + name_offset, encoded, len(encoded))
        if next_override is not None:
            row.NextEntryOffset = next_override
        elif index + 1 < len(rows):
            used = _FileIdBothDirectoryInfo.FileName.offset + len(encoded)
            next_offset = (used + 7) & ~7
            row.NextEntryOffset = next_offset
            offset += next_offset
        else:
            row.NextEntryOffset = 0

class FakeKernel:
    def GetFileInformationByHandleEx(self, handle, info_class, buffer, buffer_size):
        calls.append((handle, info_class))
        if info_class == _FILE_ID_BOTH_DIRECTORY_RESTART_INFO_CLASS:
            write_rows(
                buffer,
                [
                    (".".encode("utf-16-le"), _FILE_ATTRIBUTE_DIRECTORY, None),
                    ("..".encode("utf-16-le"), _FILE_ATTRIBUTE_DIRECTORY, None),
                    ("__init__.py".encode("utf-16-le"), 0, None),
                    ("行情数据".encode("utf-16-le"), 0, None),
                ],
            )
            return 1
        if info_class == _FILE_ID_BOTH_DIRECTORY_INFO_CLASS and len(calls) == 2:
            write_rows(buffer, [("native.pyd".encode("utf-16-le"), 0, None)])
            return 1
        return 0

api = object.__new__(_WindowsLeaseApi)
api.kernel32 = FakeKernel()
api.attributes = lambda handle: _FILE_ATTRIBUTE_DIRECTORY
api.identity = lambda handle: identity
original_get_last_error = ctypes.get_last_error
ctypes.get_last_error = lambda: 18
try:
    names = api.list_directory("retained-dir-handle")
finally:
    ctypes.get_last_error = original_get_last_error
assert names == ("__init__.py", "行情数据", "native.pyd")
assert calls == [
    ("retained-dir-handle", _FILE_ID_BOTH_DIRECTORY_RESTART_INFO_CLASS),
    ("retained-dir-handle", _FILE_ID_BOTH_DIRECTORY_INFO_CLASS),
    ("retained-dir-handle", _FILE_ID_BOTH_DIRECTORY_INFO_CLASS),
]

def expect_listing_error(rows, expected):
    local_calls = []
    class InvalidKernel:
        def GetFileInformationByHandleEx(self, handle, info_class, buffer, size):
            local_calls.append(info_class)
            if info_class == _FILE_ID_BOTH_DIRECTORY_RESTART_INFO_CLASS:
                write_rows(buffer, rows)
                return 1
            return 0
    invalid_api = object.__new__(_WindowsLeaseApi)
    invalid_api.kernel32 = InvalidKernel()
    invalid_api.attributes = lambda handle: _FILE_ATTRIBUTE_DIRECTORY
    invalid_api.identity = lambda handle: identity
    original_error = ctypes.get_last_error
    ctypes.get_last_error = lambda: 18
    try:
        try:
            invalid_api.list_directory("retained-dir-handle")
        except WindowsSourceLeaseError as error:
            assert str(error) == expected
        else:
            raise AssertionError(f"invalid directory entry was accepted: {expected}")
    finally:
        ctypes.get_last_error = original_error

expect_listing_error(
    [("device".encode("utf-16-le"), _FILE_ATTRIBUTE_DEVICE, None)],
    "source_directory_entry_invalid",
)
expect_listing_error([(b"\x00\xd8", 0, None)], "source_directory_entry_invalid")
expect_listing_error(
    [("x".encode("utf-16-le"), 0, 8)], "source_directory_buffer_invalid"
)
expect_listing_error(
    [("Case".encode("utf-16-le"), 0, None), ("case".encode("utf-16-le"), 0, None)],
    "source_directory_case_collision",
)
expect_listing_error([(".".encode("utf-16-le"), 0, None)], "source_directory_entry_invalid")

class FakeLeaseApi:
    def identity(self, handle):
        return identity
    def attributes(self, handle):
        return _FILE_ATTRIBUTE_DIRECTORY
    def list_directory(self, handle):
        assert handle == "retained-dir-handle"
        return names

lease = WindowsSourceLease(root, FakeLeaseApi())
key = os.path.normcase(os.path.normpath(target))
lease._entries[key] = _WindowsLeaseEntry(target, identity, True, None, "retained-dir-handle")
assert lease.list_directory(relative) == names
try:
    lease.list_directory(r"C:\\arbitrary")
except WindowsSourceLeaseError as error:
    assert str(error) == "source_relative_path_invalid"
else:
    raise AssertionError("absolute directory enumeration escaped the retained root")
print("retained-directory-handle-enumeration-passed")
"""
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    cache_prefix = tmp_path / f"pycache-directory-enumeration-{uuid.uuid4().hex}"
    result = _fresh_python(source + harness, pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "retained-directory-handle-enumeration-passed" in result.stdout


def test_windows_source_lease_lists_real_ntfs_directory_across_buffers(
    tmp_path: Path,
) -> None:
    harness = f"""
import pathlib

root = pathlib.Path({str(tmp_path)!r})
directory = root / "native-assets"
directory.mkdir()
expected = {{f"行情-{{index:04d}}-{{'x' * 90}}.data" for index in range(600)}}
for name in expected:
    (directory / name).write_bytes(b"x")
(directory / "sentinel.bin").write_bytes(b"lease")

lease = WindowsSourceLease.acquire(root, ("native-assets/sentinel.bin",))
try:
    actual = set(lease.list_directory("native-assets"))
    assert actual == expected | {{"sentinel.bin"}}
    lease.verify_current()
finally:
    lease.close()
print("real-ntfs-retained-directory-enumeration-passed")
"""
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    cache_prefix = tmp_path.parent / f"pycache-real-directory-{uuid.uuid4().hex}"
    result = _fresh_python(source + harness, pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "real-ntfs-retained-directory-enumeration-passed" in result.stdout


def test_windows_source_lease_rejects_reparse_path_swap(tmp_path: Path) -> None:
    harness = r"""
import os
import pathlib
import sys

base = pathlib.Path(sys.pycache_prefix).parent / (pathlib.Path(sys.pycache_prefix).name + "-reparse")
root = base / "root"
other = base / "other"
root.mkdir(parents=True)
other.mkdir()
(root / "module.py").write_bytes(b"sealed\n")
(other / "module.py").write_bytes(b"other\n")
lease = acquire_windows_source_lease(root, ("module.py",))
expected = lease._entries[os.path.normcase(os.path.normpath(str(root)))]
link = base / "source-link"

class ReparseApi:
    def open(self, path, *, is_directory, lease, read_data=False):
        assert is_directory and not lease and not read_data
        return object()
    def attributes(self, handle):
        return _FILE_ATTRIBUTE_REPARSE_POINT
    def close(self, handle):
        pass

fake_lease = WindowsSourceLease(str(root), ReparseApi())
try:
    fake_lease._open_verified_path(link, expected)
except WindowsSourceLeaseError as error:
    assert str(error) == "source_path_reparse_point"
else:
    raise AssertionError("fake reparse-point path was accepted")
print("windows-reparse-fake-negative-passed")

try:
    os.symlink(other, link, target_is_directory=True)
except OSError:
    print("windows-symlink-unavailable")
else:
    try:
        lease._open_verified_path(link, expected)
    except WindowsSourceLeaseError as error:
        assert str(error) == "source_path_reparse_point"
    else:
        raise AssertionError("reparse-point path was accepted")
lease.close()
print("windows-reparse-check-complete")
"""
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    cache_prefix = tmp_path / f"pycache-reparse-{uuid.uuid4().hex}"
    result = _fresh_python(source + harness, pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "windows-reparse-fake-negative-passed" in result.stdout
    assert "windows-reparse-check-complete" in result.stdout


def test_windows_source_lease_close_failure_retains_and_retries_handles(tmp_path: Path) -> None:
    harness = r"""
import pathlib
import sys

base = pathlib.Path(sys.pycache_prefix).parent / (pathlib.Path(sys.pycache_prefix).name + "-close-failure")

class CloseOnceApi:
    def __init__(self):
        self.close_calls = 0
    def close(self, handle):
        self.close_calls += 1
        if self.close_calls == 1:
            raise OSError("injected close failure")

direct_api = CloseOnceApi()
direct_lease = WindowsSourceLease(str(base), direct_api)
direct_lease._handles.append("already-closed-handle")
direct_lease._handles.append("retained-handle")
try:
    direct_lease.close()
except WindowsSourceLeaseError as error:
    assert str(error) == "source_lease_close_failed"
else:
    raise AssertionError("injected close failure was ignored")
assert direct_lease._handles == ["retained-handle"]
assert direct_api.close_calls == 2
assert direct_lease._poisoned and not direct_lease._closed
assert direct_lease in _PENDING_WINDOWS_SOURCE_LEASES
try:
    direct_lease.read_source("module.py", expected_sha256="a" * 64)
except WindowsSourceLeaseError as error:
    assert str(error) == "source_lease_poisoned"
else:
    raise AssertionError("poisoned lease still allowed reads")
direct_lease.close()
assert direct_api.close_calls == 3
assert direct_lease._closed and not direct_lease._handles
assert direct_lease not in _PENDING_WINDOWS_SOURCE_LEASES

api_instances = []
class FailAcquireApi(CloseOnceApi):
    def __init__(self):
        super().__init__()
        api_instances.append(self)
        self.open_calls = 0
    def open(self, path, *, is_directory, lease, read_data=False):
        self.open_calls += 1
        return "acquire-handle"
    def attributes(self, handle):
        raise WindowsSourceLeaseError("injected attribute failure")

original_api_class = _WindowsLeaseApi
_WindowsLeaseApi = FailAcquireApi
try:
    try:
        acquire_windows_source_lease(base / "absent-root", ("module.py",))
    except WindowsSourceLeaseError as error:
        assert str(error) == "source_lease_acquire_cleanup_failed"
    else:
        raise AssertionError("acquisition cleanup failure was ignored")
finally:
    _WindowsLeaseApi = original_api_class

assert len(api_instances) == 1 and api_instances[0].close_calls == 1
assert len(_PENDING_WINDOWS_SOURCE_LEASES) == 1
pending_lease = _PENDING_WINDOWS_SOURCE_LEASES[0]
assert pending_lease._poisoned and not pending_lease._closed
assert pending_lease._handles == ["acquire-handle"]
retry_pending_windows_source_lease_cleanup()
assert api_instances[0].close_calls == 2
assert pending_lease._closed and not pending_lease._handles
assert not _PENDING_WINDOWS_SOURCE_LEASES
print("windows-source-lease-close-failure-checks-passed")
"""
    source = _BOOTSTRAP_BYTES.decode("utf-8")
    cache_prefix = tmp_path / f"pycache-close-failure-{uuid.uuid4().hex}"
    result = _fresh_python(source + harness, pycache_prefix=cache_prefix)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "windows-source-lease-close-failure-checks-passed" in result.stdout
