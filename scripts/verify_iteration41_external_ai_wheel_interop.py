"""Verify the Iteration 41 offline AI-product evidence boundary from wheels.

The Backtrader runtime and its three separately distributed AI products must not
gain a live-execution path merely because they exchange review material.  This
tool builds the local ``backtrader-agent``, ``backtrader-skills`` and
``backtrader-mcp`` checkouts into wheels, installs only those wheels into a
fresh virtual environment, and runs a ``python -I -s`` child process outside
all source checkouts.

The child binds a real schema-v4 package replay ``config.yaml`` digest to a
synthetic, non-executed fixture artifact.  It proves only the portable,
read-only ``bt-api-deployment-evidence/v1`` handoff:

* Agent can produce a ``review_required`` wire record.
* Skills can validate it but rejects it for promotion.
* MCP can observe it but grants no deployment, execution, or control power.

No provider SDK, account, order, strategy runner, secrets store, or live
runtime is imported or contacted.  This is deliberately not evidence that any
``bt_api`` execution/risk/monitor capability wheel is packaged or admitted.
"""

from __future__ import print_function

import argparse
import base64
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from email.policy import default as email_default_policy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_FIXTURE = (
    "backtrader_runtime/_iteration41_l2_fixture/runtimes/managed_013_3"
)
_ARTIFACT_FIXTURE = "backtrader_runtime/_iteration41_l2_fixture/managed_013_3.py"
_PRODUCTS = (
    ("agent", "backtrader-agent", "backtrader_agent", "backtrader_agent/deployment_evidence.py"),
    ("skills", "backtrader-skills", "backtrader_skills", "backtrader_skills/deployment_evidence.py"),
    ("mcp", "backtrader-mcp", "backtrader_mcp", "backtrader_mcp/deployment_evidence.py"),
)
_BUILD_SOURCE_DATE_EPOCH = "1700000000"


class InteropError(RuntimeError):
    """A clean-wheel evidence condition did not hold."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _regular_file(path: Path, label: str) -> Path:
    try:
        status = path.lstat()
    except OSError as exc:
        raise InteropError("{0} is missing".format(label)) from exc
    if not path.is_file() or path.is_symlink():
        raise InteropError("{0} must be a regular non-symlink file".format(label))
    if status.st_size <= 0:
        raise InteropError("{0} must not be empty".format(label))
    return path


def _require_source_root(path: Path, product: str) -> Path:
    root = path.expanduser().resolve()
    if not root.is_dir() or not (root / "pyproject.toml").is_file():
        raise InteropError("{0} source root is unavailable".format(product))
    return root


def _offline_wheelhouse(path: Path) -> List[Dict[str, str]]:
    """Inventory an explicit local build wheelhouse without trusting an index."""

    root = path.expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise InteropError("offline build wheelhouse is unavailable")
    wheels = sorted(item for item in root.glob("*.whl") if item.is_file() and not item.is_symlink())
    if not wheels:
        raise InteropError("offline build wheelhouse has no wheel files")
    return [
        {"filename": wheel.name, "sha256": _sha256_bytes(wheel.read_bytes())}
        for wheel in wheels
    ]


def _load_replay_config(core_root: Path) -> Dict[str, str]:
    """Read the sealed package replay fixture without importing its strategy."""

    fixture_dir = core_root / _CONFIG_FIXTURE
    artifact = _regular_file(core_root / _ARTIFACT_FIXTURE, "package replay artifact")
    if not fixture_dir.is_dir():
        raise InteropError("package replay config fixture is unavailable")

    # The script is an acceptance utility, not a runtime module.  Its explicit
    # source-root import only asks Backtrader's strict config reader to verify
    # the real config.yaml bytes before they become evidence input.
    original_path = list(sys.path)
    try:
        sys.path.insert(0, str(core_root))
        from backtrader_runtime.config import load_runtime_config

        config = load_runtime_config(fixture_dir)
    finally:
        sys.path[:] = original_path

    if config.mode != "simulation" or config.preset != "replay":
        raise InteropError("package replay fixture must remain simulation/replay")
    return {
        "strategy_id": config.strategy_id,
        "mode": config.mode,
        "preset": config.preset,
        "config_digest": config.config_digest,
        "config_fixture": _CONFIG_FIXTURE + "/config.yaml",
        "artifact_fixture": _ARTIFACT_FIXTURE,
        "artifact_sha256": _sha256_bytes(artifact.read_bytes()),
    }


def _run(
    command: Sequence[str], cwd: Path, environment: Optional[Mapping[str, str]] = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(environment) if environment is not None else None,
        check=False,
    )


def _command_error(label: str, process: subprocess.CompletedProcess) -> InteropError:
    # Do not print pip output by default: it can carry machine-specific paths.
    detail = process.stderr.strip().splitlines()[-1:] or process.stdout.strip().splitlines()[-1:]
    suffix = " ({0})".format(detail[0]) if detail else ""
    return InteropError("{0} failed with exit status {1}{2}".format(label, process.returncode, suffix))


def _build_wheels(
    python: str,
    source_roots: Mapping[str, Path],
    wheel_dir: Path,
    run_root: Path,
    build_wheelhouse: Optional[Path] = None,
) -> Dict[str, Path]:
    wheels: Dict[str, Path] = {}
    environment = dict(os.environ)
    # Backends that honor the reproducible-build convention write stable zip
    # member timestamps.  The fixed value also keeps local evidence comparable
    # without making it a release provenance assertion.
    environment["SOURCE_DATE_EPOCH"] = _BUILD_SOURCE_DATE_EPOCH
    for label, distribution, _package, _member in _PRODUCTS:
        command = [
            python,
            "-m",
            "pip",
            "wheel",
            "--disable-pip-version-check",
            "--no-index",
            "--no-deps",
        ]
        if build_wheelhouse is None:
            # A default run uses only build backends already installed in the
            # selected interpreter.  It cannot silently bootstrap from an
            # index.
            command.append("--no-build-isolation")
        else:
            # PEP 517 isolation is allowed only when every build dependency is
            # supplied by the explicit, hash-recorded local wheelhouse.
            command.extend(("--find-links", str(build_wheelhouse)))
        command.extend(("--wheel-dir", str(wheel_dir), str(source_roots[label])))
        process = _run(tuple(command), run_root, environment)
        if process.returncode != 0:
            output = "\n".join((process.stdout, process.stderr))
            if "hatchling.build" in output:
                raise InteropError(
                    "{0} wheel build needs a local Hatchling backend; use an installed backend "
                    "or --build-wheelhouse without enabling an index".format(distribution)
                )
            raise _command_error("{0} wheel build".format(distribution), process)
        prefix = distribution.replace("-", "_") + "-"
        candidates = sorted(path for path in wheel_dir.glob("*.whl") if path.name.startswith(prefix))
        if len(candidates) != 1:
            raise InteropError("{0} wheel build did not produce one wheel".format(distribution))
        wheels[label] = candidates[0]
    return wheels


def _record_digest(record_value: str) -> Optional[str]:
    if not record_value:
        return None
    algorithm, separator, encoded = record_value.partition("=")
    if algorithm != "sha256" or not separator:
        raise InteropError("wheel RECORD uses an unsupported digest")
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (TypeError, ValueError) as exc:
        raise InteropError("wheel RECORD has an invalid SHA-256 digest") from exc
    if len(decoded) != hashlib.sha256().digest_size:
        raise InteropError("wheel RECORD has an invalid SHA-256 digest")
    return decoded.hex()


def _verify_wheel_member(wheel: Path, distribution: str, member: str) -> Dict[str, Any]:
    with zipfile.ZipFile(str(wheel)) as archive:
        names = set(archive.namelist())
        if member not in names:
            raise InteropError("wheel is missing {0}".format(member))
        record_name = next((name for name in names if name.endswith(".dist-info/RECORD")), None)
        if record_name is None:
            raise InteropError("wheel is missing RECORD")
        metadata_name = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
        if metadata_name is None:
            raise InteropError("wheel is missing METADATA")
        metadata = BytesParser(policy=email_default_policy).parsebytes(archive.read(metadata_name))
        metadata_name_value = metadata.get("Name")
        version = metadata.get("Version")
        if (
            not isinstance(metadata_name_value, str)
            or metadata_name_value.replace("_", "-").lower() != distribution
            or not isinstance(version, str)
            or not version
        ):
            raise InteropError("wheel metadata does not identify {0}".format(distribution))
        records = {
            row[0]: row[1:]
            for row in csv.reader(archive.read(record_name).decode("utf-8").splitlines())
            if len(row) == 3
        }
        row = records.get(member)
        if row is None:
            raise InteropError("wheel RECORD is missing {0}".format(member))
        payload = archive.read(member)
        digest = _record_digest(row[0])
        if digest != _sha256_bytes(payload) or row[1] != str(len(payload)):
            raise InteropError("wheel RECORD does not verify {0}".format(member))
    return {
        "filename": wheel.name,
        "version": version,
        "wheel_sha256": _sha256_bytes(wheel.read_bytes()),
        "evidence_module": member,
        "record_verified": True,
    }


def _make_venv(python: str, venv_dir: Path, run_root: Path) -> Path:
    process = _run((python, "-m", "venv", str(venv_dir)), run_root)
    if process.returncode != 0:
        raise _command_error("clean virtual environment creation", process)
    executable = venv_dir / "Scripts" / "python.exe"
    if not executable.is_file():
        executable = venv_dir / "bin" / "python"
    if not executable.is_file():
        raise InteropError("clean virtual environment has no Python executable")
    return executable


def _install_wheels(python: Path, wheels: Iterable[Path], run_root: Path) -> None:
    process = _run(
        tuple(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                "--no-index",
                "--force-reinstall",
            ]
            + [str(wheel) for wheel in wheels]
        ),
        run_root,
    )
    if process.returncode != 0:
        raise _command_error("clean wheel installation", process)


_PROBE = r"""
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

payload = json.loads(sys.argv[1])
source_roots = [Path(value).resolve() for value in json.loads(sys.argv[2])]

sys.dont_write_bytecode = True
from backtrader_agent.deployment_evidence import create_deployment_evidence
from backtrader_skills.deployment_evidence import DeploymentPromotionRejected
from backtrader_skills.deployment_evidence import validate_deployment_evidence as validate_skills
from backtrader_mcp.deployment_evidence import validate_deployment_evidence as validate_mcp

import site
site_roots = [Path(value).resolve() for value in site.getsitepackages()]

def inside(path, root):
    try:
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True

origins = {}
for module in (
    'backtrader_agent.deployment_evidence',
    'backtrader_skills.deployment_evidence',
    'backtrader_mcp.deployment_evidence',
):
    spec = importlib.util.find_spec(module)
    assert spec is not None and isinstance(spec.origin, str)
    origin = Path(spec.origin).resolve()
    assert any(inside(origin, root) for root in site_roots)
    relative = None
    for root in site_roots:
        if inside(origin, root):
            relative = origin.relative_to(root).as_posix()
            break
    assert relative is not None
    origins[module] = relative

source_checkout_absent = all(
    not any(inside(Path(item or '.').resolve(), root) for root in source_roots)
    for item in sys.path
)
assert source_checkout_absent
provider_modules_absent = not any(
    name == 'backtrader' or name.startswith('bt_api')
    for name in sys.modules
)
assert provider_modules_absent

def forbidden(*args, **kwargs):
    raise AssertionError('read-only evidence operation attempted I/O')

# Imports happened above so Python can load wheel modules.  During the actual
# evidence create/validate calls, deny filesystem, network, process, and state
# mutations.  The operation must remain pure in-memory computation.
builtins.open = forbidden
os.open = forbidden
os.mkdir = forbidden
os.makedirs = forbidden
os.remove = forbidden
os.unlink = forbidden
os.replace = forbidden
socket.create_connection = forbidden
socket.socket.connect = forbidden
subprocess.Popen = forbidden

wire = create_deployment_evidence(
    artifact_sha256=payload['artifact_sha256'],
    config_effective_digest=payload['config_digest'],
    producer_product='backtrader-agent',
    producer_version=payload['agent_version'],
    producer_commit='local-iteration41',
    producer_wheel_sha256=payload['agent_wheel_sha256'],
    tenant_id='tenant:iteration41-fixture',
    strategy_id=payload['strategy_id'],
    metadata={'fixture_kind': 'iteration41-package-replay'},
    evidence_id='evidence-iteration41-wheel-interop',
    created_at=payload['created_at'],
    expires_at=payload['expires_at'],
).to_dict()
digest = hashlib.sha256(
    json.dumps(wire, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    .encode('utf-8')
).hexdigest()
skills = validate_skills(
    wire,
    expected_tenant_id='tenant:iteration41-fixture',
    expected_strategy_id=payload['strategy_id'],
    expected_evidence_digest=digest,
    expected_artifact_sha256=payload['artifact_sha256'],
    expected_config_effective_digest=payload['config_digest'],
    now=payload['created_at'] + 1.0,
)
try:
    validate_skills(
        wire,
        expected_tenant_id='tenant:iteration41-fixture',
        expected_strategy_id=payload['strategy_id'],
        expected_evidence_digest=digest,
        expected_artifact_sha256=payload['artifact_sha256'],
        expected_config_effective_digest=payload['config_digest'],
        now=payload['created_at'] + 1.0,
        require_promotion=True,
    )
except DeploymentPromotionRejected as exc:
    promotion_code = exc.code
else:
    raise AssertionError('review_required evidence unexpectedly passed promotion')
mcp = validate_mcp(
    wire,
    expected_evidence_sha256=digest,
    expected_tenant_id='tenant:iteration41-fixture',
    expected_strategy_id=payload['strategy_id'],
    expected_artifact_sha256=payload['artifact_sha256'],
    expected_config_effective_digest=payload['config_digest'],
    now=payload['created_at'] + 1.0,
)
assert skills['status'] == 'valid'
assert skills['read_only'] is True
assert skills['authorization_granted'] is False
assert skills['promotion_review_eligible'] is False
assert promotion_code == 'DEPLOYMENT_PROMOTION_REJECTED'
assert mcp['status'] == 'REQUIRES_INDEPENDENT_REVIEW'
assert mcp['read_only'] is True
assert mcp['deployment_authorized'] is False
assert mcp['execution_authorized'] is False
assert mcp['control_authorized'] is False
print(json.dumps({
    'status': 'passed',
    'module_origins': origins,
    'source_checkout_absent': source_checkout_absent,
    'provider_modules_absent': provider_modules_absent,
    'agent_to_skills': {
        'status': skills['status'],
        'read_only': skills['read_only'],
        'authorization_granted': skills['authorization_granted'],
        'promotion_review_eligible': skills['promotion_review_eligible'],
        'promotion_rejection_code': promotion_code,
    },
    'mcp_observation': {
        'status': mcp['status'],
        'read_only': mcp['read_only'],
        'deployment_authorized': mcp['deployment_authorized'],
        'execution_authorized': mcp['execution_authorized'],
        'control_authorized': mcp['control_authorized'],
    },
}, sort_keys=True))
"""


def _run_probe(
    python: Path,
    run_root: Path,
    config: Mapping[str, str],
    agent_wheel_sha256: str,
    agent_version: str,
    source_roots: Mapping[str, Path],
) -> Dict[str, Any]:
    payload = {
        "agent_version": agent_version,
        "agent_wheel_sha256": agent_wheel_sha256,
        "artifact_sha256": config["artifact_sha256"],
        "config_digest": config["config_digest"],
        "strategy_id": config["strategy_id"],
        # Stable fixture time keeps the evidence bounded while allowing each
        # consumer to use an explicitly supplied deterministic clock.
        "created_at": 1700000000.0,
        "expires_at": 1900000000.0,
    }
    process = _run(
        (
            str(python),
            "-I",
            "-s",
            "-c",
            _PROBE,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            json.dumps([str(root) for root in source_roots.values()]),
        ),
        run_root,
    )
    if process.returncode != 0:
        raise _command_error("isolated evidence interoperation", process)
    try:
        result = json.loads(process.stdout)
    except (TypeError, ValueError) as exc:
        raise InteropError("isolated evidence interoperation emitted invalid JSON") from exc
    if not isinstance(result, dict) or result.get("status") != "passed":
        raise InteropError("isolated evidence interoperation did not pass")
    return result


def verify(
    *,
    python: str,
    core_root: Path,
    source_roots: Mapping[str, Path],
    build_wheelhouse: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build, clean-install, and exercise the narrow offline wire handoff."""

    config = _load_replay_config(core_root)
    wheelhouse_records = (
        _offline_wheelhouse(build_wheelhouse) if build_wheelhouse is not None else []
    )
    with tempfile.TemporaryDirectory(prefix="iteration41-external-ai-wheel-") as temporary:
        temporary_root = Path(temporary)
        wheel_dir = temporary_root / "wheels"
        venv_dir = temporary_root / "venv"
        run_root = temporary_root / "outside-source-checkouts"
        wheel_dir.mkdir()
        run_root.mkdir()
        wheels = _build_wheels(
            python,
            source_roots,
            wheel_dir,
            run_root,
            build_wheelhouse=build_wheelhouse,
        )
        wheel_records = {}
        for label, distribution, _package, member in _PRODUCTS:
            wheel_records[label] = _verify_wheel_member(wheels[label], distribution, member)
        isolated_python = _make_venv(python, venv_dir, run_root)
        _install_wheels(isolated_python, wheels.values(), run_root)
        probe = _run_probe(
            isolated_python,
            run_root,
            config,
            wheel_records["agent"]["wheel_sha256"],
            wheel_records["agent"]["version"],
            source_roots,
        )
        run_root_empty = not any(run_root.iterdir())
        if not run_root_empty:
            raise InteropError("isolated evidence probe created a file in its working directory")

    return {
        "schema_version": "iteration41-external-ai-wheel-interop/v1",
        "status": "passed",
        "scope": {
            "config_fixture": config["config_fixture"],
            "artifact_fixture": config["artifact_fixture"],
            "runtime_mode": config["mode"],
            "runtime_preset": config["preset"],
            "provider_network": False,
            "execution": False,
            "live_admission": False,
            "external_bt_api_capability_wheels_verified": False,
        },
        "config": {
            "strategy_id": config["strategy_id"],
            "config_effective_digest": config["config_digest"],
            "artifact_sha256": config["artifact_sha256"],
        },
        "build_environment": {
            "mode": "offline-wheelhouse" if build_wheelhouse is not None else "installed-backend",
            "package_index": False,
            "source_date_epoch": _BUILD_SOURCE_DATE_EPOCH,
            "wheelhouse": wheelhouse_records,
        },
        "wheels": wheel_records,
        "isolated_probe": probe,
        "run_root_empty": True,
    }


def _safe_error(value: BaseException, roots: Iterable[Path]) -> str:
    message = str(value)
    for root in roots:
        try:
            message = message.replace(str(root.resolve()), "<path>")
        except OSError:
            continue
    return message


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Python interpreter used for wheel builds")
    parser.add_argument("--core-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--agent-root", type=Path, default=PROJECT_ROOT.parent / "backtrader-agent")
    parser.add_argument("--skills-root", type=Path, default=PROJECT_ROOT.parent / "backtrader-skills")
    parser.add_argument("--mcp-root", type=Path, default=PROJECT_ROOT.parent / "backtrader-mcp")
    parser.add_argument(
        "--build-wheelhouse",
        type=Path,
        help=(
            "optional approved local PEP 517 build-backend wheelhouse; no package index is ever used"
        ),
    )
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path")
    args = parser.parse_args(argv)

    roots: List[Path] = [args.core_root, args.agent_root, args.skills_root, args.mcp_root]
    try:
        core_root = _require_source_root(args.core_root, "Backtrader")
        source_roots = {
            "agent": _require_source_root(args.agent_root, "backtrader-agent"),
            "skills": _require_source_root(args.skills_root, "backtrader-skills"),
            "mcp": _require_source_root(args.mcp_root, "backtrader-mcp"),
        }
        result = verify(
            python=args.python,
            core_root=core_root,
            source_roots=source_roots,
            build_wheelhouse=args.build_wheelhouse,
        )
    except (InteropError, OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {
            "schema_version": "iteration41-external-ai-wheel-interop/v1",
            "status": "failed",
            "scope": {
                "provider_network": False,
                "execution": False,
                "live_admission": False,
                "external_bt_api_capability_wheels_verified": False,
            },
            "build_environment": {
                "mode": (
                    "offline-wheelhouse" if args.build_wheelhouse is not None else "installed-backend"
                ),
                "package_index": False,
                "source_date_epoch": _BUILD_SOURCE_DATE_EPOCH,
            },
            "error": {"type": type(exc).__name__, "message": _safe_error(exc, roots)},
        }

    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
    print(serialized, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
