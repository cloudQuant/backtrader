#!/usr/bin/env python
"""Run one public 028 Alpha003 CLI mode against an installed Backtrader wheel.

This is a small external acceptance driver.  It copies the four public example
files to a fresh directory outside the checkout, verifies the installed wheel
through Iteration 50's RECORD/origin checker in the CLI child, and runs only
dry, research, or local replay.  Live SDK construction belongs to the runner's
factory-boundary tests and is intentionally outside this fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Mapping, Optional, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXAMPLE = REPOSITORY_ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
PUBLIC_FILES = ("run.py", "entry_tier.py", "alpha003_strategy.py", "config.yaml")
SAFE_MODES = ("dry", "research", "replay")
EXPECTED_STATUSES = {
    "dry": "DRY_VALIDATION_COMPLETE",
    "research": "RESEARCH_COMPLETE",
    "replay": "REPLAY_COMPLETE",
}
RECEIPT_NAME = "iteration51-installed-cli-fixture.json"
_CHILD_MARKER = "ITERATION51_INSTALLED_CHILD="


class InstalledFixtureError(RuntimeError):
    """A public installed-wheel CLI check could not prove its contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def _require_external(path: Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    if _is_within(resolved, REPOSITORY_ROOT):
        raise InstalledFixtureError(label + " must be outside the Backtrader checkout")
    return resolved


def copy_public_example(
    source_dir: Path,
    destination: Path,
    *,
    offline_config: Optional[Path] = None,
) -> tuple[Path, Path, dict[str, dict[str, Any]]]:
    """Copy exactly the four public runtime files into a new external folder.

    An optional offline configuration is copied separately as
    ``fixture-config.yaml``; it never replaces the pinned public template.
    """

    source = Path(source_dir).expanduser().resolve(strict=True)
    if not source.is_dir():
        raise InstalledFixtureError("public example source is not a directory")
    target = _require_external(Path(destination), label="example destination")
    if target.exists():
        raise InstalledFixtureError("example destination must not already exist")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()

    source_files = {name: source / name for name in PUBLIC_FILES}
    for name, source_path in source_files.items():
        if source_path.is_symlink() or not source_path.is_file():
            raise InstalledFixtureError("public example file is missing or not regular: " + name)
    config_source = None
    if offline_config is not None:
        original_config = Path(offline_config).expanduser()
        if original_config.is_symlink():
            raise InstalledFixtureError("offline config must not be a symlink")
        config_source = original_config.resolve(strict=True)
        if (
            not config_source.is_file()
            or config_source.suffix.lower() not in {".yaml", ".yml"}
            or not _is_within(config_source, target.parent)
        ):
            raise InstalledFixtureError(
                "offline config must be a regular YAML fixture inside the external workspace"
            )

    files: dict[str, dict[str, Any]] = {}
    for name, source_path in source_files.items():
        destination_path = target / name
        shutil.copyfile(source_path, destination_path)
        source_hash = _sha256(source_path)
        destination_hash = _sha256(destination_path)
        if source_hash != destination_hash:
            raise InstalledFixtureError("public example copy changed bytes: " + name)
        files[name] = {
            "sha256": source_hash,
            "size_bytes": source_path.stat().st_size,
        }

    config_path = target / "config.yaml"
    if config_source is not None:
        config_path = target / "fixture-config.yaml"
        shutil.copyfile(config_source, config_path)
        files["fixture-config.yaml"] = {
            "sha256": _sha256(config_path),
            "size_bytes": config_path.stat().st_size,
            "role": "caller-supplied-public-offline-config",
        }
    return target, config_path, files


def _config_paths(config: Mapping[str, Any], config_path: Path, workspace: Path, mode: str):
    """Validate offline input/output paths stay inside the isolated workspace."""

    if config.get("mode") == "live":
        raise InstalledFixtureError("live configs are outside this installed fixture")
    output = config.get("output")
    selection = config.get("selection")
    inputs = config.get("inputs")
    if not all(isinstance(value, Mapping) for value in (output, selection, inputs)):
        raise InstalledFixtureError("offline config sections are malformed")
    if output.get("evaluate_with_fincore") is True:
        raise InstalledFixtureError("fincore evaluation is outside this fixture")
    if selection.get("daily_bundles"):
        raise InstalledFixtureError("offline daily rollover is outside this fixture")

    candidates = [
        ("selection.bundle", selection.get("bundle"), True),
        ("inputs.minute_tape", inputs.get("minute_tape"), True),
    ]
    if mode == "replay":
        candidates.extend(
            (
                ("inputs.execution_quotes", inputs.get("execution_quotes"), True),
                ("inputs.instrument_metadata", inputs.get("instrument_metadata"), True),
            )
        )
        candidates.append(("output.decision_tape_path", output.get("decision_tape_path"), False))
    candidates.append(("output.directory", output.get("directory"), False))

    resolved = {}
    for label, value, must_exist in candidates:
        if type(value) is not str or not value or value != value.strip():
            raise InstalledFixtureError(label + " must be explicitly configured")
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = config_path.parent / path
        if path.is_symlink():
            raise InstalledFixtureError(label + " must not be a symlink")
        path = path.resolve(strict=False)
        if not _is_within(path, workspace):
            raise InstalledFixtureError(label + " must resolve inside the external workspace")
        if must_exist and (not path.is_file() or path.is_symlink()):
            raise InstalledFixtureError(label + " must name an existing regular fixture file")
        if label == "output.directory" and path.exists():
            raise InstalledFixtureError("offline output directory must be new")
        if label == "output.decision_tape_path" and path.exists():
            raise InstalledFixtureError("decision tape destination must be new")
        resolved[label] = str(path)
    return resolved


def validate_offline_config(config_path: Path, workspace: Path, mode: str) -> dict[str, str]:
    if mode not in SAFE_MODES:
        raise InstalledFixtureError("mode is outside the safe installed-fixture set")
    if mode == "dry":
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise InstalledFixtureError("PyYAML is required to validate an offline config") from exc
    try:
        with Path(config_path).open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise InstalledFixtureError("offline YAML config could not be read") from exc
    if not isinstance(config, Mapping):
        raise InstalledFixtureError("offline YAML config must contain an object")
    return _config_paths(config, config_path, workspace, mode)


_CHILD_CODE = r"""import importlib.util, json, runpy, sys, tempfile
from pathlib import Path
helper_path, wheel_path, wheel_hash, example_dir, config_path, mode, factor_mode, cli_argv_json = sys.argv[1:]
cache = tempfile.TemporaryDirectory(prefix="iteration51-installed-pycache-")
cache_path = Path(cache.name).resolve()
if any(cache_path.iterdir()):
    raise RuntimeError("fixture cache is not fresh")
sys.pycache_prefix = str(cache_path)
spec = importlib.util.spec_from_file_location("iteration50_installed_fixture_reused", helper_path)
if spec is None or spec.loader is None:
    raise RuntimeError("Iteration 50 verifier is unavailable")
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)
installed, binding = helper._verify_installed_distribution(Path(wheel_path), wheel_hash)
before = binding["loaded_modules"]
example = Path(example_dir).resolve(strict=True)
sys.path.insert(0, str(example))
sys.argv = json.loads(cli_argv_json)
exit_code = 0
try:
    runpy.run_path(str(example / "run.py"), run_name="__main__")
except SystemExit as result:
    if result.code is None:
        exit_code = 0
    elif type(result.code) is int:
        exit_code = result.code
    else:
        exit_code = 1
after = helper._snapshot_loaded_package_modules(
    binding["install_root"], binding["record_hashes"], binding["wheel_payload_hashes"],
    previous=before,
)
origins = []
for name, (_module, path, digest) in sorted(after.items()):
    relative = Path(path).resolve().relative_to(binding["install_root"]).as_posix()
    origins.append([name, relative, digest])
print("ITERATION51_INSTALLED_CHILD=" + json.dumps({
    "exit_code": exit_code,
    "distribution": installed["distribution"],
    "version": installed["version"],
    "wheel_sha256": installed["wheel"]["sha256"],
    "record_sha256": installed["record_sha256"],
    "loaded_modules_verified": len(after),
    "module_origins_sha256": __import__("hashlib").sha256(
        json.dumps(origins, separators=(",", ":")).encode("utf-8")
    ).hexdigest(),
    "fresh_bytecode_cache": bool(sys.pycache_prefix == str(cache_path)),
}, sort_keys=True, separators=(",", ":")))
raise SystemExit(exit_code)
"""


def _sanitized_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTHONPYCACHEPREFIX",
        "PYTHONDONTWRITEBYTECODE",
        "BT_SIMNOW_CONFIG_JSON",
        "BT_API_TEST_SOURCE_ROOTS",
    ):
        environment.pop(name, None)
    return environment


def _child_command(
    *,
    verifier_path: Path,
    wheel_path: Path,
    wheel_sha256: str,
    example_dir: Path,
    config_path: Path,
    mode: str,
    factor_mode: str,
    python: str = sys.executable,
) -> list[str]:
    if mode not in SAFE_MODES:
        raise InstalledFixtureError("mode is outside the safe installed-fixture set")
    if factor_mode not in {"native", "build"}:
        raise InstalledFixtureError("factor mode must be native or build")
    public_cli_argv = [
        str(Path(example_dir).resolve(strict=True) / "run.py"),
        "--config",
        str(Path(config_path).resolve(strict=True)),
        "--mode",
        mode,
        "--factor-mode",
        factor_mode,
    ]
    return [
        python,
        "-I",
        "-c",
        _CHILD_CODE,
        str(Path(verifier_path).resolve(strict=True)),
        str(Path(wheel_path).resolve(strict=True)),
        wheel_sha256,
        str(Path(example_dir).resolve(strict=True)),
        str(Path(config_path).resolve(strict=True)),
        mode,
        factor_mode,
        json.dumps(public_cli_argv, separators=(",", ":")),
    ]


def _last_json_object(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_CHILD_MARKER):
            continue
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    raise InstalledFixtureError("public CLI did not emit a JSON result")


def _child_receipt(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.startswith(_CHILD_MARKER):
            continue
        try:
            value = json.loads(line[len(_CHILD_MARKER) :])
        except json.JSONDecodeError as exc:
            raise InstalledFixtureError("installed-child receipt is malformed") from exc
        if isinstance(value, dict):
            return value
    raise InstalledFixtureError("installed-child origin receipt is missing")


def run_cli_case(
    *,
    example_dir: Path,
    config_path: Path,
    wheel_path: Path,
    wheel_sha256: str,
    mode: str,
    factor_mode: str,
    timeout_seconds: float = 180.0,
    python: str = sys.executable,
) -> dict[str, Any]:
    if mode not in SAFE_MODES:
        raise InstalledFixtureError("mode is outside the safe installed-fixture set")
    if factor_mode not in {"native", "build"}:
        raise InstalledFixtureError("factor mode must be native or build")
    if not Path(example_dir, "run.py").is_file():
        raise InstalledFixtureError("copied public runner is unavailable")
    command = _child_command(
        verifier_path=Path(__file__).with_name("iteration50_installed_fixture.py"),
        wheel_path=wheel_path,
        wheel_sha256=wheel_sha256,
        example_dir=example_dir,
        config_path=config_path,
        mode=mode,
        factor_mode=factor_mode,
        python=python,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(example_dir).resolve()),
            env=_sanitized_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstalledFixtureError("public CLI exceeded its bounded timeout") from exc
    summary = _last_json_object(completed.stdout)
    child = _child_receipt(completed.stdout)
    expected_status = EXPECTED_STATUSES[mode]
    if (
        completed.returncode != 0
        or child.get("exit_code") != completed.returncode
        or summary.get("status") != expected_status
        or child.get("wheel_sha256") != wheel_sha256
        or child.get("loaded_modules_verified", 0) <= 0
        or child.get("fresh_bytecode_cache") is not True
    ):
        raise InstalledFixtureError("public CLI or installed-origin acceptance failed")
    return {
        "mode": mode,
        "factor_mode": factor_mode,
        "cli_argv": [
            str(Path(example_dir).resolve() / "run.py"),
            "--config",
            str(Path(config_path).resolve()),
            "--mode",
            mode,
            "--factor-mode",
            factor_mode,
        ],
        "exit_code": completed.returncode,
        "status": summary["status"],
        "summary": summary,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
        "installed_child": child,
    }


_INPUT_FILE_LABELS = (
    "selection.bundle",
    "inputs.minute_tape",
    "inputs.execution_quotes",
    "inputs.instrument_metadata",
)


def _input_evidence(paths: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    evidence = {}
    for label in _INPUT_FILE_LABELS:
        value = paths.get(label)
        if value is None:
            continue
        path = Path(value).resolve(strict=True)
        if not path.is_file() or path.is_symlink():
            raise InstalledFixtureError(label + " is no longer a regular input file")
        evidence[label] = {
            "path": str(path),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
    return evidence


def _write_receipt(workspace: Path, payload: Mapping[str, Any]) -> Path:
    path = Path(workspace) / RECEIPT_NAME
    if path.exists():
        raise InstalledFixtureError("fixture receipt destination already exists")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--example-source", type=Path, default=DEFAULT_EXAMPLE)
    parser.add_argument("--config", type=Path, help="public offline YAML config inside workspace")
    parser.add_argument("--mode", choices=SAFE_MODES, required=True)
    parser.add_argument("--factor-mode", choices=("native", "build"), required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)
    try:
        wheel = Path(args.wheel).expanduser().resolve(strict=True)
        if not wheel.is_file() or wheel.suffix.lower() != ".whl":
            raise InstalledFixtureError("wheel must be an existing .whl file")
        wheel_hash = args.wheel_sha256
        if (
            type(wheel_hash) is not str
            or len(wheel_hash) != 64
            or any(value not in "0123456789abcdef" for value in wheel_hash)
            or _sha256(wheel) != wheel_hash
        ):
            raise InstalledFixtureError("wheel does not match the supplied SHA-256")
        if not (0 < args.timeout_seconds <= 1800):
            raise InstalledFixtureError("timeout must be finite and at most 1800 seconds")
        workspace = _require_external(args.workspace, label="workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        config_source = args.config
        if config_source is not None:
            config_source = Path(config_source).expanduser().resolve(strict=True)
            if not _is_within(config_source, workspace):
                raise InstalledFixtureError("offline config must be inside the external workspace")
        copied_dir = workspace / "028_alpha003_simnow_minute"
        copied_dir, config_path, file_pins = copy_public_example(
            args.example_source,
            copied_dir,
            offline_config=config_source,
        )
        resolved_inputs = validate_offline_config(config_path, workspace, args.mode)
        input_evidence = _input_evidence(resolved_inputs)
        result = run_cli_case(
            example_dir=copied_dir,
            config_path=config_path,
            wheel_path=wheel,
            wheel_sha256=wheel_hash,
            mode=args.mode,
            factor_mode=args.factor_mode,
            timeout_seconds=args.timeout_seconds,
        )
        if _input_evidence(resolved_inputs) != input_evidence:
            raise InstalledFixtureError("offline fixture inputs changed during the CLI run")
        receipt = {
            "schema": "backtrader.iteration51.installed_cli_fixture.v1",
            "status": "PASS_INSTALLED_PUBLIC_CLI_FIXTURE",
            "evidence_level": "INSTALLED_WHEEL_PUBLIC_CLI_FIXTURE_ONLY",
            "source_files": file_pins,
            "workspace": str(workspace),
            "copied_example": str(copied_dir),
            "config_path": str(config_path),
            "offline_input_evidence": input_evidence,
            "wheel": {"path": str(wheel), "sha256": wheel_hash},
            "command_result": result,
        }
        receipt_path = _write_receipt(workspace, receipt)
        print(
            json.dumps({"status": receipt["status"], "receipt": str(receipt_path)}, sort_keys=True)
        )
        return 0
    except (InstalledFixtureError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
