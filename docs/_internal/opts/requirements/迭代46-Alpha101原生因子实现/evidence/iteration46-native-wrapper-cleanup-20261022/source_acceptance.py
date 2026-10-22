"""Run existing research contracts from a frozen Git tree, outside the checkout."""

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
import time
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument("--tree", required=True)
parser.add_argument("--evidence", required=True)
parser.add_argument("--supplemental", action="store_true")
args = parser.parse_args()
repo = Path.cwd()
evidence = Path(args.evidence).resolve()
evidence.mkdir(parents=True, exist_ok=True)
prefix = "source-supplement" if args.supplemental else "source"
source = Path(tempfile.mkdtemp(prefix="backtrader-research-cleanup-source-")).resolve()
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
    "tests/integration",
    "tests/fixtures/research",
    "examples/_support",
    "examples/backtest/025_factor_single",
    "examples/backtest/026_factor_multi",
    "examples/backtest/027_alpha003_panel_acceptance",
    "docs/source/developer-guide/alpha101-native.md",
    "docs/_internal/opts/requirements/迭代46-Alpha101原生因子实现/生产因子台账.json",
    "docs/_internal/opts/requirements/迭代45-Indicator因子研究与多因子合成/Alpha101覆盖清单.md",
]
payload = subprocess.check_output(["git", "archive", "--format=tar", args.tree, *paths])
with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
    for member in archive.getmembers():
        path = Path(member.name)
        assert not path.is_absolute() and ".." not in path.parts
    archive.extractall(source, filter="data")


def hashes():
    return {
        str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and ".pytest_cache" not in path.parts
    }


before = hashes()
environment = os.environ.copy()
for name in (
    "PYTHONPATH",
    "PYTHONHOME",
    "BACKTRADER_USE_INSTALLED",
    "BT_ALPHA101_NATIVE_BATCHES",
    "BT_ALPHA101_NATIVE_IDS",
    "PYTEST_ADDOPTS",
):
    environment.pop(name, None)
environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
targets = sorted(
    str(path.relative_to(source))
    for pattern in ("test_factor_research*.py", "test_alpha101*.py")
    for path in (source / "tests/unit").glob(pattern)
)
targets += [
    "tests/unit/test_factor_strict_error_propagation.py",
    "tests/unit/test_factor_report.py",
    "tests/integration/test_alpha101_native_data_contracts.py",
    "tests/integration/test_alpha101_native_matrix.py::test_alpha101_batch_partition_and_full_registry_contract",
]
if args.supplemental:
    targets = [
        "tests/unit/test_factor_field_metadata.py",
        "tests/unit/test_factor_identity_binding.py",
    ]
commands = []


def run(name, command):
    print("Running", name, "from", source, flush=True)
    started = time.monotonic()
    output = evidence / (name + ".txt")
    with output.open("w") as handle:
        result = subprocess.run(
            command, cwd=source, env=environment, stdout=handle, stderr=subprocess.STDOUT, text=True
        )
    commands.append(
        {
            "name": name,
            "command": command,
            "exit_code": result.returncode,
            "elapsed_seconds": time.monotonic() - started,
        }
    )
    (evidence / (prefix + "-processes.json")).write_text(json.dumps(commands, indent=2) + "\n")
    assert result.returncode == 0, output.read_text()[-12000:]
    return output.read_text()


origin = run(
    prefix + "-origin", [sys.executable, "-c", "import backtrader; print(backtrader.__file__)"]
)
assert Path(origin.strip()).resolve().is_relative_to(source)
base = [sys.executable, "-m", "pytest", "-p", "xdist.plugin", "-p", "no:cacheprovider"]
collection = run(prefix + "-collection", [*base, *targets, "--collect-only", "-q"])
expected = [
    line.strip() for line in collection.splitlines() if line.startswith("tests/") and "::" in line
]
assert expected and len(expected) == len(set(expected))
run(
    prefix + "-regression",
    [
        *base,
        *targets,
        "-n",
        "6",
        "--dist=worksteal",
        "-q",
        "--tb=short",
        "--junitxml=" + str(evidence / (prefix + "-regression.xml")),
    ],
)
root = ET.parse(evidence / (prefix + "-regression.xml")).getroot()
seen = {}
skipped = {}
for case in root.findall(".//testcase"):
    nodeid = case.attrib["classname"].replace(".", "/") + ".py::" + case.attrib["name"]
    assert nodeid not in seen, nodeid
    assert case.find("failure") is None and case.find("error") is None, nodeid
    seen[nodeid] = dict(case.attrib)
    if case.find("skipped") is not None:
        assert nodeid.startswith("tests/unit/test_factor_report.py::"), nodeid
        skipped[nodeid] = case.find("skipped").attrib
assert set(seen) == set(expected), (set(expected) - set(seen), set(seen) - set(expected))
assert hashes() == before, "exported inputs changed during acceptance"
summary = {
    "status": "PASS",
    "source_tree": args.tree,
    "source_export": str(source),
    "python": sys.version,
    "origin": origin.strip(),
    "expected_count": len(expected),
    "passed": len(seen) - len(skipped),
    "skipped": skipped,
    "failures": 0,
    "errors": 0,
    "exact_test_id_coverage": True,
    "exported_input_hashes_unchanged": before,
    "expected_nodeids": expected,
    "processes": commands,
    "full_101_numerical_matrix": "NOT_RUN",
    "full_installed_fincore_matrix": "NOT_RUN",
    "pinned_installed_fincore_integration": "NOT_RUN",
    "real_a_stock_full_market": "NOT_RUN",
}
(evidence / (prefix + "-acceptance.json")).write_text(json.dumps(summary, indent=2) + "\n")
print(
    "PASS:", len(seen) - len(skipped), "passed;", len(skipped), "optional report skips", flush=True
)
