#!/usr/bin/env python
"""Build pinned research wheels and verify them outside the source checkout.

Wheels come from Git archive snapshots and are installed into a fresh target
or prefix. Isolated-mode Python processes import the project wheels from that
install while using the Anaconda base environment's runtime dependencies;
this is not a dependency-isolated environment. External test and example
copies run without importing the live source checkout. Use the Anaconda base
interpreter and provide frozen source commits.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import sysconfig
import tarfile
from typing import Any, Dict, List, Mapping, Sequence, Tuple
import xml.etree.ElementTree as ET
import zipfile

BASE_PYTHON = Path("/Users/yunjinqi/opt/anaconda3/bin/python").resolve()
_TEST_INPUTS = (
    "tests/integration/test_factor_research_installed_representatives.py",
    "tests/integration/test_alpha101_native_installed.py",
    "tests/test_utils/alpha101_full_reference.py",
    "tests/test_utils/alpha101_native_harness.py",
    "tests/test_utils/alpha101_trace_validation.py",
    "tests/unit/test_factor_research_representatives.py",
    "tests/fixtures/research/alpha101_dependencies.json",
)
_FACTOR_MODE_PAIR_TEST_INPUTS = (
    "tests/unit/test_factor_build_expression.py",
    "tests/unit/test_factor_research_examples.py",
)
_PAIR_SEMANTICS_HELPER = "scripts/verify_factor_research_pair_semantics.py"
_EXAMPLE_DIRS = (
    "examples/backtest/025_factor_single",
    "examples/backtest/026_factor_multi",
    "examples/backtest/027_alpha003_panel_acceptance",
)
_ARCHIVE_PATHS = {
    "backtrader": (
        "setup.py",
        "pyproject.toml",
        "README.md",
        "backtrader",
        "backtrader_runtime",
        *_TEST_INPUTS,
        *_EXAMPLE_DIRS,
    ),
    "fincore": (
        "setup.py",
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "NOTICE",
        "THIRD_PARTY_NOTICES.md",
        "THIRD_PARTY_LICENSES/Apache-2.0.txt",
        "fincore",
    ),
}
_FACTOR_MODE_PAIR_ARCHIVE_PATHS = (
    *_FACTOR_MODE_PAIR_TEST_INPUTS,
    _PAIR_SEMANTICS_HELPER,
)
_PAIR_FORMULA_TEST_CASES = {
    "Alpha003": ("test_alpha003_degenerate_recovery_missing_bar_nan_trace_and_reason_pair",),
    "CloseMA": ("test_025_close_ma_build_matches_native_and_independent_oracle",),
    "ROC": ("test_026_roc_build_matches_native_and_independent_oracle",),
    "KDJ": ("test_026_kdj_build_matches_native_oracle_and_all_intermediate_lines",),
}
_PAIR_ENGINE_MODES = ("runnext", "runonce")
_PAIR_MODULE_NAME = "factor_research_installed_pair_semantics"
_ALPHA_BATCHES = {"promoted_20", "a", "b", "c", "d", "e"}
_PACKAGE_ROOTS = ("backtrader/", "backtrader_runtime/", "fincore/")
_EXPECTED_SYMBOLS = 20
_EXPECTED_DATES = 243
_EVALUATION_CSVS = frozenset(
    {
        "comparisons.csv",
        "correlation.csv",
        "coverage.csv",
        "diagnostics.csv",
        "ic.csv",
        "ic_summary.csv",
        "labels.csv",
        "quantile_returns.csv",
        "signals.csv",
        "spreads.csv",
        "stability.csv",
        "turnover.csv",
    }
)
_EVALUATION_PNGS = frozenset({"ic_series.png", "quantile_returns.png"})
_PANEL_CSVS = frozenset(
    {
        "factors.csv",
        "grid.csv",
        "groups.csv",
        "prices_close.csv",
        "prices_open.csv",
        "universe.csv",
    }
)


class VerificationError(RuntimeError):
    """Raised when an installed artifact or one of its consumers fails."""


def _archive_paths(name: str, *, factor_mode_pair: bool = False) -> Tuple[str, ...]:
    try:
        paths = _ARCHIVE_PATHS[name]
    except KeyError as exc:
        raise VerificationError("no bounded archive path set for %s" % name) from exc
    if factor_mode_pair and name == "backtrader":
        return (*paths, *_FACTOR_MODE_PAIR_ARCHIVE_PATHS)
    return paths


def _verify_pair_formula_test_witnesses(junit_xml: Path) -> Mapping[str, Any]:
    if not junit_xml.is_file():
        raise VerificationError("factor-mode-pair pytest report is missing: %s" % junit_xml)
    try:
        root = ET.parse(junit_xml).getroot()
    except (ET.ParseError, OSError) as exc:
        raise VerificationError(
            "cannot read factor-mode-pair pytest report: %s" % junit_xml
        ) from exc

    cases: Dict[str, List[ET.Element]] = {}
    for case in root.iter("testcase"):
        name = case.get("name")
        if isinstance(name, str):
            cases.setdefault(name, []).append(case)

    witnesses: Dict[str, Any] = {}
    missing = []
    for formula, test_names in _PAIR_FORMULA_TEST_CASES.items():
        formula_witnesses = []
        for test_name in test_names:
            for engine in _PAIR_ENGINE_MODES:
                prefix = test_name + "["
                candidates = {
                    name: matched_cases
                    for name, matched_cases in cases.items()
                    if name.startswith(prefix)
                    and engine in name[len(prefix) : -1].replace("_", "-").split("-")
                }
                if not candidates:
                    missing.append("%s[%s]" % (test_name, engine))
                    continue
                passing = []
                for node_id, matches in candidates.items():
                    if len(matches) != 1:
                        raise VerificationError(
                            "factor formula test case is duplicated in JUnit report: %s" % node_id
                        )
                    testcase = matches[0]
                    outcomes = [
                        child.tag
                        for child in testcase
                        if child.tag in {"failure", "error", "skipped"}
                    ]
                    if outcomes:
                        raise VerificationError(
                            "required build formula engine case did not pass: %s (%s)"
                            % (node_id, ",".join(outcomes))
                        )
                    passing.append(node_id)
                formula_witnesses.append(
                    {
                        "test_case": sorted(passing)[0],
                        "engine_mode": engine,
                        "passed_test_cases": sorted(passing),
                    }
                )
        if formula_witnesses:
            witnesses[formula] = formula_witnesses
    if missing:
        raise VerificationError(
            "factor-mode-pair run omitted required formula/engine cases: %s"
            % ", ".join(sorted(missing))
        )
    if set(witnesses) != set(_PAIR_FORMULA_TEST_CASES):
        raise VerificationError("factor-mode-pair run lacks a complete four-formula witness set")
    for formula, formula_witnesses in witnesses.items():
        if {item["engine_mode"] for item in formula_witnesses} != set(_PAIR_ENGINE_MODES):
            raise VerificationError("%s does not have both required engine witnesses" % formula)
    return witnesses


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(
    command: Sequence[str | Path], *, cwd: Path | None = None, env=None
) -> subprocess.CompletedProcess:
    print("+", " ".join(str(value) for value in command), flush=True)
    try:
        return subprocess.run(
            [str(value) for value in command],
            cwd=None if cwd is None else str(cwd),
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, end="" if exc.stdout.endswith("\n") else "\n")
        raise VerificationError("command failed with exit %d" % exc.returncode) from exc


def _require_base_python() -> None:
    if Path(sys.executable).resolve() != BASE_PYTHON:
        raise VerificationError(
            "run with %s (for example, conda run -n base python ...)" % BASE_PYTHON
        )


def _full_commit(repo: Path, value: str, name: str) -> str:
    if len(value) not in (40, 64) or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise VerificationError("%s commit must be a full lowercase Git object ID" % name)
    resolved = _run(["git", "-C", repo, "rev-parse", "%s^{commit}" % value]).stdout.strip()
    if resolved != value:
        raise VerificationError("%s commit does not resolve to the supplied full object ID" % name)
    return resolved


def _extract_archive(
    repo: Path,
    commit: str,
    destination: Path,
    name: str,
    *,
    factor_mode_pair: bool = False,
) -> Tuple[Path, str]:
    destination.mkdir(parents=True)
    archive = destination / (name + ".tar")
    archive_paths = _archive_paths(name, factor_mode_pair=factor_mode_pair)
    command = ["git", "-C", str(repo), "archive", "--format=tar", commit, *archive_paths]
    print("+", " ".join(command), ">", archive, flush=True)
    with archive.open("wb") as output:
        subprocess.run(command, check=True, stdout=output, stderr=subprocess.PIPE)
    source = destination / "source"
    source.mkdir()
    with tarfile.open(archive, "r:") as bundle:
        for member in bundle.getmembers():
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise VerificationError("unsafe Git archive path: %s" % member.name)
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise VerificationError("unsupported Git archive entry: %s" % member.name)
        bundle.extractall(source)
    if name == "backtrader":
        missing_files = [relative for relative in _TEST_INPUTS if not (source / relative).is_file()]
        if factor_mode_pair:
            missing_files.extend(
                relative
                for relative in _FACTOR_MODE_PAIR_TEST_INPUTS
                if not (source / relative).is_file()
            )
            if not (source / _PAIR_SEMANTICS_HELPER).is_file():
                missing_files.append(_PAIR_SEMANTICS_HELPER)
        missing_dirs = [relative for relative in _EXAMPLE_DIRS if not (source / relative).is_dir()]
        if missing_files or missing_dirs:
            raise VerificationError(
                "pinned Backtrader archive is missing required acceptance inputs "
                "(files=%r, directories=%r)" % (missing_files, missing_dirs)
            )
    return source, _sha256(archive)


def _build_wheel(
    repo: Path,
    commit: str,
    name: str,
    evidence: Path,
    *,
    factor_mode_pair: bool = False,
) -> Tuple[Path, Path, str]:
    source, archive_hash = _extract_archive(
        repo,
        commit,
        evidence / "archives" / name,
        name,
        factor_mode_pair=factor_mode_pair,
    )
    wheel_dir = evidence / "wheels"
    wheel_dir.mkdir(exist_ok=True)
    before = set(wheel_dir.glob("*.whl"))
    result = _run(
        [
            BASE_PYTHON,
            "-I",
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--no-cache-dir",
            "--wheel-dir",
            wheel_dir,
            source,
        ],
        cwd=source,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    new_wheels = set(wheel_dir.glob("*.whl")) - before
    if len(new_wheels) != 1:
        raise VerificationError(
            "%s archive built %d wheels; expected one" % (name, len(new_wheels))
        )
    return source, new_wheels.pop(), archive_hash


def _wheel_record_rows(wheel: Path) -> List[Tuple[str, str, str]]:
    with zipfile.ZipFile(wheel) as archive:
        records = [name for name in archive.namelist() if name.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise VerificationError("%s must contain one RECORD" % wheel.name)
        with archive.open(records[0]) as stream:
            rows = list(csv.reader(io.TextIOWrapper(stream, encoding="utf-8", newline="")))
    return [(row[0], row[1], row[2]) for row in rows]


def _installed_record_path(record_path: str, install_root: Path) -> Path | None:
    parts = PurePosixPath(record_path).parts
    if len(parts) >= 3 and parts[0].endswith(".data") and parts[1] in ("purelib", "platlib"):
        relative = Path(*parts[2:])
    elif len(parts) >= 2 and parts[0].endswith(".data"):
        return None
    else:
        relative = Path(*parts)
    return install_root / relative


def _verify_wheel_payload(wheel: Path, install_root: Path, source_root: Path) -> Mapping[str, int]:
    checked_wheel = checked_install = checked_source = 0
    packaged_sources = set()
    with zipfile.ZipFile(wheel) as archive:
        member_names = archive.namelist()
        if len(member_names) != len(set(member_names)):
            raise VerificationError("wheel contains duplicate ZIP members: %s" % wheel.name)
        payload_members = {name for name in member_names if not name.endswith("/")}
        record_rows = _wheel_record_rows(wheel)
        record_paths = [record_path for record_path, _, _ in record_rows]
        if len(record_paths) != len(set(record_paths)):
            raise VerificationError("wheel RECORD contains duplicate paths: %s" % wheel.name)
        if set(record_paths) != payload_members:
            raise VerificationError(
                "wheel members and RECORD paths differ in %s: unrecorded=%r absent=%r"
                % (
                    wheel.name,
                    sorted(payload_members - set(record_paths)),
                    sorted(set(record_paths) - payload_members),
                )
            )
        for record_path, encoded_hash, encoded_size in record_rows:
            try:
                payload = archive.read(record_path)
            except KeyError as exc:
                raise VerificationError(
                    "RECORD entry is absent from %s: %s" % (wheel.name, record_path)
                ) from exc
            installed = _installed_record_path(record_path, install_root)
            if not encoded_hash:
                if not record_path.endswith(".dist-info/RECORD"):
                    raise VerificationError("wheel payload lacks a RECORD hash: %s" % record_path)
                continue
            algorithm, expected = encoded_hash.split("=", 1)
            if algorithm != "sha256":
                raise VerificationError(
                    "unsupported RECORD digest %s in %s" % (algorithm, wheel.name)
                )
            actual = (
                base64.urlsafe_b64encode(hashlib.sha256(payload).digest())
                .decode("ascii")
                .rstrip("=")
            )
            if actual != expected or str(len(payload)) != encoded_size:
                raise VerificationError("wheel RECORD hash/size mismatch: %s" % record_path)
            checked_wheel += 1
            if record_path.startswith(_PACKAGE_ROOTS):
                source_file = source_root / Path(*PurePosixPath(record_path).parts)
                if not source_file.is_file():
                    raise VerificationError(
                        "wheel payload has no matching archive source: %s" % record_path
                    )
                if source_file.read_bytes() != payload:
                    raise VerificationError(
                        "wheel payload differs from pinned archive source: %s" % record_path
                    )
                packaged_sources.add(record_path)
                checked_source += 1
            if installed is None:
                continue
            if not installed.is_file():
                raise VerificationError("installed wheel payload is absent: %s" % installed)
            installed_bytes = installed.read_bytes()
            installed_digest = (
                base64.urlsafe_b64encode(hashlib.sha256(installed_bytes).digest())
                .decode("ascii")
                .rstrip("=")
            )
            if installed_digest != expected or str(len(installed_bytes)) != encoded_size:
                raise VerificationError(
                    "installed payload differs from wheel RECORD: %s" % installed
                )
            checked_install += 1
    source_python = {
        path.relative_to(source_root).as_posix()
        for package_root in _PACKAGE_ROOTS
        for path in (source_root / package_root.rstrip("/")).rglob("*.py")
    }
    packaged_python = {path for path in packaged_sources if path.endswith(".py")}
    if packaged_python != source_python:
        missing = sorted(source_python - packaged_python)
        extra = sorted(packaged_python - source_python)
        raise VerificationError(
            "wheel Python payload differs from archive sources (missing=%r, extra=%r)"
            % (missing[:10], extra[:10])
        )
    return {
        "wheel_payloads": checked_wheel,
        "installed_payloads": checked_install,
        "archive_source_payloads": checked_source,
    }


def _install_root(args: argparse.Namespace, evidence: Path) -> Tuple[Path, str]:
    if args.target:
        root = args.target.expanduser().resolve()
        if root.exists() and any(root.iterdir()):
            raise VerificationError("--target must name a new or empty directory")
        root.mkdir(parents=True, exist_ok=True)
        return root, "target"
    if args.prefix:
        prefix = args.prefix.expanduser().resolve()
        if prefix.exists() and any(prefix.iterdir()):
            raise VerificationError("--prefix must name a new or empty directory")
        prefix.mkdir(parents=True, exist_ok=True)
        purelib = Path(
            sysconfig.get_path("purelib", vars={"base": str(prefix), "platbase": str(prefix)})
        )
        purelib.mkdir(parents=True, exist_ok=True)
        return purelib, "prefix"
    root = evidence / "fresh-target"
    root.mkdir()
    return root.resolve(), "target"


def _verify_imports(install_root: Path, evidence: Path) -> Mapping[str, Any]:
    code = r"""
import importlib, importlib.metadata, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import backtrader, fincore
modules = {
    "backtrader": backtrader,
    "backtrader.research.alpha101": importlib.import_module("backtrader.research.alpha101"),
    "fincore": fincore,
    "fincore.factor_analysis.research": importlib.import_module("fincore.factor_analysis.research"),
}
origins = {name: str(pathlib.Path(module.__file__).resolve()) for name, module in modules.items()}
for name, origin in origins.items():
    if not pathlib.Path(origin).is_relative_to(root):
        raise SystemExit("%s loaded outside project wheel install root: %s" % (name, origin))
versions = {
    "backtrader": importlib.metadata.version("back-trader-python"),
    "fincore": importlib.metadata.version("fincore"),
}
module_versions = {"backtrader": backtrader.__version__, "fincore": fincore.__version__}
if module_versions != versions:
    raise SystemExit("module versions differ from installed wheel metadata: %r != %r" % (module_versions, versions))
print(json.dumps({"origins": origins, "versions": versions, "module_versions": module_versions}))
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = _run([BASE_PYTHON, "-I", "-c", code, install_root], env=env)
    data = json.loads(result.stdout.strip().splitlines()[-1])
    (evidence / "installed-origins.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return data


def _copy_external_tests(
    bt_source: Path, external: Path, *, factor_mode_pair: bool = False
) -> None:
    test_inputs = (
        (*_TEST_INPUTS, *_FACTOR_MODE_PAIR_TEST_INPUTS) if factor_mode_pair else _TEST_INPUTS
    )
    for relative in test_inputs:
        source = bt_source / relative
        if not source.is_file():
            raise VerificationError("pinned archive lacks test input: %s" % relative)
        destination = external / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for package in ("tests", "tests/integration", "tests/test_utils", "tests/unit"):
        (external / package / "__init__.py").touch(exist_ok=True)
    if factor_mode_pair:
        _copy_examples(bt_source, external / "examples", preserve_backtest_layout=True)


def _copy_external_pair_helper(bt_source: Path, external: Path) -> Path:
    source = bt_source / _PAIR_SEMANTICS_HELPER
    if not source.is_file():
        raise VerificationError("pinned archive lacks pair-semantics helper: %s" % source)
    destination = external / "scripts" / Path(_PAIR_SEMANTICS_HELPER).name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination.resolve()


def _load_pair_semantics_helper(helper_path: Path, external: Path):
    helper_path = helper_path.expanduser().resolve()
    external = external.expanduser().resolve()
    if not helper_path.is_relative_to(external):
        raise VerificationError(
            "pair-semantics helper must be loaded from the external archive copy"
        )
    spec = importlib.util.spec_from_file_location(_PAIR_MODULE_NAME, helper_path)
    if spec is None or spec.loader is None:
        raise VerificationError("cannot load pinned pair-semantics helper: %s" % helper_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_PAIR_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(_PAIR_MODULE_NAME, None)
        raise VerificationError("cannot initialize pinned pair-semantics helper: %s" % exc) from exc
    if not callable(getattr(module, "compare_runs", None)):
        raise VerificationError("pinned pair-semantics helper has no compare_runs API")
    if not callable(getattr(module, "capture_report_semantics", None)):
        raise VerificationError("pinned pair-semantics helper has no report capture API")
    return module


def _run_installed_tests(
    external: Path,
    install_root: Path,
    provenance: Path,
    evidence: Path,
    *,
    factor_mode_pair: bool = False,
) -> Mapping[str, Any]:
    code = r"""
import sys
import pathlib
install_root, external_root, baseline, pair_junit = sys.argv[1:5]
factor_mode_pair = sys.argv[5] == "1"
sys.path[:0] = [install_root, external_root]
import backtrader, fincore, pytest
install = pathlib.Path(install_root).resolve()
for name, package in (("backtrader", backtrader), ("fincore", fincore)):
    if not pathlib.Path(package.__file__).resolve().is_relative_to(install):
        raise SystemExit("%s loaded outside installed wheel root" % name)
test_paths = [
    "-q", "--disable-warnings", "--basetemp", baseline,
    "--rootdir", external_root, "--confcutdir", external_root,
    external_root + "/tests/integration/test_factor_research_installed_representatives.py",
    external_root + "/tests/integration/test_alpha101_native_installed.py",
]
if factor_mode_pair:
    test_paths.extend([
        external_root + "/tests/unit/test_factor_build_expression.py",
        external_root + "/tests/unit/test_factor_research_examples.py",
        "--junitxml", pair_junit,
    ])
raise SystemExit(pytest.main(test_paths))
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("BT_ALPHA101_NATIVE_BATCHES", None)
    env.pop("BT_ALPHA101_NATIVE_IDS", None)
    env.update(
        {
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "BT_FACTOR_RESEARCH_RUN_INSTALLED_INTEGRATION": "1",
            "BT_ALPHA101_NATIVE_INSTALLED_ACCEPTANCE": "1",
            "BT_ALPHA101_NATIVE_PROVENANCE_JSON": str(provenance.resolve()),
            "BT_FACTOR_RESEARCH_INSTALLED_ROOTS": json.dumps([str(install_root.resolve())]),
        }
    )
    baseline = evidence / "pytest-basetemp"
    baseline.mkdir()
    junit_xml = evidence / "factor-mode-pair-tests.xml"
    result = _run(
        [
            BASE_PYTHON,
            "-I",
            "-c",
            code,
            install_root,
            external,
            baseline,
            junit_xml,
            "1" if factor_mode_pair else "0",
        ],
        cwd=evidence,
        env=env,
    )
    log = result.stdout
    print(log, end="" if log.endswith("\n") else "\n")
    (evidence / "installed-tests.log").write_text(log, encoding="utf-8")
    records = []
    covered_alpha_ids = set()
    for path in baseline.rglob("alpha101-native-installed-acceptance.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        batch = record["selected_batch"]
        engine = record["selected_engine_mode"]
        batch_ids = record["selected_batch_alpha_ids"]
        if record["trace_validation"]["formula_count"] != len(batch_ids):
            raise VerificationError("Alpha101 trace omitted one or more formulas: %s" % batch)
        records.append((batch, engine))
        covered_alpha_ids.update(batch_ids)
    expected = {(batch, mode) for batch in _ALPHA_BATCHES for mode in ("runnext", "runonce")}
    if set(records) != expected or len(records) != len(expected):
        raise VerificationError("installed Alpha101 did not produce all 12 batch/mode records")
    if covered_alpha_ids != set(range(1, 102)):
        raise VerificationError(
            "installed Alpha101 batches did not cover exactly the full registry"
        )
    representative_records = list(baseline.rglob("installed-acceptance.json"))
    if len(representative_records) != 1:
        raise VerificationError("representative CSV reevaluation record is missing")
    return {
        "pytest_log": str((evidence / "installed-tests.log").resolve()),
        "alpha101_records": len(records),
        "engine_modes": ["runnext", "runonce"],
        "batches": sorted(_ALPHA_BATCHES),
        "representative_record": str(representative_records[0].resolve()),
        **(
            {
                "factor_mode_pair_junit_xml": str(junit_xml.resolve()),
                "factor_mode_pair_formula_witnesses": _verify_pair_formula_test_witnesses(
                    junit_xml
                ),
            }
            if factor_mode_pair
            else {}
        ),
    }


def _copy_examples(
    bt_source: Path, destination: Path, *, preserve_backtest_layout: bool = False
) -> Mapping[str, Path]:
    copied: Dict[str, Path] = {}
    for relative in _EXAMPLE_DIRS:
        source = bt_source / relative
        if not source.is_dir():
            raise VerificationError("pinned archive lacks example directory %s" % relative)
        target = destination / Path(relative).name
        if preserve_backtest_layout:
            target = destination / "backtest" / Path(relative).name
            target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        copied[Path(relative).name] = target
    return copied


def _require_report_semantics(
    output: Path, *, expected_reports: int | None = None
) -> Mapping[str, Any]:
    sidecar = output / "report_semantics.json"
    if not sidecar.is_file():
        raise VerificationError("captured report semantics are missing: %s" % sidecar)
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerificationError("captured report semantics are invalid: %s" % sidecar) from exc
    reports = data.get("reports") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("schema_version"), str)
        or not data["schema_version"]
        or not isinstance(reports, list)
        or not reports
    ):
        raise VerificationError("captured report semantics has an invalid schema: %s" % sidecar)
    if expected_reports is not None and len(reports) != expected_reports:
        raise VerificationError(
            "captured report semantics contains %d reports; expected %d"
            % (len(reports), expected_reports)
        )
    for report in reports:
        if not isinstance(report, dict):
            raise VerificationError("captured report semantics contains an invalid report row")
        html_path = report.get("html_path")
        html_hash = report.get("html_sha256")
        semantic_digest = report.get("semantic_digest")
        semantic_payload = report.get("semantic_payload")
        if (
            not isinstance(html_path, str)
            or not html_path
            or not isinstance(html_hash, str)
            or len(html_hash) != 64
            or not isinstance(semantic_digest, str)
            or len(semantic_digest) != 64
            or not isinstance(semantic_payload, dict)
        ):
            raise VerificationError("captured report semantics report payload is incomplete")
        html = Path(html_path)
        if not html.is_absolute():
            html = output / html
        if not html.is_file() or _sha256(html) != html_hash:
            raise VerificationError("captured report HTML hash does not match its file: %s" % html)
    return data


def _run_example(
    script: Path,
    example_dir: Path,
    install_root: Path,
    args: Sequence[str],
    evidence: Path,
    *,
    output_dir: Path | None = None,
    pair_helper: Path | None = None,
    external_test_root: Path | None = None,
    expected_report_count: int | None = None,
) -> str:
    if pair_helper is not None:
        if output_dir is None or external_test_root is None:
            raise VerificationError(
                "report capture needs an output directory and external helper root"
            )
        if (
            not pair_helper.expanduser()
            .resolve()
            .is_relative_to(external_test_root.expanduser().resolve())
        ):
            raise VerificationError("report capture helper must come from the pinned external copy")
    code = r"""
import importlib, importlib.util, pathlib, runpy, sys
install_root, example_dir, script, output_dir, helper_path = sys.argv[1:6]
arguments = sys.argv[6:]
install_root = pathlib.Path(install_root).resolve()
sys.path[:0] = [str(install_root), example_dir]
for name in ("backtrader", "fincore"):
    package = importlib.import_module(name)
    origin = pathlib.Path(package.__file__).resolve()
    if not origin.is_relative_to(install_root):
        raise SystemExit("%s loaded outside installed wheel root: %s" % (name, origin))
if helper_path:
    spec = importlib.util.spec_from_file_location("factor_research_installed_pair_semantics", helper_path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load pinned pair-semantics helper: " + helper_path)
    helper = importlib.util.module_from_spec(spec)
    sys.modules["factor_research_installed_pair_semantics"] = helper
    spec.loader.exec_module(helper)
    with helper.capture_report_semantics(output_dir):
        module = runpy.run_path(script, run_name="factor_research_installed_example")
        status = module["main"](arguments)
        if status not in (None, 0):
            raise SystemExit(status)
else:
    module = runpy.run_path(script, run_name="factor_research_installed_example")
    raise SystemExit(module["main"](arguments))
"""
    output_arg = "" if output_dir is None else output_dir.expanduser().resolve()
    helper_arg = "" if pair_helper is None else pair_helper.expanduser().resolve()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = _run(
        [
            BASE_PYTHON,
            "-I",
            "-c",
            code,
            install_root,
            example_dir,
            script,
            output_arg,
            helper_arg,
            *args,
        ],
        cwd=evidence,
        env=env,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if pair_helper is not None:
        _require_report_semantics(output_dir, expected_reports=expected_report_count)
    return result.stdout


def _require_evaluation_export(output: Path, *, charts: bool) -> Mapping[str, Any]:
    evaluation_dir = output / "evaluation"
    if not evaluation_dir.is_dir():
        raise VerificationError("example did not export evaluation tables: %s" % output)
    exports = [path for path in evaluation_dir.iterdir() if path.is_dir()]
    if len(exports) != 1:
        raise VerificationError(
            "expected one evaluation export directory under %s" % evaluation_dir
        )
    export = exports[0]
    actual_names = {path.name for path in export.iterdir() if path.is_file()}
    expected_names = set(_EVALUATION_CSVS) | {"manifest.json"}
    if charts:
        expected_names.update(_EVALUATION_PNGS)
    if actual_names != expected_names:
        raise VerificationError(
            "evaluation export has incomplete or unexpected files: missing=%r extra=%r"
            % (sorted(expected_names - actual_names), sorted(actual_names - expected_names))
        )
    for name in sorted(expected_names):
        path = export / name
        if path.stat().st_size == 0:
            raise VerificationError("evaluation export is empty: %s" % path)
    for name in _EVALUATION_PNGS if charts else ():
        if not (export / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise VerificationError("evaluation chart is not a PNG: %s" % (export / name))
    manifest = _read_evaluation_manifest(export)
    return {
        "directory": str(export.resolve()),
        "csv_files": sorted(_EVALUATION_CSVS),
        "png_files": sorted(_EVALUATION_PNGS) if charts else [],
        "result_fingerprint": manifest["result_fingerprint"],
        "table_rows": manifest["table_rows"],
    }


def _read_evaluation_manifest(export: Path) -> Mapping[str, Any]:
    manifest = json.loads((export / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "OK":
        raise VerificationError("evaluation manifest status is not OK: %s" % export)
    fingerprint = manifest.get("result_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise VerificationError("evaluation manifest has no result_fingerprint: %s" % export)
    declared_exports = manifest.get("exports")
    if (
        not isinstance(declared_exports, list)
        or not all(isinstance(name, str) for name in declared_exports)
        or len(declared_exports) != len(set(declared_exports))
        or set(declared_exports)
        != {path.name for path in export.iterdir() if path.is_file()} - {"manifest.json"}
    ):
        raise VerificationError("evaluation manifest exports differ from files: %s" % export)
    tables = manifest.get("tables")
    expected_tables = {Path(name).stem for name in _EVALUATION_CSVS}
    if not isinstance(tables, dict) or set(tables) != expected_tables:
        raise VerificationError("evaluation manifest table inventory is incomplete: %s" % export)

    table_rows: Dict[str, int] = {}
    for name in sorted(_EVALUATION_CSVS):
        table = tables[Path(name).stem]
        if not isinstance(table, dict):
            raise VerificationError("invalid evaluation table metadata for %s" % name)
        with (export / name).open("r", encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise VerificationError("evaluation CSV has no header: %s" % name) from exc
            if header != table.get("columns"):
                raise VerificationError("evaluation CSV columns differ from manifest: %s" % name)
            row_count = sum(1 for _ in reader)
        if table.get("rows") != row_count:
            raise VerificationError(
                "evaluation CSV row count differs from manifest for %s: %d != %r"
                % (name, row_count, table.get("rows"))
            )
        table_rows[name] = row_count
    return {"result_fingerprint": fingerprint, "table_rows": table_rows}


def _require_completed_example(
    output: Path,
    *,
    multi: bool = False,
    panel_expected: bool = False,
    expected_factor_mode: str | None = None,
    expected_factor_classes: Mapping[str, str] | None = None,
    require_report_semantics: bool = False,
) -> Mapping[str, Any]:
    summary_path = output / "summary.json"
    if not summary_path.is_file():
        raise VerificationError("example did not write %s" % summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "COMPLETED" or summary.get("evaluation_status") != "OK":
        raise VerificationError("example did not complete an OK evaluation: %s" % summary)
    if not summary.get("evaluation_id"):
        raise VerificationError("example summary has no evaluation_id")
    if summary.get("symbols") != _EXPECTED_SYMBOLS or summary.get("dates") != _EXPECTED_DATES:
        raise VerificationError(
            "example used unexpected dimensions: symbols=%r dates=%r"
            % (summary.get("symbols"), summary.get("dates"))
        )
    if expected_factor_mode is not None:
        if summary.get("factor_mode") != expected_factor_mode:
            raise VerificationError(
                "example factor_mode differs from requested mode: %r != %r"
                % (summary.get("factor_mode"), expected_factor_mode)
            )
        expected_calculation = "NOT_RUN" if expected_factor_mode == "NOT_APPLICABLE" else "RAN"
        if summary.get("factor_calculation") != expected_calculation:
            raise VerificationError(
                "example factor_calculation differs from requested mode: %r != %r"
                % (summary.get("factor_calculation"), expected_calculation)
            )
    if expected_factor_classes is not None and summary.get("factor_classes") != dict(
        expected_factor_classes
    ):
        raise VerificationError(
            "example factor class identities differ: %r != %r"
            % (summary.get("factor_classes"), dict(expected_factor_classes))
        )
    reports = summary.get("reports") if multi else [summary.get("report")]
    expected_report_count = 3 if multi else 1
    if (
        not reports
        or len(reports) != expected_report_count
        or not all(path and Path(path).is_file() for path in reports)
    ):
        raise VerificationError("example report was not written: %s" % output)
    if require_report_semantics:
        semantics = _require_report_semantics(output, expected_reports=expected_report_count)
        expected_paths = {Path(path).expanduser().resolve() for path in reports}
        semantic_paths = set()
        for report in semantics["reports"]:
            path = Path(report["html_path"])
            semantic_paths.add((path if path.is_absolute() else output / path).resolve())
        if expected_paths != semantic_paths:
            raise VerificationError(
                "report semantics paths differ from the example summary: %r != %r"
                % (sorted(map(str, semantic_paths)), sorted(map(str, expected_paths)))
            )
    factor_values = output / "factor_values.csv"
    if not factor_values.is_file():
        raise VerificationError("example did not export factor_values.csv: %s" % output)
    with factor_values.open("r", encoding="utf-8", newline="") as stream:
        rows = sum(1 for _ in csv.DictReader(stream))
    expected_rows = _EXPECTED_SYMBOLS * _EXPECTED_DATES
    if rows != expected_rows:
        raise VerificationError(
            "factor_values.csv has %d rows; expected %d" % (rows, expected_rows)
        )
    evaluation = _require_evaluation_export(output, charts=True)
    panel_files = []
    if panel_expected:
        panel = output / "panel"
        panel_files = sorted(path.name for path in panel.iterdir() if path.is_file())
        if set(panel_files) != _PANEL_CSVS:
            raise VerificationError("example CSV panel is incomplete: %s" % panel_files)
    return {**summary, "evaluation_artifacts": evaluation, "panel_csv_files": panel_files}


def _expected_example_factor_classes(example_name: str, mode: str) -> Mapping[str, str]:
    if mode not in ("native", "build"):
        if mode == "NOT_APPLICABLE":
            return {}
        raise VerificationError("unsupported expected factor mode: %s" % mode)
    if example_name == "025_factor_single":
        class_name = "CloseMAFactor" if mode == "native" else "CloseMAFactorBuild"
        return {"close_ma": "close_ma_factor_strategy." + class_name}
    if example_name == "026_factor_multi":
        suffix = "" if mode == "native" else "Build"
        return {
            name: "multi_factor_strategy." + class_name + suffix
            for name, class_name in (
                ("close_ma", "CloseMAFactor"),
                ("kdj_j", "KDJFactor"),
                ("roc", "ROCFactor"),
            )
        }
    raise VerificationError("no factor class contract for example %s" % example_name)


def _compare_paired_runs(
    helper,
    left: Path,
    right: Path,
    *,
    label: str,
    require_reports: bool,
    require_mode_pair: bool,
    require_panel_pair: bool,
) -> Mapping[str, Any]:
    try:
        result = helper.compare_runs(
            left,
            right,
            require_reports=require_reports,
            require_mode_pair=require_mode_pair,
            require_panel_pair=require_panel_pair,
        )
    except Exception as exc:
        raise VerificationError("%s pair comparison failed: %s" % (label, exc)) from exc
    if not isinstance(result, Mapping) or result.get("strict_equal") is not True:
        status = result.get("status") if isinstance(result, Mapping) else None
        raise VerificationError("%s pair comparison was not accepted: %r" % (label, status))
    return result


def _run_025_026(
    examples: Mapping[str, Path],
    install_root: Path,
    data_dir: Path,
    evidence: Path,
    *,
    factor_mode_pair: bool = False,
    pair_helper=None,
    pair_helper_path: Path | None = None,
    external_test_root: Path | None = None,
) -> Mapping[str, Any]:
    if factor_mode_pair:
        if pair_helper is None or pair_helper_path is None or external_test_root is None:
            raise VerificationError(
                "factor-mode-pair requires the pinned external comparison helper"
            )
        return _run_025_026_mode_pair(
            examples,
            install_root,
            data_dir,
            evidence,
            pair_helper=pair_helper,
            pair_helper_path=pair_helper_path,
            external_test_root=external_test_root,
        )
    reports: Dict[str, Any] = {}
    for name in ("025_factor_single", "026_factor_multi"):
        example = examples[name]
        script = example / "run.py"
        full_output = evidence / "example-results" / (name + "-full")
        panel_output = evidence / "example-results" / (name + "-csv-reeval")
        full_output.parent.mkdir(exist_ok=True)
        common = ["--data-dir", str(data_dir), "--max-symbols", "20"]
        _run_example(
            script,
            example,
            install_root,
            ["--output-dir", str(full_output), *common, "--save-panel", "--report"],
            evidence,
        )
        full = _require_completed_example(
            full_output, multi=name.startswith("026"), panel_expected=True
        )
        _run_example(
            script,
            example,
            install_root,
            [
                "--output-dir",
                str(panel_output),
                *common,
                "--panel",
                str(full_output / "panel"),
                "--report",
            ],
            evidence,
        )
        restored = _require_completed_example(panel_output, multi=name.startswith("026"))
        if restored["evaluation_id"] != full["evaluation_id"]:
            raise VerificationError(
                "%s CSV reevaluation evaluation_id differs from full run" % name
            )
        full_evaluation = full["evaluation_artifacts"]
        restored_evaluation = restored["evaluation_artifacts"]
        if restored_evaluation["result_fingerprint"] != full_evaluation["result_fingerprint"]:
            raise VerificationError(
                "%s CSV reevaluation result_fingerprint differs from full run" % name
            )
        if restored_evaluation["table_rows"] != full_evaluation["table_rows"]:
            raise VerificationError(
                "%s CSV reevaluation table row counts differ from full run" % name
            )
        reports[name] = {
            "symbols": full["symbols"],
            "dates": full["dates"],
            "evaluation_id": full["evaluation_id"],
            "csv_reevaluation_id": restored["evaluation_id"],
            "result_fingerprint": full_evaluation["result_fingerprint"],
            "evaluation_table_rows": full_evaluation["table_rows"],
            "reports": full.get("reports", [full.get("report")]),
        }
    return reports


def _run_025_026_mode_pair(
    examples: Mapping[str, Path],
    install_root: Path,
    data_dir: Path,
    evidence: Path,
    *,
    pair_helper,
    pair_helper_path: Path,
    external_test_root: Path,
) -> Mapping[str, Any]:
    reports: Dict[str, Any] = {}
    for name in ("025_factor_single", "026_factor_multi"):
        example = examples[name]
        script = example / "run.py"
        multi = name == "026_factor_multi"
        report_count = 3 if multi else 1
        full_runs: Dict[str, Mapping[str, Any]] = {}
        restored_runs: Dict[str, Mapping[str, Any]] = {}
        csv_comparisons: Dict[str, Any] = {}
        for mode in ("native", "build"):
            full_output = evidence / "example-results" / (name + "-" + mode)
            panel_output = evidence / "example-results" / (name + "-" + mode + "-csv-reeval")
            full_output.parent.mkdir(exist_ok=True)
            common = ["--data-dir", str(data_dir), "--max-symbols", "20"]
            _run_example(
                script,
                example,
                install_root,
                [
                    "--output-dir",
                    str(full_output),
                    *common,
                    "--factor-mode",
                    mode,
                    "--save-panel",
                    "--report",
                ],
                evidence,
                output_dir=full_output,
                pair_helper=pair_helper_path,
                external_test_root=external_test_root,
                expected_report_count=report_count,
            )
            full = _require_completed_example(
                full_output,
                multi=multi,
                panel_expected=True,
                expected_factor_mode=mode,
                expected_factor_classes=_expected_example_factor_classes(name, mode),
                require_report_semantics=True,
            )
            _run_example(
                script,
                example,
                install_root,
                [
                    "--output-dir",
                    str(panel_output),
                    *common,
                    "--panel",
                    str(full_output / "panel"),
                    "--report",
                ],
                evidence,
                output_dir=panel_output,
                pair_helper=pair_helper_path,
                external_test_root=external_test_root,
                expected_report_count=report_count,
            )
            restored = _require_completed_example(
                panel_output,
                multi=multi,
                expected_factor_mode="NOT_APPLICABLE",
                expected_factor_classes={},
                require_report_semantics=True,
            )
            if restored["evaluation_id"] != full["evaluation_id"]:
                raise VerificationError(
                    "%s %s CSV reevaluation evaluation_id differs from full run" % (name, mode)
                )
            full_evaluation = full["evaluation_artifacts"]
            restored_evaluation = restored["evaluation_artifacts"]
            if restored_evaluation["result_fingerprint"] != full_evaluation["result_fingerprint"]:
                raise VerificationError(
                    "%s %s CSV reevaluation result_fingerprint differs from full run" % (name, mode)
                )
            if restored_evaluation["table_rows"] != full_evaluation["table_rows"]:
                raise VerificationError(
                    "%s %s CSV reevaluation table row counts differ from full run" % (name, mode)
                )
            csv_comparisons[mode] = _compare_paired_runs(
                pair_helper,
                full_output,
                panel_output,
                label="%s %s full-to-CSV" % (name, mode),
                require_reports=True,
                require_mode_pair=False,
                require_panel_pair=False,
            )
            full_runs[mode] = full
            restored_runs[mode] = restored

        mode_comparison = _compare_paired_runs(
            pair_helper,
            evidence / "example-results" / (name + "-native"),
            evidence / "example-results" / (name + "-build"),
            label="%s native-to-build" % name,
            require_reports=True,
            require_mode_pair=True,
            require_panel_pair=True,
        )
        native = full_runs["native"]
        reports[name] = {
            "symbols": native["symbols"],
            "dates": native["dates"],
            "factor_modes": ["native", "build"],
            "factor_classes": {
                mode: full_runs[mode]["factor_classes"] for mode in ("native", "build")
            },
            "evaluation_ids": {
                mode: full_runs[mode]["evaluation_id"] for mode in ("native", "build")
            },
            "csv_reevaluation_ids": {
                mode: restored_runs[mode]["evaluation_id"] for mode in ("native", "build")
            },
            "evaluation_fingerprints": {
                mode: full_runs[mode]["evaluation_artifacts"]["result_fingerprint"]
                for mode in ("native", "build")
            },
            "evaluation_table_rows": {
                mode: full_runs[mode]["evaluation_artifacts"]["table_rows"]
                for mode in ("native", "build")
            },
            "native_build_comparison": mode_comparison,
            "full_to_csv_comparisons": csv_comparisons,
            "reports": native.get("reports", [native.get("report")]),
        }
    return reports


def _write_027_probe(external_dir: Path) -> Path:
    probe = external_dir / "verify_027_csv_reevaluation.py"
    probe.write_text(
        r"""from __future__ import annotations
import csv, importlib, importlib.util, json, math, pathlib, runpy, sys
import pandas as pd

install_root, example_dir, data_dir, output_dir = map(pathlib.Path, sys.argv[1:5])
factor_mode, helper_path = sys.argv[5:7]
output_dir = output_dir.resolve()
install_root = install_root.resolve()
sys.path[:0] = [str(install_root), str(example_dir.resolve())]
for package_name in ("backtrader", "fincore"):
    package = importlib.import_module(package_name)
    if not pathlib.Path(package.__file__).resolve().is_relative_to(install_root):
        raise SystemExit("%s loaded outside installed wheel root" % package_name)
main_args = ["--data-dir", str(data_dir.resolve()), "--max-symbols", "20",
             "--output-dir", str(output_dir), "--report"]
if factor_mode:
    main_args.extend(["--factor-mode", factor_mode])
if helper_path:
    spec = importlib.util.spec_from_file_location(
        "factor_research_installed_pair_semantics", helper_path
    )
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load pinned pair-semantics helper")
    helper = importlib.util.module_from_spec(spec)
    sys.modules["factor_research_installed_pair_semantics"] = helper
    spec.loader.exec_module(helper)
    with helper.capture_report_semantics(output_dir):
        module = runpy.run_path(
            str(example_dir / "run.py"), run_name="factor_research_027_acceptance"
        )
        if module["main"](main_args) != 0:
            raise SystemExit("027 runner failed")
else:
    module = runpy.run_path(
        str(example_dir / "run.py"), run_name="factor_research_027_acceptance"
    )
    if module["main"](main_args) != 0:
        raise SystemExit("027 runner failed")

# Check the installed runner's own mode summary before replaying its collector.
# Legacy pinned archives do not yet write mode fields, so only the opt-in mode
# profile imposes this contract.
summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
if (summary.get("status") != "COMPLETED" or summary.get("symbols") != 20
        or summary.get("dates") != 243):
    raise SystemExit("027 runner summary has unexpected completion dimensions")
if factor_mode:
    expected_indicator = (
        "backtrader.research.alpha101.alpha003.Alpha003Native"
        if factor_mode == "native"
        else "backtrader.research.alpha101.alpha003.Alpha003Build"
    )
    if (summary.get("factor_mode") != factor_mode
            or summary.get("factor_calculation") != "RAN"
            or summary.get("indicator") != expected_indicator):
        raise SystemExit("027 runner mode or indicator identity differs from requested mode")

# This bootstrap/mode-summary section is exercised independently by the unit
# suite; the remaining probe replays the collector and checks CSV artifacts.
config = module["_load_config"]()
config["data"]["directory"] = str(data_dir.resolve())
config["data"]["max_symbols"] = 20
if factor_mode:
    config["factor_mode"] = factor_mode
source = module["load_daily_panel"](config["data"])
_, collected, indicator = module["_run_factor"](config, source)
if len(collected.target_order) != 20 or len(collected.grid) != 243:
    raise SystemExit("027 did not use exactly 20 symbols x 243 dates")
saved_values = pd.read_csv(output_dir / "factor_values.csv", float_precision="round_trip")
expected_values = collected.factors.reset_index()
if len(saved_values) != 20 * 243:
    raise SystemExit("027 factor_values.csv has an unexpected row count")
if list(saved_values.columns) != list(expected_values.columns):
    raise SystemExit("027 exported factor columns differ from collected panel")
if saved_values["asset"].tolist() != expected_values["asset"].tolist():
    raise SystemExit("027 exported asset order differs from collected panel")
if pd.to_datetime(saved_values["time"]).tolist() != pd.to_datetime(expected_values["time"]).tolist():
    raise SystemExit("027 exported grid differs from collected panel")
pd.testing.assert_series_equal(
    saved_values["alpha003"],
    expected_values["alpha003"],
    check_dtype=False,
    check_exact=True,
)

from backtrader.research import FactorPanel, evaluate_frames
from fincore.factor_analysis.research import ResearchEvaluationSpec
panel_path = output_dir / "factor-panel"
collected.to_csv(panel_path)
restored = FactorPanel.from_csv(
    panel_path,
    start=collected.start,
    end=collected.end,
    directions={"alpha003": 1},
    target_order=collected.target_order,
    factor_order=("alpha003",),
    groups=collected.groups,
)
for frame_name in ("factors", "grid", "prices_open", "prices_close", "universe"):
    pd.testing.assert_frame_equal(
        getattr(restored, frame_name), getattr(collected, frame_name), check_exact=True
    )
if (restored.target_order, restored.factor_order, restored.directions, restored.groups) != (
    collected.target_order,
    collected.factor_order,
    collected.directions,
    collected.groups,
):
    raise SystemExit("027 CSV panel metadata changed during round trip")
data = config["data"]
spec = ResearchEvaluationSpec(
    targets=restored.target_order,
    start=restored.start,
    end=restored.end,
    snapshot_id=data["snapshot_id"],
    price_basis=data["price_basis"],
    calendar_id=data["calendar_id"],
    frequency=data["frequency"],
    source_timezone=data["source_timezone"],
    feed_time_kind="close_time",
    periods=(1,),
    label="next_open_to_open",
    precomputed_entry="next_open",
    min_assets=2,
    quantiles=1,
    min_quantile_assets=1,
    preprocess="cross_section_rank",
    stability_lags=(1,),
    max_loss=1.0,
)
result = evaluate_frames(restored, spec)
status = str(getattr(result.status, "value", result.status)).upper()
if status != "OK":
    raise SystemExit("027 CSV evaluation status is %s" % status)
reevaluation = output_dir / "csv-reevaluation"
result.export(reevaluation, charts=False)
if factor_mode:
    expected_indicator = indicator.__module__ + "." + indicator.__qualname__
    if summary.get("indicator") != expected_indicator:
        raise SystemExit("027 runner mode or indicator identity differs from collected factor")
if (int(summary.get("finite", 0)) <= 0
        or not any(math.isfinite(float(value)) for value in collected.factors["alpha003"])):
    raise SystemExit("027 factor output has no finite witness")
if not summary.get("report") or not pathlib.Path(summary["report"]).is_file():
    raise SystemExit("027 runner did not write its report")
export_dirs = [path for path in reevaluation.iterdir() if path.is_dir()]
if len(export_dirs) != 1:
    raise SystemExit("027 evaluation did not produce one export directory")
export_dir = export_dirs[0]
evaluation_files = {path.name for path in export_dir.iterdir() if path.is_file()}
expected_evaluation_files = {
    "comparisons.csv", "correlation.csv", "coverage.csv", "diagnostics.csv",
    "ic.csv", "ic_summary.csv", "labels.csv", "manifest.json",
    "quantile_returns.csv", "signals.csv", "spreads.csv", "stability.csv", "turnover.csv",
}
if evaluation_files != expected_evaluation_files:
    raise SystemExit("027 evaluation CSV export is incomplete: %r" % sorted(evaluation_files))
if any((export_dir / name).stat().st_size == 0 for name in expected_evaluation_files):
    raise SystemExit("027 evaluation export contains an empty table")
manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
expected_csv_files = expected_evaluation_files - {"manifest.json"}
declared_exports = manifest.get("exports")
if (not isinstance(declared_exports, list)
        or not all(isinstance(name, str) for name in declared_exports)
        or len(declared_exports) != len(set(declared_exports))
        or set(declared_exports) != expected_csv_files):
    raise SystemExit("027 evaluation manifest exports are incomplete")
expected_table_names = {pathlib.Path(name).stem for name in expected_csv_files}
tables = manifest.get("tables")
if not isinstance(tables, dict) or set(tables) != expected_table_names:
    raise SystemExit("027 evaluation manifest table inventory is incomplete")
table_rows = {}
for name in sorted(expected_csv_files):
    table = tables[pathlib.Path(name).stem]
    if not isinstance(table, dict):
        raise SystemExit("027 evaluation manifest has invalid table metadata for %s" % name)
    with (export_dir / name).open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        try:
            header = next(reader)
        except StopIteration:
            raise SystemExit("027 evaluation CSV has no header: %s" % name)
        if header != table.get("columns"):
            raise SystemExit("027 evaluation CSV columns differ from manifest: %s" % name)
        row_count = sum(1 for _ in reader)
    if table.get("rows") != row_count:
        raise SystemExit("027 evaluation CSV row count differs from manifest: %s" % name)
    table_rows[name] = row_count
if manifest.get("status") != "OK" or manifest.get("result_fingerprint") != result.manifest.get("result_fingerprint"):
    raise SystemExit("027 evaluation manifest status/fingerprint differs from result")
panel_files = {path.name for path in panel_path.iterdir() if path.is_file()}
expected_panel_files = {
    "factors.csv", "grid.csv", "groups.csv", "prices_close.csv", "prices_open.csv", "universe.csv"
}
if panel_files != expected_panel_files:
    raise SystemExit("027 CSV factor panel is incomplete: %r" % sorted(panel_files))
payload = {
    "status": status,
    "factor_mode": summary.get("factor_mode"),
    "indicator": summary.get("indicator"),
    "symbols": len(restored.target_order),
    "dates": len(restored.grid),
    "factor_csv_cells": len(saved_values),
    "report": summary["report"],
    "csv_panel_files": sorted(panel_files),
    "evaluation_fingerprint": result.manifest.get("result_fingerprint"),
    "evaluation_table_rows": table_rows,
    "evaluation_export_directory": str(export_dir),
    "evaluation_exports": sorted(evaluation_files),
}
if len(restored.target_order) != 20 or len(restored.grid) != 243 or not payload["evaluation_fingerprint"]:
    raise SystemExit("027 CSV reevaluation outputs are incomplete")
(output_dir / "csv-reevaluation-summary.json").write_text(
    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(payload, sort_keys=True))
""",
        encoding="utf-8",
    )
    return probe


def _run_027(
    example: Path,
    install_root: Path,
    data_dir: Path,
    evidence: Path,
    *,
    factor_mode_pair: bool = False,
    pair_helper=None,
    pair_helper_path: Path | None = None,
    external_test_root: Path | None = None,
) -> Mapping[str, Any]:
    if factor_mode_pair and (
        pair_helper is None or pair_helper_path is None or external_test_root is None
    ):
        raise VerificationError("factor-mode-pair requires the pinned external comparison helper")
    probe = _write_027_probe(evidence)

    def run_one(output: Path, mode: str = "") -> Mapping[str, Any]:
        output.parent.mkdir(exist_ok=True)
        helper_argument = pair_helper_path if factor_mode_pair else ""
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = _run(
            [
                BASE_PYTHON,
                "-I",
                probe,
                install_root,
                example,
                data_dir,
                output,
                mode,
                helper_argument,
            ],
            cwd=evidence,
            env=env,
        )
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        if factor_mode_pair:
            if payload.get("factor_mode") != mode:
                raise VerificationError("027 %s result has unexpected factor mode" % mode)
            expected_indicator = (
                "backtrader.research.alpha101.alpha003.Alpha003Native"
                if mode == "native"
                else "backtrader.research.alpha101.alpha003.Alpha003Build"
            )
            if payload.get("indicator") != expected_indicator:
                raise VerificationError(
                    "027 %s result has unexpected factor class: %r"
                    % (mode, payload.get("indicator"))
                )
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            semantics = _require_report_semantics(output, expected_reports=1)
            expected_path = Path(summary["report"]).resolve()
            actual_path = Path(semantics["reports"][0]["html_path"])
            if (
                actual_path if actual_path.is_absolute() else output / actual_path
            ).resolve() != expected_path:
                raise VerificationError("027 report semantics path differs from runner summary")
        return payload

    if not factor_mode_pair:
        output = evidence / "example-results" / "027_alpha003_panel_acceptance"
        return run_one(output)

    mode_reports = {}
    for mode in ("native", "build"):
        output = evidence / "example-results" / ("027_alpha003_panel_acceptance-" + mode)
        mode_reports[mode] = run_one(output, mode)
    comparison = _compare_paired_runs(
        pair_helper,
        evidence / "example-results" / "027_alpha003_panel_acceptance-native",
        evidence / "example-results" / "027_alpha003_panel_acceptance-build",
        label="027 Alpha003 native-to-build",
        require_reports=True,
        require_mode_pair=True,
        require_panel_pair=False,
    )
    return {
        "factor_modes": ["native", "build"],
        "formula": "Alpha003",
        "mode_results": mode_reports,
        "native_build_comparison": comparison,
    }


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backtrader-commit", required=True, help="full frozen Backtrader Git commit"
    )
    parser.add_argument("--fincore-commit", required=True, help="full frozen fincore Git commit")
    parser.add_argument("--backtrader-repo", type=Path, default=root)
    parser.add_argument("--fincore-repo", type=Path, default=root.parent / "fincore")
    parser.add_argument(
        "--evidence-dir", type=Path, required=True, help="new directory for wheels and evidence"
    )
    parser.add_argument("--data-dir", type=Path, default=root / "tests" / "datas" / "a_stocks")
    parser.add_argument(
        "--symbols", type=int, default=20, help="copied example symbol count (fixed at 20)"
    )
    parser.add_argument(
        "--factor-mode-pair",
        action="store_true",
        help=(
            "also run the Iteration 47 build-formula profile: four formula pairs, "
            "both engines, reports, panels, and CSV reevaluation"
        ),
    )
    install = parser.add_mutually_exclusive_group()
    install.add_argument("--target", type=Path, help="fresh pip --target directory")
    install.add_argument("--prefix", type=Path, help="fresh pip --prefix directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _require_base_python()
        if args.symbols != 20:
            raise VerificationError("installed runner acceptance is fixed to exactly 20 symbols")
        bt_repo = args.backtrader_repo.expanduser().resolve()
        fincore_repo = args.fincore_repo.expanduser().resolve()
        data_dir = args.data_dir.expanduser().resolve()
        evidence = args.evidence_dir.expanduser().resolve()
        for path, label in (
            (bt_repo, "Backtrader repository"),
            (fincore_repo, "fincore repository"),
        ):
            if not (path / ".git").exists():
                raise VerificationError("%s is not a Git checkout: %s" % (label, path))
        if not (data_dir / "_metadata" / "manifest.json").is_file():
            raise VerificationError("daily source data manifest is absent: %s" % data_dir)
        if evidence.exists() and any(evidence.iterdir()):
            raise VerificationError("evidence directory must be new or empty: %s" % evidence)
        evidence.mkdir(parents=True, exist_ok=True)

        bt_commit = _full_commit(bt_repo, args.backtrader_commit, "Backtrader")
        fincore_commit = _full_commit(fincore_repo, args.fincore_commit, "fincore")
        bt_source, bt_wheel, bt_archive_hash = _build_wheel(
            bt_repo,
            bt_commit,
            "backtrader",
            evidence,
            factor_mode_pair=args.factor_mode_pair,
        )
        fincore_source, fincore_wheel, fincore_archive_hash = _build_wheel(
            fincore_repo, fincore_commit, "fincore", evidence
        )
        install_root, install_kind = _install_root(args, evidence)
        install_args = [
            BASE_PYTHON,
            "-I",
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
        ]
        install_args.extend(
            ["--prefix", args.prefix.expanduser().resolve()]
            if install_kind == "prefix"
            else ["--target", install_root]
        )
        install_args.extend([bt_wheel, fincore_wheel])
        result = _run(install_args, cwd=evidence)
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")

        payloads = {
            bt_wheel.name: _verify_wheel_payload(bt_wheel, install_root, bt_source),
            fincore_wheel.name: _verify_wheel_payload(fincore_wheel, install_root, fincore_source),
        }
        imports = _verify_imports(install_root, evidence)
        versions = imports["versions"]
        provenance = {
            "schema": "iteration46-installed-alpha101-provenance-v1",
            "acceptance_profile": (
                "iteration47-factor-mode-pair"
                if args.factor_mode_pair
                else "iteration46-installed-alpha101"
            ),
            "backtrader": {
                "source_commit": bt_commit,
                "version": versions["backtrader"],
                "wheel_path": str(bt_wheel.resolve()),
                "wheel_sha256": _sha256(bt_wheel),
                "git_archive_sha256": bt_archive_hash,
            },
            "fincore": {
                "source_commit": fincore_commit,
                "version": versions["fincore"],
                "wheel_path": str(fincore_wheel.resolve()),
                "wheel_sha256": _sha256(fincore_wheel),
                "git_archive_sha256": fincore_archive_hash,
            },
        }
        provenance_path = evidence / "artifact-provenance.json"
        provenance_path.write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        external = evidence / "external-tests"
        external.mkdir()
        _copy_external_tests(bt_source, external, factor_mode_pair=args.factor_mode_pair)
        pair_helper_path = None
        pair_helper = None
        if args.factor_mode_pair:
            pair_helper_path = _copy_external_pair_helper(bt_source, external)
            pair_helper = _load_pair_semantics_helper(pair_helper_path, external)
        test_report = _run_installed_tests(
            external,
            install_root,
            provenance_path,
            evidence,
            factor_mode_pair=args.factor_mode_pair,
        )
        copied_examples = _copy_examples(bt_source, evidence / "external-examples")
        example_reports = _run_025_026(
            copied_examples,
            install_root,
            data_dir,
            evidence,
            factor_mode_pair=args.factor_mode_pair,
            pair_helper=pair_helper,
            pair_helper_path=pair_helper_path,
            external_test_root=external if args.factor_mode_pair else None,
        )
        example_reports["027_alpha003_panel_acceptance"] = _run_027(
            copied_examples["027_alpha003_panel_acceptance"],
            install_root,
            data_dir,
            evidence,
            factor_mode_pair=args.factor_mode_pair,
            pair_helper=pair_helper,
            pair_helper_path=pair_helper_path,
            external_test_root=external if args.factor_mode_pair else None,
        )
        final = {
            "status": "PASS_LOCAL_INSTALLED_WHEEL_ACCEPTANCE",
            "acceptance_profile": (
                "iteration47-factor-mode-pair"
                if args.factor_mode_pair
                else "iteration46-installed-alpha101"
            ),
            "factor_mode_pair": (
                {
                    "enabled": True,
                    "formulas": ["Alpha003", "CloseMA", "ROC", "KDJ"],
                    "engine_modes": list(_PAIR_ENGINE_MODES),
                    "formula_test_witnesses": test_report["factor_mode_pair_formula_witnesses"],
                    "examples": [
                        "025_factor_single",
                        "026_factor_multi",
                        "027_alpha003_panel_acceptance",
                    ],
                }
                if args.factor_mode_pair
                else {"enabled": False}
            ),
            "source_commits": {"backtrader": bt_commit, "fincore": fincore_commit},
            "versions": versions,
            "install_kind": install_kind,
            "install_root": str(install_root),
            "wheel_sha256": {
                "backtrader": _sha256(bt_wheel),
                "fincore": _sha256(fincore_wheel),
            },
            "wheel_record_payloads": payloads,
            "module_origins": imports["origins"],
            "installed_tests": test_report,
            "copied_examples": example_reports,
            "scope": (
                "local pinned-wheel acceptance using Anaconda base dependencies; "
                "not dependency-isolated, release, or deployment evidence"
            ),
        }
        (evidence / "verification-summary.json").write_text(
            json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(final, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, VerificationError) as exc:
        print("NOT_ACCEPTED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
