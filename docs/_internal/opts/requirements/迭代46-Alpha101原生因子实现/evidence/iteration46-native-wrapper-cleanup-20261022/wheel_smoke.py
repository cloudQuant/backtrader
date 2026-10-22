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
import zipfile


def run(command, *, cwd, env, log):
    result = subprocess.run(
        command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    log.write_text(result.stdout)
    if result.returncode:
        print(result.stdout)
        raise RuntimeError("command failed: %r" % command)
    return result.stdout


parser = argparse.ArgumentParser()
parser.add_argument("--tree", required=True)
parser.add_argument("--evidence", required=True)
args = parser.parse_args()
repo = Path.cwd()
evidence = Path(args.evidence).resolve()
evidence.mkdir(parents=True, exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix="backtrader-alpha101-direct-wheel-"))
print("Wheel check workspace:", workspace, flush=True)
source = workspace / "source"
source.mkdir()
archive_bytes = subprocess.check_output(
    [
        "git",
        "archive",
        "--format=tar",
        args.tree,
        "backtrader",
        "backtrader_runtime",
        "setup.py",
        "pyproject.toml",
        "README.md",
        "LICENSE",
    ],
    cwd=repo,
)
with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as archive:
    for member in archive.getmembers():
        path = Path(member.name)
        assert not path.is_absolute() and ".." not in path.parts
    archive.extractall(source, filter="data")
environment = os.environ.copy()
for name in (
    "PYTHONPATH",
    "PYTHONHOME",
    "BACKTRADER_USE_INSTALLED",
    "PYTEST_ADDOPTS",
    "BT_ALPHA101_NATIVE_BATCHES",
    "BT_ALPHA101_NATIVE_IDS",
):
    environment.pop(name, None)
environment.update(
    PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
)
dist = workspace / "dist"
run(
    [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--no-build-isolation",
        "--wheel-dir",
        str(dist),
        str(source),
    ],
    cwd=workspace,
    env=environment,
    log=workspace / "build.log",
)
(wheel,) = dist.glob("*.whl")
with zipfile.ZipFile(wheel) as package:
    names = set(package.namelist())
    for alpha_id in range(1, 102):
        assert "backtrader/research/alpha101/alpha%03d.py" % alpha_id in names
    forbidden = (
        "backtrader/research/representative.py",
        "backtrader/research/alpha101_dependencies.json",
        "backtrader/research/alpha101/_base.py",
        "backtrader/research/alpha101/promoted.py",
    )
    assert not names.intersection(forbidden)
    assert not any(name.startswith("tests/") for name in names)
    assert not any(name.startswith("backtrader/research/alpha101/batch_") for name in names)
    payload_hashes = {}
    for name in sorted(names):
        if name.startswith("backtrader/research/") and name.endswith(".py"):
            data = package.read(name)
            assert data == (source / name).read_bytes(), name
            payload_hashes[name] = hashlib.sha256(data).hexdigest()

venv = workspace / "consumer"
run(
    [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
    cwd=workspace,
    env=environment,
    log=workspace / "venv.log",
)
consumer_python = venv / "bin/python"
run(
    [
        str(consumer_python),
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--no-index",
        "--ignore-installed",
        str(wheel),
    ],
    cwd=workspace,
    env=environment,
    log=workspace / "install.log",
)
external = workspace / "external"
external.mkdir()
probe = external / "probe.py"
probe.write_text("""import hashlib, importlib, json, sys
from pathlib import Path
from backtrader.research.alpha101 import get_alpha, list_alphas
from backtrader.research.factor_indicator import FactorIndicator
assert list_alphas() == tuple(range(1, 102))
origins = {}
for number in list_alphas():
    cls = get_alpha(number)
    assert cls.__bases__ == (FactorIndicator,)
    name = 'backtrader.research.alpha101.alpha%03d' % number
    assert cls.__module__ == name
    module = importlib.import_module(name)
    path = Path(module.__file__).resolve()
    assert 'site-packages' in path.relative_to(Path(sys.prefix).resolve()).parts
    origins[name] = str(path)
for name in ('backtrader.research.factor_indicator', 'backtrader.research.factor_strategy', 'backtrader.research.alpha101._helpers', 'backtrader.research.alpha101._metadata'):
    path = Path(importlib.import_module(name).__file__).resolve()
    assert 'site-packages' in path.relative_to(Path(sys.prefix).resolve()).parts
    origins[name] = str(path)
assert 'backtrader.research.representative' not in sys.modules
import backtrader.research as research
import backtrader.research.alpha101 as alphas
import backtrader.research.operators as operators
assert not hasattr(research, 'save_dataset')
assert not hasattr(alphas, 'FormulaIdentity')
assert not hasattr(alphas, 'ImplementationIdentity')
for number in list_alphas():
    cls = get_alpha(number)
    assert isinstance(cls.formula, str) and cls.formula
    assert not hasattr(cls, 'formula_identity')
    assert not hasattr(cls, 'implementation_identity')
for name in ('Rank', 'Scale', 'RollingStdDev', 'Corr', 'Cov', 'ElementwiseMin', 'ElementwiseMax'):
    assert not hasattr(operators, name)
Path('origins.json').write_text(json.dumps(origins, indent=2) + '\\n')
print('PASS: all 101 direct factors load from installed wheel')
""")
run(
    [str(consumer_python), str(probe)], cwd=external, env=environment, log=workspace / "origins.log"
)
test_path = external / "test_alpha101_native_l0.py"
test_payload = subprocess.check_output(
    ["git", "show", args.tree + ":tests/unit/test_alpha101_native_l0.py"], cwd=repo
)
test_path.write_bytes(test_payload)
run(
    [
        str(consumer_python),
        "-m",
        "pytest",
        str(test_path),
        "-q",
        "--tb=short",
        "--junitxml=" + str(evidence / "installed-l0.xml"),
    ],
    cwd=external,
    env=environment,
    log=workspace / "l0.log",
)
origins = json.loads((external / "origins.json").read_text())
for name, expected_hash in payload_hashes.items():
    installed = venv / "lib" / ("python%d.%d" % sys.version_info[:2]) / "site-packages" / name
    assert hashlib.sha256(installed.read_bytes()).hexdigest() == expected_hash
summary = {
    "status": "PASS",
    "scope": "isolated wheel payload/import and installed Alpha003/Alpha009 numerical lifecycle smoke",
    "source_tree": args.tree,
    "python": sys.version,
    "workspace": str(workspace),
    "wheel_path": str(wheel),
    "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    "direct_factor_count": 101,
    "research_python_payloads_verified": len(payload_hashes),
    "removed_runtime_modules_absent": True,
    "removed_apis_absent": True,
    "test_assets_absent": True,
    "test_payload_sha256": hashlib.sha256(test_payload).hexdigest(),
    "origins": origins,
    "full_installed_fincore_matrix": "NOT_RUN",
}
(evidence / "wheel-smoke.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(
    run(
        [str(consumer_python), "-c", "import sys; print(sys.executable)"],
        cwd=external,
        env=environment,
        log=workspace / "interpreter.log",
    ).strip()
)
print((workspace / "origins.log").read_text().strip())
print((workspace / "l0.log").read_text().strip())
print("Evidence:", evidence / "wheel-smoke.json")
