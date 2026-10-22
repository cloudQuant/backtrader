"""Recheck the affected tests against an exported, immutable Git snapshot."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET


parser = argparse.ArgumentParser()
parser.add_argument("--commit", required=True)
parser.add_argument("--evidence", required=True)
args = parser.parse_args()
repo = Path.cwd()
evidence = Path(args.evidence).resolve()
commit = subprocess.check_output(["git", "rev-parse", args.commit], text=True).strip()
paths = [
    "backtrader",
    "backtrader_runtime",
    "conftest.py",
    "pytest.ini",
    "pyproject.toml",
    "setup.py",
    "README.md",
    "LICENSE",
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/unit",
    "tests/test_utils",
    "tests/fixtures/research",
    "tests/integration/__init__.py",
    "tests/integration/conftest.py",
    "tests/integration/test_alpha101_native_matrix.py",
    "docs/_internal/opts/requirements/迭代46-Alpha101原生因子实现/生产因子台账.json",
]
archive_bytes = subprocess.check_output(["git", "archive", "--format=tar", commit, *paths])
snapshot = Path(tempfile.mkdtemp(prefix="backtrader-alpha101-cleanup-snapshot-"))
with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
    for member in archive.getmembers():
        path = Path(member.name)
        assert not path.is_absolute() and ".." not in path.parts
    archive.extractall(snapshot, filter="data")
sources = {
    str(path.relative_to(snapshot)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in snapshot.rglob("*")
    if path.is_file()
}
environment = os.environ.copy()
for key in (
    "PYTHONPATH",
    "PYTHONHOME",
    "BACKTRADER_USE_INSTALLED",
    "BT_ALPHA101_NATIVE_BATCHES",
    "BT_ALPHA101_NATIVE_IDS",
):
    environment.pop(key, None)
probe = (
    "from pathlib import Path; import backtrader; "
    "path = Path(backtrader.__file__).resolve(); "
    "assert path.is_relative_to(Path.cwd().resolve()); print(path)"
)
origin = subprocess.check_output(
    [sys.executable, "-c", probe], cwd=snapshot, env=environment, text=True
).strip()
selection = [
    "tests/unit/test_factor_research_representatives.py",
    "tests/unit/test_alpha101_native_promotion.py",
    "tests/unit/test_alpha101_scalar_clock.py",
    "tests/unit/test_alpha101_native_corrections.py",
    "tests/unit/test_alpha101_formula_membership.py",
    "tests/integration/test_alpha101_native_matrix.py::"
    "test_alpha101_batch_partition_and_full_registry_contract",
]
command = [
    sys.executable,
    "-m",
    "pytest",
    "-n",
    "4",
    "--dist=worksteal",
    *selection,
    "-q",
    "--tb=short",
    "--junitxml=" + str(evidence / "clean-source-affected.xml"),
]
print("Clean snapshot:", snapshot, "commit:", commit, flush=True)
with (evidence / "clean-source-process.log").open("w") as log:
    result = subprocess.run(command, cwd=snapshot, env=environment, text=True, stdout=log,
                            stderr=subprocess.STDOUT)
process = {"exit_code": result.returncode, "command": command, "cwd": str(snapshot)}
(evidence / "clean-process-result.json").write_text(json.dumps(process, indent=2) + "\n")
print((evidence / "clean-source-process.log").read_text(), flush=True)
assert result.returncode == 0


def passed_ids(path):
    root = ET.parse(path).getroot()
    suite, = list(root.iter("testsuite"))
    counters = {key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")}
    assert counters == {"tests": 55, "failures": 0, "errors": 0, "skipped": 0}
    cases = list(root.iter("testcase"))
    assert len(cases) == 55
    ids = [(case.attrib["classname"], case.attrib["name"]) for case in cases]
    assert len(set(ids)) == 55
    assert all(not list(case) for case in cases)
    return set(ids)


assert passed_ids(evidence / "source-affected.xml") == passed_ids(evidence / "clean-source-affected.xml")
for relative, expected in sources.items():
    assert hashlib.sha256((snapshot / relative).read_bytes()).hexdigest() == expected, relative
record = {
    "status": "PASS",
    "source_commit": commit,
    "snapshot": str(snapshot),
    "interpreter": sys.executable,
    "package_origin": origin,
    "git_archive_paths": paths,
    "git_archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
    "exported_source_files_verified_unchanged": len(sources),
    "source_sha256": sources,
    "passed_unique_test_ids": 55,
    "same_test_ids_as_initial_workspace_run": True,
    "process_exit_code": result.returncode,
    "full_installed_fincore_matrix": "NOT_RUN",
}
(evidence / "clean-snapshot.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
print("PASS: 55 affected tests against the committed snapshot; exported sources unchanged")
