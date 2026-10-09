"""Root-held caller for one credential-free M01 GateR8 lifecycle attempt.

This driver reads public source and review pins before the one-use call. The
caller installs a permanent process audit hook, so no subprocess or Git query
is made after ``run_one`` returns. Post-call Git verification is explicitly
left to the Root process outside this interpreter.
"""
import ast
import builtins
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
import uuid
import zipfile

ROOT = Path("D:/source_code/backtrader")
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
PACKET = EVIDENCE / "iteration41-okx-m01-r7-five-module-root-gate-preparation-r4-2026-10-09"
INTEGRATION_PACKET = EVIDENCE / "iteration41-okx-m01-root-helper-lifecycle-integration-r2-2026-10-09"
CALLER_RELATIVE = "scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r5.py"
CALLER_TEST_RELATIVE = "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r5_source_fake.py"
GATE_RELATIVE = "scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r8.py"
GATE_TEST_RELATIVE = "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r8.py"
INTEGRATION_SOURCE_MAP = INTEGRATION_PACKET / "source-map.json"
INTEGRATION_SOURCE_INDEX = INTEGRATION_PACKET / "source-index.json"
INTEGRATION_SOURCE_ZIP = INTEGRATION_PACKET / "source.zip"
INTEGRATION_SOURCE_MAP_RELATIVE = INTEGRATION_SOURCE_MAP.relative_to(ROOT).as_posix()
INTEGRATION_SOURCE_INDEX_RELATIVE = INTEGRATION_SOURCE_INDEX.relative_to(ROOT).as_posix()
INTEGRATION_SOURCE_ZIP_BYTES = 152448
INTEGRATION_SOURCE_ZIP_SHA256 = "55ff96b74f1d4406050ff0cd7f8cc3f9686ea17d2c16963206077cf598850877"
CUV2_SOURCE_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)
CALLER_PATH = ROOT / CALLER_RELATIVE
CU_PATH = Path("D:/temp/iteration41-root-public-custody-v2.py")
OUTPUT = EVIDENCE / "iteration41-okx-m01-r7-five-module-root-gate-actual-r5-2026-10-09"
ROOT_RESULT_PATH = ROOT / ".codex-tmp/okx_m01_r7_r5_root_actual_20261009.json"
EXPECTED_HEAD = "e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b"
GIT_EXE = Path("C:/Program Files/Git/cmd/git.exe")
EXPECTED_CALLER = (77188, "65f0cac34348f992ff960954cc31c24ed339dffb7ae1e3feee336798d15c4fcd")
EXPECTED_CALLER_TEST = (
    41797,
    "7be7b0eb8357129b1fd5ba4e88bd2f606280a2069ef95de277c12d9b8fbfd2e3",
)
EXPECTED_CU = (2344, "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246")
EXPECTED_GATE = (75279, "c8e6a4caab04d1c813f20036bed231e5d124ad1224227e25a019d8c9bbfca08f")
EXPECTED_GATE_TEST = (29972, "15c0f97ca1403edbdcd8d3d04c8536aeff1495113fa94a61c1d9c654a5bdb035")
SOURCE_MAP_BYTES = 2877
SOURCE_MAP_SHA256 = "07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3"
SOURCE_INDEX_BYTES = 9970
SOURCE_INDEX_SHA256 = "865e93b85e6811d81b58bc876c9cc6883b76d2e619725836f0737a43031417b0"
EXPECTED_SOFTWARE_PINS = {
    "C:/anaconda3/python.exe": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
    "C:/anaconda3/python311.dll": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
    "D:/temp/iteration41-root-public-custody-v2.py": "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246",
}
EXPECTED_CANDIDATE = (
    8232,
    "7afb872549da80766d1b3959bb0162e44776046f6be895a573c60c544e89dc6c",
)
EXPECTED_CALLER_REVIEW = (
    4284,
    "ea34c7cfd87d20491fe0530d0d0a9613c725e4a9aee1f630ff5cc1e743800246",
)
EXPECTED_INTEGRATION_REVIEW = EXPECTED_CALLER_REVIEW
EXPECTED_REVIEW_ARTIFACTS = [
    {
        "bytes": 4284,
        "path": (
            "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
            "iteration41-okx-m01-root-helper-lifecycle-r8-r5-independent-review-r1-2026-10-09/"
            "README.md"
        ),
        "sha256": "ea34c7cfd87d20491fe0530d0d0a9613c725e4a9aee1f630ff5cc1e743800246",
    }
]
CANDIDATE_PATH = PACKET / "candidate-pins.json"
ROOT_STATE = {"started": False, "returned": False, "exit_permitted": False}


def check(value, code):
    if not value:
        raise RuntimeError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_pinned(path, size, sha):
    check(not path.is_symlink() and path.is_file(), "source_not_regular_file")
    with path.open("rb") as stream:
        raw = stream.read(size + 1)
    check((len(raw), digest(raw)) == (size, sha), "public_pin_mismatch")
    return raw


def read_bounded_pinned(path, limit, sha):
    check(not path.is_symlink() and path.is_file(), "software_not_regular_file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    check(len(raw) <= limit and digest(raw) == sha, "software_pin_changed")
    return raw


def git(args):
    env = {
        key: os.environ[key]
        for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP")
        if key in os.environ
    }
    env["GIT_OPTIONAL_LOCKS"] = "0"
    check(
        GIT_EXE.is_file()
        and {key for key in env if key.startswith("GIT_")} == {"GIT_OPTIONAL_LOCKS"},
        "fixed_git_environment_invalid",
    )
    proc = subprocess.run(
        [str(GIT_EXE), "-C", str(ROOT), "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=True,
    )
    check(proc.stderr == b"", "git_stderr_not_empty")
    return proc.stdout.decode("utf-8").rstrip("\r\n")


def git_state():
    branch = git(["branch", "--show-current"])
    head = git(["rev-parse", "HEAD"])
    index = git(["diff", "--cached", "--name-only"])
    check(branch == "dev" and head == EXPECTED_HEAD and index == "", "git_state_changed")
    return {"branch": branch, "head": head, "index_empty": True}


def code_map(raw, origin):
    pending = [compile(raw, origin, "exec", dont_inherit=True)]
    found = {}
    while pending:
        code = pending.pop()
        found.setdefault(code.co_qualname, []).append(code)
        pending.extend(item for item in code.co_consts if type(item) is types.CodeType)
    return {key: tuple(values) for key, values in found.items()}


def immutable(value):
    if type(value) in (str, int, float, bool, bytes, type(None)):
        return (type(value), value)
    if type(value) in (tuple, list):
        return (type(value), tuple(immutable(v) for v in value))
    if type(value) in (set, frozenset):
        return (type(value), frozenset(immutable(v) for v in value))
    if type(value) is dict:
        return (dict, tuple((immutable(k), immutable(v)) for k, v in value.items()))
    return ("identity", id(value))


def verify_caller(module, raw, expected, initial=False):
    namespace = module.__dict__
    check(sys.modules.get(module.__name__) is module, "caller_alias_changed")
    check(module.__file__ == str(CALLER_PATH), "caller_origin_changed")
    check(
        module.__spec__.name == module.__name__ and module.__spec__.origin == str(CALLER_PATH),
        "caller_spec_changed",
    )
    check(namespace.get("__builtins__") is builtins.__dict__, "caller_builtins_changed")
    functions = []
    class_bindings = []

    def verify_function(fn, qualname):
        check(
            type(fn) is types.FunctionType and fn.__globals__ is namespace,
            "caller_function_globals_changed",
        )
        check(
            fn.__module__ == module.__name__ and fn.__qualname__ == qualname,
            "caller_function_metadata_changed",
        )
        check(fn.__code__ in expected.get(qualname, ()), "caller_held_code_mismatch")
        functions.append(
            (
                fn,
                fn.__code__,
                fn.__defaults__,
                fn.__kwdefaults__,
                fn.__annotations__,
                fn.__module__,
                fn.__qualname__,
                tuple(c.cell_contents for c in (fn.__closure__ or ())),
            )
        )

    for key, value in list(namespace.items()):
        if type(value) is types.FunctionType and value.__module__ == module.__name__:
            verify_function(value, key)
        elif type(value) is type and value.__module__ == module.__name__:
            class_namespace = vars(value)
            class_bindings.append((value, tuple(class_namespace.items())))
            for member, item in class_namespace.items():
                if type(item) is types.FunctionType:
                    verify_function(item, key + "." + member)
                elif type(item) in (staticmethod, classmethod):
                    verify_function(item.__func__, key + "." + member)
                elif type(item) is property:
                    for fn in (item.fget, item.fset, item.fdel):
                        if fn is not None:
                            verify_function(fn, key + "." + member)
    tree = ast.parse(raw, str(CALLER_PATH))
    literals = []
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                check(
                    namespace[alias.asname or alias.name.split(".")[0]]
                    is importlib.import_module(alias.name.split(".")[0]),
                    "caller_import_changed",
                )
        elif isinstance(statement, ast.ImportFrom) and statement.module != "__future__":
            imported = importlib.import_module(statement.module)
            for alias in statement.names:
                check(
                    namespace[alias.asname or alias.name] is getattr(imported, alias.name),
                    "caller_from_import_changed",
                )
        if isinstance(statement, ast.Assign):
            targets, node = statement.targets, statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets, node = [statement.target], statement.value
        else:
            continue
        try:
            literal = ast.literal_eval(node)
        except (ValueError, TypeError):
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if name == "_INVOCATION_STARTED":
                check(namespace[name] is (not initial), "caller_once_state_invalid")
            elif name == "_RETAINED_CONTEXTS":
                check(type(namespace[name]) is list, "caller_retention_type_changed")
                if initial:
                    check(namespace[name] == [], "caller_retention_not_fresh")
            else:
                check(immutable(namespace[name]) == immutable(literal), "caller_literal_changed")
                literals.append((name, immutable(literal)))
    check(
        namespace["ROOT"] == ROOT
        and namespace["EVIDENCE_ROOT"] == EVIDENCE
        and namespace["CURRENT_PACKET"] == INTEGRATION_PACKET
        and namespace["SOURCE_MAP_RELATIVE"] == INTEGRATION_SOURCE_MAP_RELATIVE
        and namespace["SOURCE_INDEX_RELATIVE"] == INTEGRATION_SOURCE_INDEX_RELATIVE
        and namespace["SOURCE_MAP_BYTES"] == SOURCE_MAP_BYTES
        and namespace["SOURCE_MAP_SHA256"] == SOURCE_MAP_SHA256
        and namespace["SOURCE_INDEX_BYTES"] == SOURCE_INDEX_BYTES
        and namespace["SOURCE_INDEX_SHA256"] == SOURCE_INDEX_SHA256
        and namespace["SOURCE_INDEX_ROW_COUNT"] == 26
        and namespace["GATE_RELATIVE"] == GATE_RELATIVE
        and namespace["GATE_BYTES"] == EXPECTED_GATE[0]
        and namespace["GATE_SHA256"] == EXPECTED_GATE[1]
        and namespace["GATE_TEST_RELATIVE"] == GATE_TEST_RELATIVE
        and namespace["GATE_TEST_BYTES"] == EXPECTED_GATE_TEST[0]
        and namespace["GATE_TEST_SHA256"] == EXPECTED_GATE_TEST[1]
        and namespace["CALLER_RELATIVE"] == CALLER_RELATIVE
        and namespace["CALLER_TEST_RELATIVE"] == CALLER_TEST_RELATIVE
        and namespace["ACTUAL_OUTPUT_NAME"] == OUTPUT.name
        and namespace["ROOT_PUBLIC_PIN_COUNT"] == 31
        and namespace["ROOT_SOFTWARE_PIN_COUNT"] == 3,
        "caller_computed_path_or_source_pin_changed",
    )
    return tuple(functions), tuple(literals), tuple(class_bindings)


def verify_snapshot(module, snapshot):
    functions, literals, class_bindings = snapshot
    for fn, code, defaults, kwdefaults, annotations, module_name, qualname, cells in functions:
        check(
            fn.__code__ is code
            and fn.__defaults__ is defaults
            and fn.__kwdefaults__ is kwdefaults
            and fn.__annotations__ is annotations
            and fn.__module__ == module_name
            and fn.__qualname__ == qualname,
            "caller_function_snapshot_changed",
        )
        check(
            len(fn.__closure__ or ()) == len(cells)
            and all(c.cell_contents is prior for c, prior in zip(fn.__closure__ or (), cells)),
            "caller_closure_changed",
        )
    for name, prior in literals:
        check(immutable(module.__dict__[name]) == prior, "caller_literal_snapshot_changed")
    for cls, prior_items in class_bindings:
        current = vars(cls)
        check(
            set(current) == {name for name, _value in prior_items},
            "caller_class_member_set_changed",
        )
        check(
            all(current.get(name) is value for name, value in prior_items),
            "caller_class_member_identity_changed",
        )


def precheck():
    check(not OUTPUT.exists() and not ROOT_RESULT_PATH.exists(), "root_output_not_fresh")
    before = git_state()
    manifest_raw = read_pinned(
        PACKET / "candidate-pins.json",
        *EXPECTED_CANDIDATE,
    )
    manifest = json.loads(manifest_raw)
    check(
        manifest.get("schema") == "iteration41.okx.m01.r7.root-caller-r5-candidate-pins.v1"
        and manifest.get("checkout_head") == EXPECTED_HEAD,
        "candidate_manifest_identity_mismatch",
    )
    expected_source_rows = {
        "caller": {
            "bytes": EXPECTED_CALLER[0],
            "path": CALLER_RELATIVE,
            "sha256": EXPECTED_CALLER[1],
        },
        "caller_test": {
            "bytes": EXPECTED_CALLER_TEST[0],
            "path": CALLER_TEST_RELATIVE,
            "sha256": EXPECTED_CALLER_TEST[1],
        },
        "gate": {
            "bytes": EXPECTED_GATE[0],
            "path": GATE_RELATIVE,
            "sha256": EXPECTED_GATE[1],
        },
        "gate_test": {
            "bytes": EXPECTED_GATE_TEST[0],
            "path": GATE_TEST_RELATIVE,
            "sha256": EXPECTED_GATE_TEST[1],
        },
    }
    check(
        all(manifest.get(key) == value for key, value in expected_source_rows.items()),
        "candidate_source_rows_mismatch",
    )
    expected_packet = {
        "source_map": {
            "path": INTEGRATION_SOURCE_MAP_RELATIVE,
            "bytes": SOURCE_MAP_BYTES,
            "sha256": SOURCE_MAP_SHA256,
        },
        "source_index": {
            "path": INTEGRATION_SOURCE_INDEX_RELATIVE,
            "bytes": SOURCE_INDEX_BYTES,
            "sha256": SOURCE_INDEX_SHA256,
        },
        "source_zip": {
            "path": INTEGRATION_SOURCE_ZIP.relative_to(ROOT).as_posix(),
            "bytes": INTEGRATION_SOURCE_ZIP_BYTES,
            "sha256": INTEGRATION_SOURCE_ZIP_SHA256,
        },
    }
    check(manifest.get("integration_packet") == expected_packet, "integration_packet_pin_mismatch")
    check(manifest.get("software_pins") == EXPECTED_SOFTWARE_PINS, "software_pin_manifest_mismatch")
    check(manifest.get("review_artifacts") == EXPECTED_REVIEW_ARTIFACTS, "review_manifest_mismatch")
    source_map_raw = read_pinned(INTEGRATION_SOURCE_MAP, SOURCE_MAP_BYTES, SOURCE_MAP_SHA256)
    source_index_raw = read_pinned(INTEGRATION_SOURCE_INDEX, SOURCE_INDEX_BYTES, SOURCE_INDEX_SHA256)
    source_zip_raw = read_pinned(
        INTEGRATION_SOURCE_ZIP,
        INTEGRATION_SOURCE_ZIP_BYTES,
        INTEGRATION_SOURCE_ZIP_SHA256,
    )
    source_map = json.loads(source_map_raw.decode("ascii"))
    source_index = json.loads(source_index_raw.decode("ascii"))
    check(
        source_map.get("schema") == "iteration41.okx.m01.case-source-map.v3"
        and type(source_map.get("source_pins")) is dict
        and len(source_map["source_pins"]) == 19,
        "source_map_shape_invalid",
    )
    check(
        source_index.get("schema")
        == "iteration41.okx.m01.root-helper-lifecycle-integration-source-index.v1"
        and source_index.get("source_map_file_sha256") == SOURCE_MAP_SHA256
        and source_index.get("source_map_sha256") == SOURCE_MAP_SHA256
        and source_index.get("source_map_bytes") == SOURCE_MAP_BYTES
        and source_index.get("runtime_source_count") == 19
        and source_index.get("archive_member_count") == 26
        and type(source_index.get("rows")) is list
        and len(source_index["rows"]) == 26,
        "source_index_shape_invalid",
    )
    indexed_rows = source_index["rows"]
    indexed = {row["path"]: row for row in indexed_rows if type(row) is dict}
    check(len(indexed) == 26, "source_index_duplicate_path")
    runtime_rows = {
        path: row for path, row in indexed.items() if row.get("role") == "runtime_source"
    }
    check(set(runtime_rows) == set(source_map["source_pins"]), "source_map_runtime_set_mismatch")
    check(
        all(
            source_map["source_pins"].get(path) == row.get("sha256")
            and type(row.get("bytes")) is int
            and row["bytes"] >= 0
            for path, row in runtime_rows.items()
        ),
        "source_map_index_rows_mismatch",
    )
    with zipfile.ZipFile(io.BytesIO(source_zip_raw)) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        check(
            len(members) == 26
            and len(names) == len(set(names))
            and set(names) == set(indexed),
            "source_archive_member_set_mismatch",
        )
        for member in members:
            member_path = Path(member.filename)
            check(
                not member_path.is_absolute()
                and ".." not in member_path.parts
                and "\\" not in member.filename,
                "source_archive_member_path_invalid",
            )
        for row in indexed_rows:
            raw_member = archive.read(row["path"])
            check(
                type(row.get("bytes")) is int
                and type(row.get("sha256")) is str
                and len(raw_member) == row["bytes"]
                and digest(raw_member) == row["sha256"],
                "source_archive_row_mismatch",
            )

    rows = manifest.get("public_pins")
    check(
        type(rows) is list
        and len(rows) == 31
        and all(type(row) is dict for row in rows)
        and len({row.get("path") for row in rows}) == 31,
        "public_count_wrong",
    )
    by_path = {row["path"]: row for row in rows}
    expected_extras = {
        INTEGRATION_SOURCE_MAP_RELATIVE: (SOURCE_MAP_BYTES, SOURCE_MAP_SHA256),
        INTEGRATION_SOURCE_INDEX_RELATIVE: (SOURCE_INDEX_BYTES, SOURCE_INDEX_SHA256),
        CUV2_SOURCE_RELATIVE: EXPECTED_CU,
        CALLER_RELATIVE: EXPECTED_CALLER,
        CALLER_TEST_RELATIVE: EXPECTED_CALLER_TEST,
    }
    expected_paths = set(indexed) | set(expected_extras)
    check(
        len(expected_paths) == 31 and set(by_path) == expected_paths,
        "public_pin_set_not_exact",
    )
    for path, row in indexed.items():
        check(
            by_path[path].get("bytes") == row.get("bytes")
            and by_path[path].get("sha256") == row.get("sha256"),
            "indexed_public_pin_mismatch",
        )
    for path, pin in expected_extras.items():
        check(
            (by_path[path].get("bytes"), by_path[path].get("sha256")) == pin,
            "support_public_pin_mismatch",
        )
    public_rows = rows
    check(
        len(public_rows) == 31 and len({row["path"] for row in public_rows}) == 31,
        "r5_public_count_wrong",
    )
    check(
        CALLER_RELATIVE in {row["path"] for row in public_rows}
        and CALLER_TEST_RELATIVE in {row["path"] for row in public_rows},
        "r5_caller_rows_missing",
    )
    public_raw = {
        row["path"]: read_pinned(ROOT / row["path"], row["bytes"], row["sha256"])
        for row in public_rows
    }
    public_pins = {row["path"]: row["sha256"] for row in public_rows}
    caller_raw = public_raw[CALLER_RELATIVE]
    check(
        len(public_raw[CALLER_TEST_RELATIVE]) == EXPECTED_CALLER_TEST[0]
        and digest(public_raw[CALLER_TEST_RELATIVE]) == EXPECTED_CALLER_TEST[1],
        "r5_caller_test_pin_changed",
    )
    cu_raw = read_pinned(CU_PATH, *EXPECTED_CU)
    check(
        cu_raw == public_raw[CUV2_SOURCE_RELATIVE],
        "cuv2_snapshot_changed",
    )
    software = dict(EXPECTED_SOFTWARE_PINS)
    software_limits = {
        "C:/anaconda3/python.exe": 92160,
        "C:/anaconda3/python311.dll": 5991424,
        str(CU_PATH).replace(chr(92), "/"): EXPECTED_CU[0],
    }
    for path, sha in software.items():
        if path == str(CU_PATH).replace(chr(92), "/"):
            software_raw = cu_raw
        else:
            software_raw = read_bounded_pinned(Path(path), software_limits[path], sha)
        check(digest(software_raw) == sha, "software_pin_changed")
    review_raws = {}
    for row in EXPECTED_REVIEW_ARTIFACTS:
        review_raws[row["path"]] = read_pinned(
            ROOT / row["path"], row["bytes"], row["sha256"]
        )
    expected = code_map(caller_raw, str(CALLER_PATH))
    check(git_state() == before, "precheck_git_changed")
    return (
        before,
        public_rows,
        public_raw,
        public_pins,
        caller_raw,
        cu_raw,
        software,
        expected,
        manifest_raw,
        source_zip_raw,
        review_raws,
    )


PRECHECK = precheck()
ROOT_STATE["precheck"] = {
    "public_count": 31,
    "software_count": 3,
    "held_count": 34,
    "caller_bytes": EXPECTED_CALLER[0],
    "caller_sha256": EXPECTED_CALLER[1],
    "caller_test_sha256": EXPECTED_CALLER_TEST[1],
    "gate_sha256": EXPECTED_GATE[1],
    "gate_test_sha256": EXPECTED_GATE_TEST[1],
    "source_map_sha256": SOURCE_MAP_SHA256,
    "source_index_sha256": SOURCE_INDEX_SHA256,
    "source_zip_sha256": INTEGRATION_SOURCE_ZIP_SHA256,
    "candidate_manifest_sha256": EXPECTED_CANDIDATE[1],
    "caller_review_sha256": EXPECTED_CALLER_REVIEW[1],
    "integration_review_sha256": EXPECTED_INTEGRATION_REVIEW[1],
    "git_pre_call": PRECHECK[0],
}
print(json.dumps({"phase": "ROOT_PRECHECK_PASSED", **ROOT_STATE["precheck"]}), flush=True)
if "--precheck" not in sys.argv:
    (
        before,
        public_rows,
        public_raw,
        public_pins,
        caller_raw,
        cu_raw,
        software,
        expected,
        manifest_raw,
        source_zip_raw,
        review_raws,
    ) = PRECHECK
    nonce = uuid.uuid4().hex
    caller_name = "_root_m01_r7_r5_caller_" + nonce[:12]
    caller = types.ModuleType(caller_name)
    caller.__file__ = str(CALLER_PATH)
    caller.__package__ = ""
    caller.__spec__ = importlib.util.spec_from_file_location(caller_name, CALLER_PATH)
    sys.modules[caller_name] = caller
    exec(compile(caller_raw, str(CALLER_PATH), "exec", dont_inherit=True), caller.__dict__)
    root_binding = verify_caller(caller, caller_raw, expected, initial=True)
    caller_globals = dict(caller.__dict__)
    retained_registry = caller._RETAINED_CONTEXTS
    cu_name = "_root_m01_r7_r5_cuv2_" + nonce[:12]
    cu = types.ModuleType(cu_name)
    cu.__file__ = str(CU_PATH)
    cu.__package__ = ""
    cu.__spec__ = importlib.util.spec_from_file_location(cu_name, CU_PATH)
    sys.modules[cu_name] = cu
    exec(compile(cu_raw, str(CU_PATH), "exec", dont_inherit=True), cu.__dict__)
    ROOT_STATE.update(
        caller=caller,
        cu=cu,
        root_binding=root_binding,
        nonce=nonce,
        retained_registry=retained_registry,
        started=True,
    )
    started = time.monotonic()
    ACTUAL_RESULT = caller.run_one(
        cu,
        cuv2_source_raw=cu_raw,
        public_pins=public_pins,
        software_pins=software,
        root_nonce=nonce,
        output_dir=OUTPUT,
        root=ROOT,
    )
    ROOT_STATE["returned"] = True
    verify_caller(caller, caller_raw, expected, initial=False)
    verify_snapshot(caller, root_binding)
    check(set(caller.__dict__) == set(caller_globals), "caller_global_set_changed")
    check(
        all(
            caller.__dict__[k] is v for k, v in caller_globals.items() if k != "_INVOCATION_STARTED"
        ),
        "caller_global_identity_changed",
    )
    check(caller._RETAINED_CONTEXTS is retained_registry, "root_retention_rebound")
    for row in public_rows:
        check(
            read_pinned(ROOT / row["path"], row["bytes"], row["sha256"])
            == public_raw[row["path"]],
            "public_post_pin_changed",
        )
    check(
        read_pinned(
            CANDIDATE_PATH,
            *EXPECTED_CANDIDATE,
        )
        == manifest_raw,
        "candidate_manifest_post_pin_changed",
    )
    check(
        read_pinned(
            INTEGRATION_SOURCE_ZIP,
            INTEGRATION_SOURCE_ZIP_BYTES,
            INTEGRATION_SOURCE_ZIP_SHA256,
        )
        == source_zip_raw,
        "source_archive_post_pin_changed",
    )
    for row in EXPECTED_REVIEW_ARTIFACTS:
        check(
            read_pinned(ROOT / row["path"], row["bytes"], row["sha256"])
            == review_raws[row["path"]],
            "review_artifact_post_pin_changed",
        )
    receipt = {
        "schema": "iteration41.okx.m01.r7.r5.root-actual.v1",
        "evidence_level": "ROOT_ACTUAL_CREDENTIAL_FREE_LOCAL_LIFECYCLE_ONLY",
        "elapsed_seconds": time.monotonic() - started,
        "public_pin_count": 31,
        "software_pin_count": 3,
        "held_pin_count": 34,
        "candidate_manifest_sha256": EXPECTED_CANDIDATE[1],
        "gate_sha256": EXPECTED_GATE[1],
        "gate_test_sha256": EXPECTED_GATE_TEST[1],
        "caller_review_sha256": EXPECTED_CALLER_REVIEW[1],
        "integration_review_sha256": EXPECTED_INTEGRATION_REVIEW[1],
        "source_map_sha256": SOURCE_MAP_SHA256,
        "source_index_sha256": SOURCE_INDEX_SHA256,
        "source_zip_sha256": INTEGRATION_SOURCE_ZIP_SHA256,
        "caller_module_function_binding_count": len(root_binding[0]),
        "caller_module_literal_binding_count": len(root_binding[1]),
        "caller_module_class_binding_count": len(root_binding[2]),
        "root_caller_source_bindings_pre_post_verified": True,
        "source_bytes_pre_post_unchanged": True,
        "git_pre_call": before,
        "git_post_call_verification": {
            "status": "PENDING_OUTSIDE_HOST",
            "verified": False,
        },
        "result": ACTUAL_RESULT,
        "formal_m01_pass_count": 0,
    }
    success_receipt = bool(
        ACTUAL_RESULT.get("host_exit_permitted") is True
        and ACTUAL_RESULT.get("status") == "LOCAL_SYNTHETIC_CHILD"
        and ACTUAL_RESULT.get("outer_normal_postverify_and_close") is True
        and ACTUAL_RESULT.get("scope_exit_confirmed") is True
        and ACTUAL_RESULT.get("gate_invocations") == 1
        and ACTUAL_RESULT.get("source_count") == 34
        and ACTUAL_RESULT.get("public_source_count") == 31
        and ACTUAL_RESULT.get("software_source_count") == 3
        and ACTUAL_RESULT.get("source_pre_post_bindings_verified") is True
        and ACTUAL_RESULT.get("gate_cleanup_facts_verified") is True
        and ACTUAL_RESULT.get("software_pins_verified_by_cuv2") is True
        and ACTUAL_RESULT.get("software_payload_bytes_returned_to_caller") is True
        and ACTUAL_RESULT.get("software_payload_bytes_retained_in_caller_state") is True
        and ACTUAL_RESULT.get("software_payload_bytes_sha256_rechecked_by_caller") is True
        and ACTUAL_RESULT.get("account_provider_operations") is False
        and ACTUAL_RESULT.get("private_inputs_read") is False
        and ACTUAL_RESULT.get("formal_m01_pass_count") == 0
        and retained_registry == []
    )
    receipt["caller_scope_clean"] = success_receipt
    receipt["root_host_exit_permitted"] = False
    receipt["root_host_exit_state"] = "PENDING_OUTSIDE_HOST_GIT_POSTVERIFY"
    ROOT_RESULT_PATH.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    ROOT_STATE["exit_permitted"] = False
    print(
        json.dumps(
            {
                "phase": "ROOT_ACTUAL_RETURNED",
                "elapsed_seconds": receipt["elapsed_seconds"],
                "status": ACTUAL_RESULT["status"],
                "reason": ACTUAL_RESULT.get("reason"),
                "failure_phase": ACTUAL_RESULT.get("failure_phase"),
                "gate_invocations": ACTUAL_RESULT["gate_invocations"],
                "gate_cleanup_facts_verified": ACTUAL_RESULT["gate_cleanup_facts_verified"],
                "outer_normal_postverify_and_close": ACTUAL_RESULT[
                    "outer_normal_postverify_and_close"
                ],
                "git_post_call_verification": "PENDING_OUTSIDE_HOST",
                "exit_permitted": ROOT_STATE["exit_permitted"],
            }
        ),
        flush=True,
    )
