"""Verify review-only Iteration 41 AI evidence across three isolated wheels.

The caller supplies already-built wheel files.  The verifier never builds
packages, downloads dependencies, imports a source checkout, or contacts a
provider.  It installs only those three wheels into a fresh temporary target
with ``--no-index --no-deps`` and runs the portable evidence vector using
``python -I -S``.  Passing this verifier is local review-evidence compatibility
only; it grants no deployment, execution, control, account, or credential
authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple


SCHEMA_VERSION = "iteration41.ai-wheel-review-interop.v1"
_WHEEL_ARGUMENTS = (
    ("backtrader-agent", "agent_wheel", "backtrader_agent"),
    ("backtrader-skills", "skills_wheel", "backtrader_skills"),
    ("backtrader-mcp", "mcp_wheel", "backtrader_mcp"),
)


class AiWheelInteropError(ValueError):
    """A safe verifier rejection which never echoes supplied paths or output."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        raise AiWheelInteropError("wheel file cannot be read") from None
    return digest.hexdigest()


def _regular_wheel(path: Path) -> Path:
    try:
        result = os.lstat(str(path))
        resolved = path.resolve(strict=True)
    except OSError:
        raise AiWheelInteropError("wheel file is unavailable") from None
    if stat.S_ISLNK(result.st_mode) or not stat.S_ISREG(result.st_mode):
        raise AiWheelInteropError("wheel must be a regular non-link file")
    if resolved.suffix.lower() != ".whl":
        raise AiWheelInteropError("wheel file must have a .whl suffix")
    return resolved


def _wheel_inputs(arguments: argparse.Namespace) -> Tuple[Tuple[str, Path, str], ...]:
    """Return fixed product-to-wheel identities and reject duplicated artifacts."""

    records = []
    identities = set()
    for product, argument_name, module_name in _WHEEL_ARGUMENTS:
        path = _regular_wheel(Path(getattr(arguments, argument_name)))
        identity = str(path)
        if identity in identities:
            raise AiWheelInteropError("each AI product must use a distinct wheel file")
        identities.add(identity)
        records.append((product, path, module_name))
    return tuple(records)


_CHILD_PROGRAM = r'''
import json
import socket
import sys
import time
from pathlib import Path

site_root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(site_root))

def inside(child, parent):
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True

def deny_socket(*args, **kwargs):
    raise AssertionError("AI wheel review interop must not open a socket")

socket.socket = deny_socket

from backtrader_agent.deployment_evidence import create_deployment_evidence
from backtrader_skills.deployment_evidence import validate_deployment_evidence as validate_skills
from backtrader_mcp.deployment_evidence import validate_deployment_evidence as validate_mcp

for name in (
    "backtrader_agent.deployment_evidence",
    "backtrader_skills.deployment_evidence",
    "backtrader_mcp.deployment_evidence",
):
    origin = Path(sys.modules[name].__file__).resolve()
    assert inside(origin, site_root), origin

now = time.time()
evidence = create_deployment_evidence(
    artifact_sha256="a" * 64,
    config_effective_digest="b" * 64,
    producer_product="backtrader-agent",
    producer_version="0.2.0",
    producer_commit="iteration41",
    producer_wheel_sha256="c" * 64,
    tenant_id="tenant-41",
    strategy_id="strategy-41",
    evidence_id="wheel-evidence-41",
    metadata={"source": "isolated-wheel"},
    created_at=now - 1.0,
    expires_at=now + 60.0,
)
wire = evidence.to_dict()
digest = evidence.digest
skills = validate_skills(
    wire,
    expected_tenant_id="tenant-41",
    expected_strategy_id="strategy-41",
    expected_evidence_digest=digest,
    expected_artifact_sha256="a" * 64,
    expected_config_effective_digest="b" * 64,
    now=now,
)
mcp = validate_mcp(
    wire,
    expected_evidence_sha256=digest,
    expected_tenant_id="tenant-41",
    expected_strategy_id="strategy-41",
    expected_artifact_sha256="a" * 64,
    expected_config_effective_digest="b" * 64,
    now=now,
)
assert skills["read_only"] is True
assert skills["authorization_granted"] is False
assert mcp["read_only"] is True
assert mcp["deployment_authorized"] is False
assert mcp["execution_authorized"] is False
assert mcp["control_authorized"] is False
assert not any(
    name == "backtrader" or name.startswith("backtrader.")
    or name == "bt_api" or name.startswith("bt_api.") or name == "bt_api_py"
    for name in sys.modules
)
print(json.dumps({"status": "AI_WHEEL_REVIEW_INTEROP_PASS", "evidence_sha256": digest}))
'''


def _run_checked(command: Sequence[str]) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(
            tuple(command),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError:
        raise AiWheelInteropError("isolated wheel verifier could not start a required process") from None
    if completed.returncode != 0:
        raise AiWheelInteropError("isolated wheel verifier subprocess failed")
    return completed


def verify_wheel_interop(
    wheels: Sequence[Tuple[str, Path, str]], *, python_executable: Path
) -> Dict[str, object]:
    """Install supplied wheels locally and validate their read-only wire contract."""

    python_path = Path(python_executable)
    try:
        executable_stat = os.stat(str(python_path))
    except OSError as err:
        raise AiWheelInteropError("Python executable is unavailable") from err
    if not stat.S_ISREG(executable_stat.st_mode):
        raise AiWheelInteropError("Python executable is unavailable")
    with tempfile.TemporaryDirectory(prefix="iteration41-ai-wheel-") as temporary:
        target = Path(temporary) / "site"
        install = [
            str(python_path),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--target",
            str(target),
        ]
        install.extend(str(path) for _, path, _ in wheels)
        _run_checked(install)
        child = _run_checked([str(python_path), "-I", "-S", "-c", _CHILD_PROGRAM, str(target)])
    try:
        result = json.loads(child.stdout)
    except (TypeError, ValueError):
        raise AiWheelInteropError("isolated wheel verifier emitted an invalid result") from None
    if result.get("status") != "AI_WHEEL_REVIEW_INTEROP_PASS":
        raise AiWheelInteropError("isolated wheel verifier did not confirm review-only interop")
    digest = result.get("evidence_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise AiWheelInteropError("isolated wheel verifier returned an invalid evidence digest")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "LOCAL_WHEEL_REVIEW_INTEROP_PASS",
        "isolated_python_flags": ["-I", "-S"],
        "network": "not_opened_by_evidence_vector",
        "authority": "review_only",
        "evidence_sha256": digest,
        "wheels": [
            {"product": product, "sha256": _sha256_file(path), "module": module}
            for product, path, module in wheels
        ],
        "limitations": [
            "This local wheel vector proves only portable read-only evidence compatibility.",
            "It does not prove release provenance, a trusted deployment manifest, provider access, or live admission.",
            "The supplied wheel hashes must be independently reviewed before any deployment use.",
        ],
    }


def _write_json_atomically(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".iteration41-ai-wheel-result-", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="verify Iteration 41 AI review evidence in three supplied isolated wheels"
    )
    parser.add_argument("--agent-wheel", required=True, type=Path)
    parser.add_argument("--skills-wheel", required=True, type=Path)
    parser.add_argument("--mcp-wheel", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python", default=Path(sys.executable), type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = verify_wheel_interop(_wheel_inputs(args), python_executable=args.python)
    except AiWheelInteropError as error:
        print(json.dumps({"status": "REJECTED", "reason": str(error)}, ensure_ascii=False))
        return 2
    _write_json_atomically(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the acceptance command.
    raise SystemExit(main())
