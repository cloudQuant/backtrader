"""Run paired, fresh-process benchmarks for factor-research examples 025-027.

The harness executes each checkout's real ``run.py`` with the selected data
snapshot and symbol limit. One full-size warmup runs per checkout/example,
followed by alternating baseline/candidate runs for every measured group.
Parent-side psutil samples record wall time, process-tree CPU, and peak RSS.
Examples 025/026 export the PNGs declared by fincore's evaluation manifest by
default; ``--no-charts`` selects diagnostic-only runs.
The default 500-symbol profile is the minimum formal sample floor; runs with a
smaller explicit symbol limit are labeled ``SMOKE_ONLY`` in the result manifest.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

EXAMPLES = ("025", "026", "027")
EXAMPLE_DIRS = {
    "025": Path("examples/backtest/025_factor_single"),
    "026": Path("examples/backtest/026_factor_multi"),
    "027": Path("examples/backtest/027_alpha003_panel_acceptance"),
}
FORMAL_MINIMUM_SYMBOLS = 500
EXPECTED_PANEL_CSVS = frozenset(
    {
        "factors.csv",
        "grid.csv",
        "groups.csv",
        "prices_close.csv",
        "prices_open.csv",
        "universe.csv",
    }
)
REQUIRED_EVALUATION_TABLES = ("labels.csv", "ic.csv", "signals.csv")
EXPECTED_FACTORS = {
    "025": ("close_ma",),
    "026": ("close_ma", "roc", "kdj_j"),
    "027": ("alpha003",),
}
SOURCE_SUFFIXES = {".py", ".yaml"}
CONFIG_DIFFERENCE_ALLOWLIST = {
    "operator_profile": {
        "example": "027",
        "baseline": "alpha101-v1",
        "candidate": "alpha101-v2",
        "reason": "native Alpha003 moved to the alpha101-v2 float64 operator profile; the frozen alpha101-v1 runtime cannot run that profile",
        "scope": "allowed for end-to-end comparison only; not evidence for isolated structural or float-profile attribution",
    }
}
PROBE_SOURCE = r"""
import importlib.util, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd()))
import backtrader
import backtrader.research as research
fincore = importlib.util.find_spec('fincore')
print(json.dumps({
    'backtrader': str(pathlib.Path(backtrader.__file__).resolve()),
    'research': str(pathlib.Path(research.__file__).resolve()),
    'fincore': None if fincore is None else fincore.origin,
    'python': sys.executable,
}))
"""
FULL_REVISION_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
REPORT_SEMANTICS_FILENAME = "report_semantics.json"
REPORT_SEMANTICS_SCHEMA = "factor-report-semantics-v1"
REPORT_CAPTURE_NOTE = (
    "Measured wall/CPU/RSS include in-process ReportDocument capture, semantic payload "
    "serialization, HTML hashing, and sidecar writing; these are instrumented end-to-end "
    "measurements, not uninstrumented production performance."
)


class ModePairComparisonError(RuntimeError):
    """A strict pair comparison failed after its evidence record was written."""

    def __init__(self, message: str, record: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.record = dict(record)


CAPTURED_ENTRYPOINT_SOURCE = r"""
import importlib.util
import hashlib
import runpy
import sys
from pathlib import Path

helper_path, expected_helper_sha256, checkout_root, entrypoint, output_dir, *entry_args = sys.argv[1:]
actual_helper_sha256 = hashlib.sha256(Path(helper_path).read_bytes()).hexdigest()
if actual_helper_sha256 != expected_helper_sha256:
    raise RuntimeError("current report-semantics helper changed before load")
spec = importlib.util.spec_from_file_location("_factor_pair_semantics_current", helper_path)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load current report-semantics helper: " + helper_path)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
root = str(Path(checkout_root).resolve())
if root not in sys.path:
    sys.path.insert(0, root)
script_dir = str(Path(entrypoint).resolve().parent)
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
sys.argv = [entrypoint, *entry_args]
namespace = runpy.run_path(entrypoint, run_name="_factor_pair_entrypoint")
main = namespace.get("main")
if not callable(main):
    raise RuntimeError("example entrypoint has no callable main(): " + entrypoint)
with helper.capture_report_semantics(Path(output_dir)):
    status = main(entry_args)
    if status not in (None, 0):
        raise SystemExit(status)
raise SystemExit(0)
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _process_environment(root: Path) -> Dict[str, str]:
    """Bind imports to this checkout and drop any inherited PYTHONPATH."""
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONPATH"] = str(root.resolve())
    return environment


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _selected_input_manifest(data_dir: Path, symbols: int) -> Dict[str, Any]:
    """Hash the exact ordered asset subset and calendar used by this run."""
    try:
        from scripts.diagnose_factor_research_pipeline import _input_manifest
    except ImportError:
        from diagnose_factor_research_pipeline import _input_manifest
    return _input_manifest(data_dir, symbols)


def _load_pair_semantics_helper() -> Any:
    """Load the comparator beside this current harness, never from a tested checkout."""
    helper_path = Path(__file__).resolve().with_name("verify_factor_research_pair_semantics.py")
    spec = importlib.util.spec_from_file_location("_factor_pair_semantics_current", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load current pair semantics helper: %s" % helper_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_factor_modes(
    baseline: Optional[str], candidate: Optional[str]
) -> Optional[Dict[str, str]]:
    if baseline is None and candidate is None:
        return None
    if baseline is None or candidate is None:
        raise ValueError("both --baseline-factor-mode and --candidate-factor-mode are required")
    if baseline == candidate:
        raise ValueError("paired factor modes must differ")
    return {"baseline": baseline, "candidate": candidate}


def _source_drift(
    before: Mapping[str, str], after: Mapping[str, str]
) -> Dict[str, List[Optional[str]]]:
    return {
        path: [before.get(path), after.get(path)]
        for path in sorted(set(before) | set(after))
        if before.get(path) != after.get(path)
    }


def _origin_identity(root: Path, origin: Any) -> Tuple[str, str]:
    if not isinstance(origin, str) or not origin:
        raise ValueError("module origin is missing")
    path = Path(origin).resolve()
    if _path_inside(path, root):
        return "checkout", path.relative_to(root.resolve()).as_posix()
    return "external", str(path)


def _validate_factor_mode_pair(sides: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Require identical source/runtime provenance before attributing mode differences."""
    baseline = sides["baseline"]
    candidate = sides["candidate"]
    baseline_revision = str(baseline.get("source_revision") or "")
    candidate_revision = str(candidate.get("source_revision") or "")
    if not FULL_REVISION_RE.fullmatch(baseline_revision) or not FULL_REVISION_RE.fullmatch(
        candidate_revision
    ):
        raise ValueError("mode-pair comparison requires full 40- or 64-character source revisions")
    if baseline_revision.lower() != candidate_revision.lower():
        raise ValueError("mode-pair source revisions differ")
    if baseline.get("source_hashes") != candidate.get("source_hashes"):
        raise ValueError("mode-pair source file hashes differ")
    if baseline.get("execution_environment_sha256") != candidate.get(
        "execution_environment_sha256"
    ):
        raise ValueError("mode-pair execution environments differ")

    module_identities = {}
    for name in ("backtrader", "research", "fincore"):
        side_identities = {}
        for side, metadata in (("baseline", baseline), ("candidate", candidate)):
            probe = metadata.get("module_probe", {})
            modules = probe.get("modules", {}) if isinstance(probe, Mapping) else {}
            hashes = probe.get("module_source_sha256", {}) if isinstance(probe, Mapping) else {}
            origin = modules.get(name) if isinstance(modules, Mapping) else None
            digest = hashes.get(name) if isinstance(hashes, Mapping) else None
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ValueError(
                    "mode-pair %s source hash is missing or invalid for %s" % (name, side)
                )
            side_identities[side] = {
                "origin": _origin_identity(Path(metadata["root"]), origin),
                "source_sha256": digest.lower(),
            }
        if side_identities["baseline"] != side_identities["candidate"]:
            raise ValueError("mode-pair %s origins or source hashes differ" % name)
        module_identities[name] = side_identities
    return {
        "status": "IDENTICAL_RUNTIME_PROVENANCE",
        "source_revision": baseline_revision,
        "source_manifest_sha256": baseline.get("source_manifest_sha256"),
        "execution_environment_sha256": baseline.get("execution_environment_sha256"),
        "modules": module_identities,
    }


def _git_head(root: Path) -> Optional[str]:
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(root), capture_output=True, text=True
    )
    if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != root.resolve():
        return None
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=str(root), capture_output=True, text=True
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _git_status(root: Path) -> str:
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(root), capture_output=True, text=True
    )
    if top_level.returncode != 0 or Path(top_level.stdout.strip()).resolve() != root.resolve():
        return ""
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _source_manifest(root: Path) -> Dict[str, str]:
    paths = set()
    for package in ("backtrader", "backtrader_runtime", "scripts"):
        directory = root / package
        if directory.is_dir():
            paths.update(directory.rglob("*.py"))
    colocated_fincore = root / "fincore"
    if colocated_fincore.is_dir():
        paths.update(path for path in colocated_fincore.rglob("*.py") if path.is_file())
    for relative in EXAMPLE_DIRS.values():
        directory = root / relative
        if directory.is_dir():
            paths.update(
                path
                for path in directory.rglob("*")
                if path.is_file() and (path.suffix in SOURCE_SUFFIXES or path.name == "config.yaml")
            )
    for path in root.glob("requirements*.txt"):
        if path.is_file():
            paths.add(path)
    for filename in (
        "setup.py",
        "pyproject.toml",
        "setup.cfg",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "conda-lock.yml",
        "environment.yml",
    ):
        path = root / filename
        if path.is_file():
            paths.add(path)
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(paths, key=lambda item: item.as_posix())
    }


def _dependency_snapshot() -> Dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise RuntimeError("pip freeze failed: %s" % completed.stderr[-2000:])
    packages = sorted(line.strip() for line in completed.stdout.splitlines() if line.strip())
    return {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "pip_freeze_returncode": completed.returncode,
        "pip_freeze": packages,
        "pip_freeze_sha256": _canonical_hash(packages),
        "pip_freeze_stderr": completed.stderr[-2000:],
    }


def _effective_config(root: Path, example: str, data_dir: Path, symbols: int) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to record benchmark input configuration") from exc
    path = root / EXAMPLE_DIRS[example] / "config.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
        raise ValueError("invalid example config: %s" % path)
    value = copy.deepcopy(value)
    value["data"]["directory"] = str(data_dir)
    value["data"]["max_symbols"] = symbols
    return value


def _probe_modules(root: Path) -> Dict[str, Any]:
    environment = _process_environment(root)
    completed = subprocess.run(
        [sys.executable, "-c", PROBE_SOURCE],
        cwd=str(root),
        env=environment,
        capture_output=True,
        text=True,
    )
    details: Dict[str, Any] = {
        "command": [sys.executable, "-c", PROBE_SOURCE],
        "returncode": completed.returncode,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }
    if completed.returncode == 0:
        try:
            details["modules"] = json.loads(completed.stdout.strip().splitlines()[-1])
            details["module_source_sha256"] = {}
            for name, source in details["modules"].items():
                if name not in ("backtrader", "research", "fincore"):
                    continue
                path = Path(source) if isinstance(source, str) else None
                details["module_source_sha256"][name] = (
                    _sha256(path) if path is not None and path.is_file() else None
                )
        except (ValueError, IndexError):
            details["parse_error"] = "module probe did not return JSON"
    return details


def _probe_entrypoint(
    root: Path,
    example: str,
    requested_save: bool = True,
    require_factor_mode: bool = False,
) -> Dict[str, Any]:
    script = root / EXAMPLE_DIRS[example] / "run.py"
    command = [sys.executable, str(script), "--help"]
    completed = subprocess.run(
        command,
        cwd=str(root),
        env=_process_environment(root),
        capture_output=True,
        text=True,
    )
    help_text = completed.stdout + completed.stderr
    option_names = (
        "--data-dir",
        "--max-symbols",
        "--report",
        "--no-charts",
        "--save-panel",
        "--save-dataset",
    )
    if require_factor_mode:
        option_names += ("--factor-mode",)
    options = {option: option in help_text for option in option_names}
    if completed.returncode != 0:
        raise RuntimeError("%s %s --help failed: %s" % (example, script, help_text[-2000:]))
    for required in ("--data-dir", "--max-symbols", "--report"):
        if not options[required]:
            raise RuntimeError("%s entrypoint does not support %s" % (script, required))
    if require_factor_mode and not options["--factor-mode"]:
        raise RuntimeError("%s entrypoint does not support --factor-mode" % script)
    if example in ("025", "026"):
        if options["--save-panel"]:
            save_mode = "factor_panel_csv"
        elif options["--save-dataset"]:
            save_mode = "legacy_research_dataset"
        else:
            if requested_save:
                raise RuntimeError("%s supports neither --save-panel nor --save-dataset" % script)
            save_mode = None
    else:
        save_mode = "factor_values_csv_only"
    return {
        "command": command,
        "returncode": completed.returncode,
        "options": options,
        "save_mode": save_mode,
        "help_sha256": hashlib.sha256(help_text.encode("utf-8")).hexdigest(),
        "help_tail": help_text[-2000:],
    }


def _inspect_side(
    root: Path,
    name: str,
    data_dir: Path,
    symbols: int,
    declared_revision: Optional[str],
    execution_environment: Mapping[str, Any],
    examples: Sequence[str] = EXAMPLES,
    requested_save: bool = True,
    require_factor_mode: bool = False,
) -> Dict[str, Any]:
    if not (root / "backtrader" / "__init__.py").is_file():
        raise ValueError("%s root is not a Backtrader source checkout: %s" % (name, root))
    configs = {}
    config_hashes = {}
    for example in examples:
        config_path = root / EXAMPLE_DIRS[example] / "config.yaml"
        for filename in ("run.py", "config.yaml"):
            if not (config_path.parent / filename).is_file():
                raise FileNotFoundError(
                    "missing benchmark input: %s" % (config_path.parent / filename)
                )
        configs[example] = _effective_config(root, example, data_dir, symbols)
        config_hashes[example] = _sha256(config_path)
    entrypoints = {
        example: _probe_entrypoint(
            root,
            example,
            requested_save=requested_save,
            require_factor_mode=require_factor_mode,
        )
        for example in examples
    }
    module_probe = _probe_modules(root)
    _validate_colocated_fincore_origin(root, module_probe)
    source_hashes = _source_manifest(root)
    git_status = _git_status(root)
    git_head = _git_head(root)
    return {
        "name": name,
        "root": str(root),
        "git_head": git_head,
        "source_revision": git_head or declared_revision,
        "source_revision_method": "git" if git_head else "explicit_cli",
        "git_status": git_status,
        "git_status_sha256": hashlib.sha256(git_status.encode("utf-8")).hexdigest(),
        "source_hashes": source_hashes,
        "source_manifest_sha256": _canonical_hash(source_hashes),
        "config_sha256": config_hashes,
        "effective_config_sha256": {
            example: _canonical_hash(configs[example]) for example in examples
        },
        "effective_configs": configs,
        "entrypoints": entrypoints,
        "requested_save": requested_save,
        "pythonpath": str(root),
        "module_probe": module_probe,
        "execution_environment_sha256": _canonical_hash(execution_environment),
        "dependency_declaration_sha256": {
            path: digest
            for path, digest in source_hashes.items()
            if path.startswith("requirements")
            or path
            in {
                "setup.py",
                "pyproject.toml",
                "setup.cfg",
                "Pipfile.lock",
                "poetry.lock",
                "uv.lock",
                "conda-lock.yml",
                "environment.yml",
            }
        },
    }


def _config_differences(left: Any, right: Any, prefix: str = "") -> List[Dict[str, Any]]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        keys = sorted(set(left) | set(right))
        differences = []
        for key in keys:
            path = "%s.%s" % (prefix, key) if prefix else str(key)
            if key not in left or key not in right:
                differences.append(
                    {"path": path, "baseline": left.get(key), "candidate": right.get(key)}
                )
            else:
                differences.extend(_config_differences(left[key], right[key], path))
        return differences
    if left != right:
        return [{"path": prefix, "baseline": left, "candidate": right}]
    return []


def _mode_config_comparison(
    sides: Mapping[str, Mapping[str, Any]],
    modes: Mapping[str, str],
    examples: Sequence[str],
) -> Dict[str, Any]:
    differences = {}
    for example in examples:
        configs = {}
        for side in ("baseline", "candidate"):
            configs[side] = copy.deepcopy(sides[side]["effective_configs"][example])
            configs[side]["factor_mode"] = modes[side]
        differences[example] = _config_differences(configs["baseline"], configs["candidate"])
        if differences[example] != [
            {
                "path": "factor_mode",
                "baseline": modes["baseline"],
                "candidate": modes["candidate"],
            }
        ]:
            raise ValueError(
                "mode-pair effective configuration must differ only at factor_mode for %s: %s"
                % (example, json.dumps(differences[example], ensure_ascii=False))
            )
    return {
        "equal_except_factor_mode": True,
        "expected_difference": {
            "path": "factor_mode",
            "baseline": modes["baseline"],
            "candidate": modes["candidate"],
        },
        "differences": differences,
    }


def _compare_mode_runs(
    *,
    output: Path,
    example: str,
    kind: str,
    group: Optional[int],
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    helper = _load_pair_semantics_helper()
    baseline_dir = Path(baseline["output_dir"])
    candidate_dir = Path(candidate["output_dir"])
    comparison_path = (
        output
        / "paired-comparisons"
        / example
        / ("warmup" if group is None else "group-%02d" % group)
        / "comparison.json"
    )
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    record: Dict[str, Any] = {
        "example": example,
        "kind": kind,
        "group": group,
        "baseline_run": str(baseline_dir),
        "candidate_run": str(candidate_dir),
        "helper_path": str(Path(helper.__file__).resolve()),
        "helper_sha256": _sha256(Path(helper.__file__).resolve()),
        "requirements": {
            "reports": True,
            "mode_pair": True,
            "panel_pair": example in ("025", "026"),
        },
    }
    try:
        result = helper.compare_runs(
            baseline_dir,
            candidate_dir,
            require_reports=True,
            require_mode_pair=True,
            require_panel_pair=example in ("025", "026"),
        )
        record["comparison"] = result
        record["status"] = (
            "OK" if isinstance(result, Mapping) and result.get("strict_equal") is True else "FAILED"
        )
        if record["status"] != "OK":
            record["error"] = "paired output comparison did not pass strict equality"
    except Exception as exc:
        record["status"] = "FAILED"
        record["error"] = "%s: %s" % (type(exc).__name__, exc)
    serialized = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    comparison_path.write_text(serialized, encoding="utf-8")
    record["comparison_path"] = str(comparison_path)
    record["comparison_sha256"] = _sha256(comparison_path)
    if record["status"] != "OK":
        raise ModePairComparisonError(
            "%s %s mode-pair comparison failed: %s"
            % (example, kind, record.get("error", "unknown comparison failure")),
            record,
        )
    return record


def _append_mode_comparison(payload: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    try:
        record = _compare_mode_runs(**kwargs)
    except ModePairComparisonError as exc:
        payload["paired_comparisons"].append(exc.record)
        raise
    payload["paired_comparisons"].append(record)
    return record


def _classify_config_differences(
    differences: Mapping[str, Sequence[Mapping[str, Any]]],
    requested_allowlist: Sequence[str],
) -> Dict[str, Any]:
    """Allow only explicitly named, exact input migrations; fail on all others."""
    requested = set(requested_allowlist)
    allowed = []
    unapproved = []
    for example, items in differences.items():
        for difference in items:
            key = str(difference.get("path"))
            policy = CONFIG_DIFFERENCE_ALLOWLIST.get(key)
            approved = bool(
                policy
                and key in requested
                and example == policy["example"]
                and difference.get("baseline") == policy["baseline"]
                and difference.get("candidate") == policy["candidate"]
            )
            entry = {"example": example, **dict(difference)}
            if approved:
                entry["approved"] = True
                entry["reason"] = policy["reason"]
                entry["scope"] = policy["scope"]
                allowed.append(entry)
            else:
                entry["approved"] = False
                unapproved.append(entry)
    return {
        "allowed_differences": allowed,
        "unapproved_differences": unapproved,
        "compatible": not unapproved,
    }


def _build_command(
    root: Path,
    example: str,
    output_dir: Path,
    data_dir: Path,
    symbols: int,
    save_mode: Optional[str] = None,
    no_charts: bool = False,
    requested_save: bool = True,
    factor_mode: Optional[str] = None,
) -> List[str]:
    command = [
        sys.executable,
        str(root / EXAMPLE_DIRS[example] / "run.py"),
        "--output-dir",
        str(output_dir),
        "--data-dir",
        str(data_dir),
        "--max-symbols",
        str(symbols),
        "--report",
    ]
    if factor_mode is not None:
        if factor_mode not in ("native", "build"):
            raise ValueError("factor_mode must be 'native' or 'build'")
        command.extend(("--factor-mode", factor_mode))
    if example in ("025", "026"):
        if requested_save:
            if save_mode == "legacy_research_dataset":
                command.append("--save-dataset")
            elif save_mode in (None, "factor_panel_csv"):
                command.append("--save-panel")
            else:
                raise ValueError("unsupported saved-panel API for %s: %s" % (example, save_mode))
        if no_charts:
            command.append("--no-charts")
    return command


def _build_captured_command(
    entrypoint_command: Sequence[str], root: Path, output_dir: Path
) -> Tuple[List[str], Dict[str, Any]]:
    if len(entrypoint_command) < 2:
        raise ValueError("entrypoint command is incomplete")
    helper_path = Path(__file__).resolve().with_name("verify_factor_research_pair_semantics.py")
    if not helper_path.is_file():
        raise FileNotFoundError("current report semantics helper is missing: %s" % helper_path)
    helper_sha256 = _sha256(helper_path)
    command = [
        sys.executable,
        "-c",
        CAPTURED_ENTRYPOINT_SOURCE,
        str(helper_path),
        helper_sha256,
        str(root.resolve()),
        str(Path(entrypoint_command[1]).resolve()),
        str(output_dir.resolve()),
        *entrypoint_command[2:],
    ]
    return command, {
        "enabled": True,
        "helper_path": str(helper_path),
        "helper_sha256": helper_sha256,
        "mechanism": (
            "fresh subprocess loads the current comparator helper by absolute path, loads the "
            "side run.py with runpy, and captures the actual ReportDocument during main()"
        ),
        "measurement_note": REPORT_CAPTURE_NOTE,
    }


def _path_inside(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((str(path.resolve()), str(parent.resolve()))) == str(
            parent.resolve()
        )
    except ValueError:
        return False


def _validate_colocated_fincore_origin(root: Path, module_probe: Mapping[str, Any]) -> None:
    """Require probed fincore to match source included beside this checkout."""
    package = root / "fincore"
    if not package.is_dir():
        return
    modules = module_probe.get("modules")
    origin = modules.get("fincore") if isinstance(modules, dict) else None
    if not isinstance(origin, str) or not origin or not _path_inside(Path(origin), package):
        raise ValueError(
            "colocated fincore source exists at %s but module probe resolved fincore outside "
            "that package: %s" % (package, origin)
        )


def _artifact_manifest(path: Path) -> List[Dict[str, Any]]:
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = [item for item in path.rglob("*") if item.is_file()]
    else:
        return []
    manifest = []
    for item in sorted(files, key=lambda item: item.as_posix()):
        entry: Dict[str, Any] = {
            "path": item.relative_to(path if path.is_dir() else path.parent).as_posix(),
            "size_bytes": item.stat().st_size,
            "sha256": _sha256(item),
        }
        if item.suffix.lower() == ".csv":
            with item.open("r", encoding="utf-8-sig", newline="") as handle:
                entry["csv_header"] = handle.readline().rstrip("\r\n")
        manifest.append(entry)
    return manifest


def _summary_report_paths(example: str, summary: Mapping[str, Any], output_dir: Path) -> List[Path]:
    if example == "026":
        values = summary.get("reports")
        if not isinstance(values, list):
            return []
    else:
        value = summary.get("report")
        values = [] if not isinstance(value, str) or not value else [value]
    paths = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = output_dir / path
        paths.append(path.resolve())
    return paths


def _validate_report_semantics(output_dir: Path, example: str) -> Dict[str, Any]:
    sidecar = output_dir / REPORT_SEMANTICS_FILENAME
    result: Dict[str, Any] = {
        "path": str(sidecar),
        "exists": sidecar.is_file(),
        "status": "MISSING",
        "reports": [],
        "sha256": _sha256(sidecar) if sidecar.is_file() else None,
    }
    problems = []
    if not sidecar.is_file() or sidecar.stat().st_size < 1:
        problems.append("report semantics sidecar is missing or empty")
    else:
        try:
            loaded = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            loaded = None
            problems.append(
                "report semantics sidecar is invalid: %s: %s" % (type(exc).__name__, exc)
            )
        if (
            not isinstance(loaded, Mapping)
            or loaded.get("schema_version") != REPORT_SEMANTICS_SCHEMA
        ):
            problems.append("report semantics sidecar schema is missing or unsupported")
        records = loaded.get("reports") if isinstance(loaded, Mapping) else None
        if not isinstance(records, list):
            problems.append("report semantics sidecar reports must be a list")
            records = []
        observed_names = set()
        for record in records:
            if not isinstance(record, Mapping):
                problems.append("report semantics entry must be an object")
                continue
            relative = record.get("html_path")
            path = Path(relative) if isinstance(relative, str) else Path("..")
            if path.is_absolute() or ".." in path.parts:
                problems.append("report semantics entry has an unsafe html_path")
                continue
            html_path = output_dir / path
            observed_names.add(path.as_posix())
            payload = record.get("semantic_payload")
            digest = record.get("semantic_digest")
            html_digest = record.get("html_sha256")
            if not isinstance(payload, Mapping):
                problems.append("report semantics entry has no object semantic_payload")
            elif not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                problems.append("report semantics entry has an invalid semantic_digest")
            else:
                try:
                    canonical = json.dumps(
                        payload,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                except (TypeError, ValueError):
                    problems.append("report semantics payload is not strict JSON")
                else:
                    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != digest.lower():
                        problems.append("report semantics digest does not match its payload")
            if not isinstance(html_digest, str) or not SHA256_RE.fullmatch(html_digest):
                problems.append("report semantics entry has an invalid html_sha256")
            elif (
                not _path_inside(html_path, output_dir)
                or not html_path.is_file()
                or _sha256(html_path) != html_digest.lower()
            ):
                problems.append("report semantics HTML hash does not match rendered report")
            result["reports"].append(dict(record))
        expected_paths = {"factor_report_%s.html" % factor for factor in EXPECTED_FACTORS[example]}
        if observed_names != expected_paths or len(observed_names) != len(records):
            problems.append(
                "report semantics report set differs: expected=%s actual=%s"
                % (sorted(expected_paths), sorted(observed_names))
            )
    result["problems"] = problems
    result["status"] = "OK" if not problems else "FAILED"
    return result


def _csv_stats(path: Path) -> Dict[str, Any]:
    """Read CSV shape and count finite numeric values without retaining all rows."""
    rows = 0
    finite_values: Dict[str, int] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            finite_values = dict.fromkeys(headers, 0)
            for row in reader:
                rows += 1
                for header in headers:
                    value = row.get(header)
                    try:
                        is_finite = math.isfinite(float(value))
                    except (TypeError, ValueError):
                        is_finite = False
                    if is_finite:
                        finite_values[header] += 1
    except (OSError, UnicodeError, csv.Error) as exc:
        return {
            "path": str(path),
            "exists": path.is_file(),
            "rows": 0,
            "headers": [],
            "finite_values": {},
            "error": "%s: %s" % (type(exc).__name__, exc),
        }
    return {
        "path": str(path),
        "exists": True,
        "rows": rows,
        "headers": headers,
        "finite_values": finite_values,
        "error": None,
    }


def _finite_columns_present(stats: Mapping[str, Any], columns: Sequence[str]) -> bool:
    finite_values = stats.get("finite_values", {})
    return all(
        column in stats.get("headers", [])
        and isinstance(finite_values.get(column), int)
        and finite_values[column] > 0
        for column in columns
    )


def _validate_run(
    example: str,
    summary: Optional[Mapping[str, Any]],
    returncode: Optional[int],
    output_dir: Path,
    save_mode: Optional[str] = None,
    requested_symbols: Optional[int] = None,
    charts_enabled: bool = True,
    requested_save: bool = True,
    factor_mode: Optional[str] = None,
    require_report_semantics: bool = False,
) -> Dict[str, Any]:
    problems = []
    evaluation = {
        "requested": example in ("025", "026"),
        "applicable": example in ("025", "026"),
        "status": "NOT_APPLICABLE" if example == "027" else "MISSING",
    }
    if returncode is None:
        problems.append("run.py process did not start or return an exit status")
    elif returncode != 0:
        problems.append("run.py exited with status %d" % returncode)
    if summary is None:
        problems.append("summary.json is missing or invalid")
    else:
        if summary.get("status") != "COMPLETED":
            problems.append("summary status is %r" % summary.get("status"))
        effective_symbols = summary.get("symbols")
        if (
            isinstance(effective_symbols, bool)
            or not isinstance(effective_symbols, int)
            or effective_symbols < 1
        ):
            problems.append("summary symbols is missing or invalid")
        elif requested_symbols is not None and effective_symbols < requested_symbols:
            problems.append(
                "insufficient input symbols: requested %d, effective %d"
                % (requested_symbols, effective_symbols)
            )
        if example in ("025", "026"):
            status = str(summary.get("evaluation_status", "MISSING")).upper()
            evaluation["status"] = status
            if status != "OK":
                problems.append("evaluation status is %s, expected OK" % status)
        if factor_mode is not None and summary.get("factor_mode") != factor_mode:
            problems.append(
                "summary factor_mode is %r, expected %r" % (summary.get("factor_mode"), factor_mode)
            )

    sample_count = {
        "requested": requested_symbols,
        "effective": summary.get("symbols") if summary is not None else None,
        "reported_dates": summary.get("dates") if summary is not None else None,
        "factor_value_rows": None,
        "status": "MISSING",
    }
    if summary is not None:
        effective_symbols = summary.get("symbols")
        if isinstance(effective_symbols, int) and not isinstance(effective_symbols, bool):
            if requested_symbols is None or effective_symbols >= requested_symbols:
                sample_count["status"] = "OK"
            else:
                sample_count["status"] = "INSUFFICIENT"
        elif effective_symbols is not None:
            sample_count["status"] = "INVALID"

    orders: Dict[str, Any] = {
        "applicable": example in ("025", "026"),
        "status": "NOT_APPLICABLE" if example == "027" else "MISSING",
    }
    if summary is not None and example in ("025", "026"):
        broker = summary.get("broker")
        if not isinstance(broker, Mapping):
            problems.append("summary broker order counts are missing or invalid")
        else:
            submit = broker.get("submit")
            cancel = broker.get("cancel")
            orders.update({"submit": submit, "cancel": cancel})
            if any(
                isinstance(count, bool) or not isinstance(count, int) or count < 0
                for count in (submit, cancel)
            ):
                orders["status"] = "INVALID"
                problems.append("summary broker order counts are missing or invalid")
            elif submit != 0 or cancel != 0:
                orders["status"] = "FAILED"
                problems.append(
                    "unexpected broker activity: submit=%d cancel=%d" % (submit, cancel)
                )
            else:
                orders["status"] = "OK"
    elif (
        summary is not None
        and example == "027"
        and factor_mode is None
        and isinstance(summary.get("broker"), Mapping)
    ):
        broker = summary["broker"]
        orders.update({"submit": broker.get("submit"), "cancel": broker.get("cancel")})
        if broker.get("submit") != 0 or broker.get("cancel") != 0:
            orders["applicable"] = True
            orders["status"] = "FAILED"
            problems.append("unexpected broker activity in 027 summary")
    if summary is not None and example == "027" and factor_mode is not None:
        broker = summary.get("broker")
        if not isinstance(broker, Mapping):
            orders["status"] = "INVALID"
            problems.append("mode-pair 027 summary broker order counts are missing or invalid")
        else:
            submit = broker.get("submit")
            cancel = broker.get("cancel")
            if any(
                isinstance(count, bool) or not isinstance(count, int) or count < 0
                for count in (submit, cancel)
            ):
                orders["status"] = "INVALID"
                problems.append("mode-pair 027 summary broker order counts are missing or invalid")
            elif submit != 0 or cancel != 0:
                orders.update({"submit": submit, "cancel": cancel, "status": "FAILED"})
                orders["applicable"] = True
                problems.append("unexpected broker activity in 027 mode-pair summary")
            else:
                orders.update({"submit": submit, "cancel": cancel, "status": "OK"})
                orders["applicable"] = True

    expected_csv = output_dir / "factor_values.csv"
    csv_exists = expected_csv.is_file() and expected_csv.stat().st_size > 0
    factor_stats = (
        _csv_stats(expected_csv)
        if csv_exists
        else {
            "path": str(expected_csv),
            "exists": False,
            "rows": 0,
            "headers": [],
            "finite_values": {},
            "error": "CSV is missing or empty",
        }
    )
    if not csv_exists or factor_stats["rows"] < 1:
        problems.append("factor_values.csv is missing or empty")
    missing_factors = [
        factor for factor in EXPECTED_FACTORS[example] if factor not in factor_stats["headers"]
    ]
    empty_factors = [
        factor
        for factor in EXPECTED_FACTORS[example]
        if factor in factor_stats["headers"] and factor_stats["finite_values"].get(factor, 0) < 1
    ]
    if missing_factors:
        problems.append("factor_values.csv is missing factor columns: %s" % missing_factors)
    if empty_factors:
        problems.append("factor_values.csv has no finite values for factors: %s" % empty_factors)
    sample_count["factor_value_rows"] = factor_stats["rows"]
    if summary is not None:
        reported_dates = summary.get("dates")
        effective_symbols = summary.get("symbols")
        if (
            isinstance(reported_dates, bool)
            or not isinstance(reported_dates, int)
            or reported_dates < 1
        ):
            problems.append("summary dates is missing or invalid")
        elif (
            isinstance(effective_symbols, int)
            and not isinstance(effective_symbols, bool)
            and factor_stats["rows"] != effective_symbols * reported_dates
        ):
            problems.append(
                "factor_values.csv row count does not match summary symbols x dates: %d != %d x %d"
                % (factor_stats["rows"], effective_symbols, reported_dates)
            )
        if example == "027":
            reported_cells = summary.get("cells")
            reported_finite = summary.get("finite")
            factor_finite = factor_stats["finite_values"].get("alpha003", 0)
            if (
                isinstance(reported_cells, bool)
                or not isinstance(reported_cells, int)
                or reported_cells != factor_stats["rows"]
            ):
                problems.append("027 summary cells does not match factor_values.csv rows")
            if (
                isinstance(reported_finite, bool)
                or not isinstance(reported_finite, int)
                or reported_finite != factor_finite
            ):
                problems.append(
                    "027 summary finite does not match factor_values.csv finite factor values"
                )

    evaluation_results: Dict[str, Any] = {
        "status": "NOT_APPLICABLE" if example == "027" else "MISSING",
        "evaluation_id": None,
        "tables": {},
    }
    charts: Dict[str, Any] = {
        "requested": example in ("025", "026") and charts_enabled,
        "applicable": example in ("025", "026"),
        "status": "NOT_APPLICABLE" if example == "027" else "MISSING",
        "expected": [],
        "actual": [],
        "files": [],
    }
    if summary is not None and example in ("025", "026"):
        evaluation_id = summary.get("evaluation_id")
        evaluation_results["evaluation_id"] = evaluation_id
        evaluation_dir = output_dir / "evaluation" / str(evaluation_id)
        evaluation_results["path"] = str(evaluation_dir)
        if not isinstance(evaluation_id, str) or not evaluation_id:
            problems.append("summary evaluation_id is missing or invalid")
        elif not _path_inside(evaluation_dir, output_dir):
            problems.append("evaluation output resolves outside the run output")
        else:
            evaluation_manifest = evaluation_dir / "manifest.json"
            if not evaluation_manifest.is_file() or evaluation_manifest.stat().st_size < 1:
                problems.append("evaluation manifest is missing or empty")
                export_manifest: Optional[Mapping[str, Any]] = None
            else:
                try:
                    loaded_manifest = json.loads(evaluation_manifest.read_text(encoding="utf-8"))
                    export_manifest = (
                        loaded_manifest if isinstance(loaded_manifest, Mapping) else None
                    )
                except (OSError, ValueError) as exc:
                    export_manifest = None
                    problems.append(
                        "evaluation manifest is invalid: %s: %s" % (type(exc).__name__, exc)
                    )
            exports = None if export_manifest is None else export_manifest.get("exports")
            if not isinstance(exports, list) or any(not isinstance(item, str) for item in exports):
                problems.append("evaluation manifest exports list is missing or invalid")
                exports = []
            expected_pngs = []
            for export in exports:
                relative = Path(export)
                if relative.is_absolute() or ".." in relative.parts:
                    problems.append("evaluation manifest contains an unsafe export path")
                    continue
                if relative.suffix.lower() == ".png":
                    expected_pngs.append(relative.as_posix())
            actual_pngs = sorted(
                path.relative_to(evaluation_dir).as_posix()
                for path in evaluation_dir.rglob("*")
                if path.is_file() and path.suffix.lower() == ".png"
            )
            charts.update(
                {
                    "expected": sorted(expected_pngs),
                    "actual": actual_pngs,
                }
            )
            if charts_enabled:
                if not expected_pngs:
                    problems.append("evaluation export manifest declares no PNG charts")
                if sorted(expected_pngs) != actual_pngs:
                    problems.append(
                        "evaluation PNG set does not match manifest exports: expected=%s actual=%s"
                        % (sorted(expected_pngs), actual_pngs)
                    )
                for relative_path in sorted(expected_pngs):
                    png_path = evaluation_dir / relative_path
                    inside = _path_inside(png_path, evaluation_dir)
                    exists_nonempty = png_path.is_file() and png_path.stat().st_size > 0
                    chart_file = {
                        "path": str(png_path),
                        "manifest_path": relative_path,
                        "exists_nonempty": exists_nonempty,
                        "inside_evaluation_dir": inside,
                        "size_bytes": png_path.stat().st_size if png_path.is_file() else 0,
                        "sha256": _sha256(png_path) if png_path.is_file() else None,
                    }
                    charts["files"].append(chart_file)
                    if not exists_nonempty or not inside:
                        problems.append(
                            "evaluation PNG is missing, empty, or outside the export directory: %s"
                            % relative_path
                        )
                charts["status"] = (
                    "OK"
                    if expected_pngs
                    and sorted(expected_pngs) == actual_pngs
                    and all(
                        item["exists_nonempty"] and item["inside_evaluation_dir"]
                        for item in charts["files"]
                    )
                    else "FAILED"
                )
            else:
                if expected_pngs or actual_pngs:
                    problems.append("no-charts diagnostic unexpectedly exported PNG charts")
                charts["status"] = (
                    "NOT_REQUESTED" if not expected_pngs and not actual_pngs else "FAILED"
                )
            for table_name in REQUIRED_EVALUATION_TABLES:
                table_path = evaluation_dir / table_name
                stats = (
                    _csv_stats(table_path)
                    if table_path.is_file()
                    else {
                        "path": str(table_path),
                        "exists": False,
                        "rows": 0,
                        "headers": [],
                        "finite_values": {},
                        "error": "CSV is missing",
                    }
                )
                evaluation_results["tables"][table_name] = stats
                if not stats["exists"] or stats["error"]:
                    problems.append("evaluation table is missing or unreadable: %s" % table_name)
                elif stats["rows"] < 1:
                    problems.append("evaluation table has no records: %s" % table_name)
            finite_evaluation_values = {
                "labels.csv": ("value",),
                "ic.csv": ("ic", "rank_ic"),
                "signals.csv": ("value",),
            }
            for table_name, columns in finite_evaluation_values.items():
                stats = evaluation_results["tables"].get(table_name, {})
                if not any(_finite_columns_present(stats, (column,)) for column in columns):
                    problems.append(
                        "evaluation table has no finite values in %s: %s" % (columns, table_name)
                    )
        evaluation_results["status"] = (
            "OK"
            if not any(
                "evaluation" in problem or "factor_values.csv" in problem for problem in problems
            )
            and evaluation.get("status") == "OK"
            else "FAILED"
        )
        evaluation_results["charts"] = charts

    artifact_requested = requested_save and example in ("025", "026")
    artifact_status = (
        "REQUESTED"
        if artifact_requested
        else "NOT_REQUESTED" if example in ("025", "026") else "NOT_APPLICABLE"
    )
    saved_data_artifact: Dict[str, Any] = {
        "mode": save_mode,
        "requested": artifact_requested,
        "status": artifact_status,
    }
    panel_files: List[str] = []
    if example in ("025", "026") and not requested_save:
        saved_data_artifact.update(
            {
                "api": None,
                "path": None,
                "format": "optional panel/dataset artifact not requested",
                "files": [],
            }
        )
    elif example in ("025", "026"):
        if save_mode == "legacy_research_dataset":
            saved_path = output_dir / "dataset"
            saved_files = _artifact_manifest(saved_path)
            saved_data_artifact.update(
                {
                    "api": "--save-dataset",
                    "path": str(saved_path),
                    "format": "legacy ResearchDataset bundle",
                    "schema_note": "legacy dataset schema and identity are retained; output differs from current FactorPanel CSV by design",
                    "files": saved_files,
                    "inside_output_dir": _path_inside(saved_path, output_dir),
                }
            )
            if not saved_files:
                problems.append("legacy saved dataset is missing or empty")
            if not saved_data_artifact["inside_output_dir"]:
                problems.append("legacy saved dataset resolves outside the run output")
        elif save_mode == "factor_panel_csv":
            panel_dir = output_dir / "panel"
            saved_files = _artifact_manifest(panel_dir)
            panel_files = [
                str(panel_dir / item["path"])
                for item in saved_files
                if item["path"].lower().endswith(".csv") and item["size_bytes"] > 0
            ]
            saved_data_artifact.update(
                {
                    "api": "--save-panel",
                    "path": str(panel_dir),
                    "format": "current FactorPanel CSV bundle",
                    "schema_note": "current panel CSV schema; legacy identity fields are not retained as part of the planned structural change",
                    "files": saved_files,
                    "inside_output_dir": _path_inside(panel_dir, output_dir),
                }
            )
            if not panel_files:
                problems.append("saved panel has no non-empty CSV files")
            panel_csv_paths = sorted(
                item["path"] for item in saved_files if item["path"].lower().endswith(".csv")
            )
            nonempty_panel_csv_paths = sorted(
                item["path"]
                for item in saved_files
                if item["path"].lower().endswith(".csv") and item["size_bytes"] > 0
            )
            expected_panel_paths = sorted(EXPECTED_PANEL_CSVS)
            panel_csv_contract = {
                "expected": expected_panel_paths,
                "actual": panel_csv_paths,
                "nonempty": nonempty_panel_csv_paths,
                "exact_match": (
                    panel_csv_paths == expected_panel_paths
                    and nonempty_panel_csv_paths == expected_panel_paths
                ),
            }
            saved_data_artifact["csv_contract"] = panel_csv_contract
            if not panel_csv_contract["exact_match"]:
                problems.append(
                    "saved panel CSV set differs from the exact non-empty six-file contract: missing=%s empty=%s extra=%s"
                    % (
                        sorted(set(expected_panel_paths) - set(nonempty_panel_csv_paths)),
                        sorted(set(panel_csv_paths) - set(nonempty_panel_csv_paths)),
                        sorted(set(panel_csv_paths) - set(expected_panel_paths)),
                    )
                )
            if not saved_data_artifact["inside_output_dir"]:
                problems.append("saved panel resolves outside the run output")
        else:
            panel_files = []
            problems.append("saved panel API was not identified")
    else:
        panel_files = []
        saved_data_artifact.update(
            {
                "api": "factor_values.csv",
                "path": str(expected_csv),
                "format": "factor value CSV",
                "files": _artifact_manifest(expected_csv),
            }
        )

    reports = []
    if summary is not None:
        reports = _summary_report_paths(example, summary, output_dir)
    expected_reports = [
        (output_dir / ("factor_report_%s.html" % factor)).resolve()
        for factor in EXPECTED_FACTORS[example]
    ]
    if len(reports) != len(expected_reports):
        problems.append(
            "summary references %d reports; expected %d" % (len(reports), len(expected_reports))
        )
    report_artifacts = []
    for expected in expected_reports:
        exists = expected.is_file() and expected.stat().st_size > 0
        referenced = expected in reports
        inside = _path_inside(expected, output_dir)
        report_artifacts.append(
            {
                "path": str(expected),
                "exists_nonempty": exists,
                "referenced_by_summary": referenced,
                "inside_output_dir": inside,
                "size_bytes": expected.stat().st_size if expected.is_file() else 0,
                "sha256": _sha256(expected) if expected.is_file() else None,
            }
        )
        if not exists or not referenced or not inside:
            problems.append(
                "report is missing, empty, unreferenced, or outside output: %s" % expected
            )

    report_semantics = (
        _validate_report_semantics(output_dir, example) if require_report_semantics else None
    )
    if report_semantics is not None:
        problems.extend(report_semantics["problems"])
    result = {
        "status": "OK" if not problems else "FAILED",
        "problems": problems,
        "requested_save": requested_save,
        "evaluation": evaluation,
        "charts": charts,
        "sample_count": sample_count,
        "orders": orders,
        "evaluation_results": evaluation_results,
        "factor_values_csv": {
            **factor_stats,
            "exists_nonempty": csv_exists,
            "expected_factors": list(EXPECTED_FACTORS[example]),
            "finite_factors": {
                factor: factor_stats["finite_values"].get(factor, 0)
                for factor in EXPECTED_FACTORS[example]
            },
        },
        "saved_panel_csvs": panel_files,
        "saved_data_artifact": saved_data_artifact,
        "reports": report_artifacts,
    }
    if require_report_semantics:
        result["report_semantics"] = report_semantics
    return result


def _measure_process(
    command: Sequence[str],
    cwd: Path,
    interval_s: float,
    environment: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Capture subprocess wall/CPU and sampled RSS for its full process tree."""
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required for parent process-tree measurements") from exc

    cpu_by_pid: Dict[int, float] = {}
    samples = []
    peak_rss = 0
    with tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8"
    ) as stdout_file, tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_file:
        started_at = dt.datetime.now(dt.timezone.utc).isoformat()
        started = time.perf_counter()
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=None if environment is None else dict(environment),
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )

        def sample() -> None:
            nonlocal peak_rss
            try:
                root = psutil.Process(process.pid)
                processes = [root] + root.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                processes = []
            rss_total = 0
            cpu_total = 0.0
            pids = []
            for item in processes:
                try:
                    rss = int(item.memory_info().rss)
                    cpu_times = item.cpu_times()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                cpu = float(cpu_times.user + cpu_times.system)
                rss_total += rss
                cpu_total += cpu
                pids.append(item.pid)
                cpu_by_pid[item.pid] = max(cpu_by_pid.get(item.pid, 0.0), cpu)
            peak_rss = max(peak_rss, rss_total)
            samples.append(
                {
                    "elapsed_s": time.perf_counter() - started,
                    "rss_tree_bytes": rss_total,
                    "cpu_tree_s": cpu_total,
                    "pids": pids,
                }
            )

        while process.poll() is None:
            sample()
            time.sleep(interval_s)
        sample()
        returncode = process.wait()
        wall_s = time.perf_counter() - started
        ended_at = dt.datetime.now(dt.timezone.utc).isoformat()
        stdout_file.seek(0)
        stderr_file.seek(0)
        return {
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "returncode": returncode,
            "wall_s": wall_s,
            "cpu_tree_s": sum(cpu_by_pid.values()),
            "peak_rss_tree_bytes": peak_rss,
            "sample_interval_s": interval_s,
            "samples": samples,
            "stdout": stdout_file.read(),
            "stderr": stderr_file.read(),
        }


def _run_case(
    *,
    side: str,
    root: Path,
    example: str,
    output_dir: Path,
    data_dir: Path,
    symbols: int,
    interval_s: float,
    kind: str,
    group: Optional[int],
    entrypoint: Mapping[str, Any],
    module_origins: Mapping[str, Any],
    charts_enabled: bool = True,
    requested_save: bool = True,
    factor_mode: Optional[str] = None,
    capture_reports: bool = False,
) -> Dict[str, Any]:
    save_mode = entrypoint.get("save_mode")
    artifact_requested = requested_save and example in ("025", "026")
    command = _build_command(
        root,
        example,
        output_dir,
        data_dir,
        symbols,
        save_mode,
        no_charts=not charts_enabled,
        requested_save=requested_save,
        factor_mode=factor_mode,
    )
    entrypoint_command = command
    report_capture = {"enabled": False}
    if capture_reports:
        command, report_capture = _build_captured_command(command, root, output_dir)
    output_contract = {
        "save_mode": save_mode,
        "requested_save": requested_save,
        "artifact_requested": artifact_requested,
        "evaluation_charts": (
            "enabled"
            if charts_enabled and example in ("025", "026")
            else ("disabled_diagnostic" if example in ("025", "026") else "not_applicable")
        ),
        "chart_validation_source": (
            "fincore evaluation manifest exports" if example in ("025", "026") else "not_applicable"
        ),
        "artifact_path": (
            "dataset"
            if artifact_requested and save_mode == "legacy_research_dataset"
            else (
                "panel"
                if artifact_requested and save_mode == "factor_panel_csv"
                else "not_requested" if example in ("025", "026") else "factor_values.csv"
            )
        ),
        "contract_change_note": (
            "legacy ResearchDataset serialization and current FactorPanel CSV serialization have different schemas and identity retention by design; timing is end-to-end and does not isolate serialization"
            if artifact_requested and save_mode in ("legacy_research_dataset", "factor_panel_csv")
            else (
                "optional panel/dataset artifact was not requested; factor_values.csv remains required"
                if example in ("025", "026")
                else "027 emits its existing factor_values.csv without a saved panel option"
            )
        ),
    }
    if capture_reports:
        output_contract["measurement_note"] = REPORT_CAPTURE_NOTE
    result: Dict[str, Any] = {
        "side": side,
        "example": example,
        "kind": kind,
        "group": group,
        "requested_symbols": symbols,
        "requested_save": requested_save,
        "output_dir": str(output_dir),
        "command": command,
        "python_executable": sys.executable,
        "pythonpath": str(root.resolve()),
        "entrypoint_api": dict(entrypoint),
        "expected_module_origins": dict(module_origins),
        "module_import_binding": "run.py executes with PYTHONPATH set to this side's source root and no inherited PYTHONPATH",
        "output_contract": output_contract,
    }
    if capture_reports:
        result.update(
            {
                "entrypoint_command": entrypoint_command,
                "factor_mode": factor_mode,
                "report_capture": report_capture,
            }
        )
    try:
        measured = _measure_process(
            command, root, interval_s, environment=_process_environment(root)
        )
        result.update(
            {
                "started_at_utc": measured["started_at_utc"],
                "ended_at_utc": measured["ended_at_utc"],
                "returncode": measured["returncode"],
                "wall_s": measured["wall_s"],
                "cpu_tree_s": measured["cpu_tree_s"],
                "peak_rss_tree_bytes": measured["peak_rss_tree_bytes"],
                "sample_interval_s": measured["sample_interval_s"],
                "process_samples": measured["samples"],
                "stdout_tail": measured["stdout"][-3000:],
                "stderr_tail": measured["stderr"][-3000:],
            }
        )
    except Exception as exc:
        result.update(
            {
                "returncode": None,
                "wall_s": None,
                "cpu_tree_s": None,
                "peak_rss_tree_bytes": None,
                "harness_error": "%s: %s" % (type(exc).__name__, exc),
            }
        )

    summary_path = output_dir / "summary.json"
    summary = None
    summary_error = None
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            summary_error = "%s: %s" % (type(exc).__name__, exc)
    else:
        summary_error = "summary.json is missing"
    result["summary_path"] = str(summary_path)
    result["summary_sha256"] = _sha256(summary_path) if summary_path.is_file() else None
    result["summary"] = summary
    result["effective_symbols"] = summary.get("symbols") if summary is not None else None
    result["summary_error"] = summary_error
    validation = _validate_run(
        example,
        summary,
        result.get("returncode"),
        output_dir,
        save_mode=save_mode,
        requested_symbols=symbols,
        charts_enabled=charts_enabled,
        requested_save=requested_save,
        factor_mode=factor_mode,
        require_report_semantics=capture_reports,
    )
    if result.get("harness_error"):
        validation["status"] = "FAILED"
        validation["problems"].append(result["harness_error"])
    if summary_error and summary_error not in validation["problems"]:
        validation["problems"].append(summary_error)
        validation["status"] = "FAILED"
    result["validation"] = validation
    output_files = _artifact_manifest(output_dir)
    result["output_files"] = output_files
    result["output_files_sha256"] = _canonical_hash(output_files)
    return result


def _run_dir(output: Path, example: str, kind: str, side: str, group: Optional[int]) -> Path:
    suffix = "warmup" if group is None else "group-%02d" % group
    directory = output / "runs" / example / suffix / (kind + "-" + side)
    directory.parent.mkdir(parents=True, exist_ok=True)
    if directory.exists():
        raise FileExistsError("run output directory already exists: %s" % directory)
    return directory


def _alternating_order(group: int) -> Tuple[str, str]:
    if group % 2:
        return "baseline", "candidate"
    return "candidate", "baseline"


def _median_stats(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    metrics = ("wall_s", "cpu_tree_s", "peak_rss_tree_bytes")
    return {
        metric: statistics.median(
            float(item[metric]) for item in records if isinstance(item.get(metric), (int, float))
        )
        for metric in metrics
    }


def _mode_cost_ratios(
    side_stats: Mapping[str, Mapping[str, Any]], modes: Mapping[str, str]
) -> Dict[str, Optional[float]]:
    build_side = next(side for side, mode in modes.items() if mode == "build")
    native_side = next(side for side, mode in modes.items() if mode == "native")
    return {
        metric: (
            side_stats[build_side][metric] / side_stats[native_side][metric]
            if side_stats[native_side][metric]
            else None
        )
        for metric in ("wall_s", "cpu_tree_s", "peak_rss_tree_bytes")
    }


def _sample_scope(
    requested_symbols: int,
    no_charts: bool = False,
    requested_save: bool = True,
    examples: Sequence[str] = EXAMPLES,
) -> Dict[str, Any]:
    symbol_floor_met = requested_symbols >= FORMAL_MINIMUM_SYMBOLS
    formal = symbol_floor_met and not no_charts
    run_status = "OK" if formal else "DIAGNOSTIC_ONLY" if no_charts else "SMOKE_ONLY"
    scope_status = (
        "FORMAL_SCOPE_MET"
        if formal
        else "DIAGNOSTIC_NO_CHARTS" if no_charts else "INSUFFICIENT_FOR_FORMAL_SAMPLE_FLOOR"
    )
    return {
        "run_status": run_status,
        "status": scope_status,
        "requested_symbols": requested_symbols,
        "requested_save": requested_save,
        "examples": list(examples),
        "formal_minimum_symbols": FORMAL_MINIMUM_SYMBOLS,
        "formal_sample_floor_met": symbol_floor_met,
        "formal_eligible": formal,
        "charts_enabled": not no_charts,
        "note": (
            "Harness checks passed at or above the formal symbol-count floor; performance acceptance is assessed separately."
            if formal
            else (
                "This no-charts run is diagnostic only and cannot be formal benchmark evidence."
                if no_charts
                else "All process/output checks passed, but this reduced-symbol run is not formal benchmark evidence."
            )
        ),
    }


def _mode_pair_sample_scope(
    requested_symbols: int, requested_save: bool, examples: Sequence[str]
) -> Dict[str, Any]:
    scope = _sample_scope(
        requested_symbols,
        no_charts=False,
        requested_save=requested_save,
        examples=examples,
    )
    formal_complete = (
        requested_symbols >= FORMAL_MINIMUM_SYMBOLS
        and tuple(examples) == EXAMPLES
        and requested_save
    )
    scope["formal_eligible"] = formal_complete
    if not formal_complete:
        scope["run_status"] = "SMOKE_ONLY"
        scope["status"] = (
            "INSUFFICIENT_FOR_FORMAL_SAMPLE_FLOOR"
            if requested_symbols < FORMAL_MINIMUM_SYMBOLS
            else "INCOMPLETE_FORMAL_EXAMPLE_OR_OUTPUT_SCOPE"
        )
        scope["note"] = (
            "This mode-pair run is reduced-scope evidence; it is not formal iteration 47 acceptance."
        )
    else:
        scope["note"] = (
            "All example, panel, report, chart, and symbol-count scope checks passed. "
            "Mode-pair measurements are instrumented and have no performance reduction gate."
        )
    scope["instrumented_measurements"] = True
    scope["performance_reduction_gate"] = None
    return scope


def _selected_examples(requested: Optional[Sequence[str]]) -> Tuple[str, ...]:
    if not requested:
        return EXAMPLES
    requested_set = set(requested)
    unknown = requested_set - set(EXAMPLES)
    if unknown:
        raise ValueError("unsupported examples: %s" % sorted(unknown))
    return tuple(example for example in EXAMPLES if example in requested_set)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", required=True, help="frozen source checkout")
    parser.add_argument("--candidate-root", required=True, help="candidate source checkout")
    parser.add_argument("--baseline-revision", help="revision represented by a source archive")
    parser.add_argument("--candidate-revision", help="revision represented by a source archive")
    parser.add_argument(
        "--baseline-factor-mode",
        choices=("native", "build"),
        help="factor implementation mode for the baseline side (paired mode profile)",
    )
    parser.add_argument(
        "--candidate-factor-mode",
        choices=("native", "build"),
        help="factor implementation mode for the candidate side (paired mode profile)",
    )
    parser.add_argument("--data-dir", required=True, help="fixed input data directory")
    parser.add_argument("--output", required=True, help="new evidence directory")
    parser.add_argument(
        "--example",
        action="append",
        choices=EXAMPLES,
        help="limit runs to this example; repeat to select multiple (default: all)",
    )
    parser.add_argument(
        "--symbols",
        type=int,
        default=FORMAL_MINIMUM_SYMBOLS,
        help="requested symbols (default 500; values below 500 are smoke-only)",
    )
    parser.add_argument(
        "--no-charts",
        action="store_true",
        help="disable 025/026 evaluation PNGs for diagnostics only; result cannot be formal",
    )
    parser.add_argument(
        "--no-save-panel",
        action="store_true",
        help="skip optional 025/026 panel/dataset exports; factor_values.csv remains required",
    )
    parser.add_argument("--groups", type=int, default=3)
    parser.add_argument("--sample-interval", type=float, default=0.05)
    parser.add_argument(
        "--allow-config-difference",
        action="append",
        choices=sorted(CONFIG_DIFFERENCE_ALLOWLIST),
        default=[],
        help="approve only the documented exact migration for this input field",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    selected_examples = _selected_examples(args.example)
    requested_save = not args.no_save_panel
    output = Path(args.output).expanduser().resolve()
    payload: Dict[str, Any] = {
        "schema_version": "factor-research-paired-benchmark-v1",
        "status": "FAILED",
        "command": list(sys.argv if argv is None else [sys.argv[0]] + list(argv)),
        "parameters": {
            "examples": list(selected_examples),
            "symbols": args.symbols,
            "formal_minimum_symbols": FORMAL_MINIMUM_SYMBOLS,
            "groups": args.groups,
            "warmups_per_side_example": 1,
            "report": True,
            "requested_save": requested_save,
            "save_panel_examples": [
                example
                for example in selected_examples
                if requested_save and example in ("025", "026")
            ],
            "charts_enabled": not args.no_charts,
            "chart_examples": [
                example for example in selected_examples if example in ("025", "026")
            ],
            "no_charts_diagnostic": args.no_charts,
            "sample_interval_s": args.sample_interval,
            "python_executable": sys.executable,
            "allow_config_differences": list(args.allow_config_difference),
        },
        "runs": [],
    }
    if args.baseline_factor_mode is not None or args.candidate_factor_mode is not None:
        payload["paired_comparisons"] = []
        payload["parameters"].update(
            {
                "baseline_factor_mode": args.baseline_factor_mode,
                "candidate_factor_mode": args.candidate_factor_mode,
            }
        )
    mode_data_dir: Optional[Path] = None
    mode_input_before: Optional[Dict[str, Any]] = None
    mode_roots: Optional[Dict[str, Path]] = None
    mode_sides: Optional[Dict[str, Dict[str, Any]]] = None
    mode_profile_requested = (
        args.baseline_factor_mode is not None or args.candidate_factor_mode is not None
    )
    created_output = False
    try:
        modes = _resolve_factor_modes(args.baseline_factor_mode, args.candidate_factor_mode)
        if args.symbols < 1:
            raise ValueError("--symbols must be positive")
        minimum_groups = 1 if modes is not None else 3
        if args.groups < minimum_groups:
            raise ValueError("--groups must be at least %d" % minimum_groups)
        if args.sample_interval <= 0:
            raise ValueError("--sample-interval must be positive")
        if modes is not None:
            payload["factor_mode_pair"] = {
                "modes": modes,
                "profile": "instrumented_native_build_pair",
                "performance_reduction_gate": None,
                "measurement_note": REPORT_CAPTURE_NOTE,
            }
            if args.no_charts:
                raise ValueError("mode-pair profile requires evaluation charts")
            if args.no_save_panel:
                raise ValueError("mode-pair profile requires saved 025/026 panel outputs")
            if args.allow_config_difference:
                raise ValueError("mode-pair profile does not allow input configuration differences")
        if output.exists():
            raise FileExistsError("output directory already exists: %s" % output)
        output.mkdir(parents=True)
        created_output = True
        roots = {
            "baseline": Path(args.baseline_root).expanduser().resolve(),
            "candidate": Path(args.candidate_root).expanduser().resolve(),
        }
        mode_roots = (
            roots
            if args.baseline_factor_mode is not None or args.candidate_factor_mode is not None
            else None
        )
        revisions = {
            "baseline": args.baseline_revision,
            "candidate": args.candidate_revision,
        }
        data_dir = Path(args.data_dir).expanduser().resolve()
        mode_data_dir = data_dir if mode_profile_requested else None
        manifest_path = data_dir / "_metadata" / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("data manifest not found: %s" % manifest_path)
        payload["input"] = {
            "data_dir": str(data_dir),
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "manifest_size_bytes": manifest_path.stat().st_size,
        }
        execution_environment = _dependency_snapshot()
        payload["execution_environment"] = execution_environment
        sides = {
            name: _inspect_side(
                root,
                name,
                data_dir,
                args.symbols,
                revisions[name],
                execution_environment,
                examples=selected_examples,
                requested_save=requested_save,
                require_factor_mode=modes is not None,
            )
            for name, root in roots.items()
        }
        mode_sides = sides if mode_profile_requested else None
        if modes is not None:
            for side, mode in modes.items():
                sides[side]["effective_config_mode_source"] = "explicit --%s-factor-mode" % side
                for example in selected_examples:
                    effective = sides[side]["effective_configs"][example]
                    effective["factor_mode"] = mode
                    sides[side]["effective_config_sha256"][example] = _canonical_hash(effective)
        payload["sides"] = sides
        if modes is not None:
            payload["factor_mode_pair"]["runtime_provenance"] = _validate_factor_mode_pair(sides)
            for example in selected_examples:
                if example in ("025", "026"):
                    wrong_sides = [
                        side
                        for side in sides
                        if sides[side]["entrypoints"][example]["save_mode"] != "factor_panel_csv"
                    ]
                    if wrong_sides:
                        raise RuntimeError(
                            "%s mode-pair requires --save-panel on both sides: %s"
                            % (example, wrong_sides)
                        )
        if args.no_charts:
            unsupported = [
                "%s:%s" % (side, example)
                for side, metadata in sides.items()
                for example in selected_examples
                if example in ("025", "026")
                if not metadata["entrypoints"][example]["options"]["--no-charts"]
            ]
            if unsupported:
                raise RuntimeError(
                    "no-charts diagnostic is unsupported by entrypoints: %s" % unsupported
                )
        if modes is None:
            payload["output_contract_comparison"] = {
                "shared_outputs": [
                    "factor_values.csv",
                    "summary.json",
                    "factor_report_*.html",
                    "evaluation export files generated by each example",
                ],
                "save_api_by_side": {
                    side: {
                        example: sides[side]["entrypoints"][example]["save_mode"]
                        for example in selected_examples
                    }
                    for side in sides
                },
                "requested_save": requested_save,
                "planned_025_026_difference": (
                    "baseline uses --save-dataset and retains the legacy ResearchDataset schema/identity in dataset/; candidate uses --save-panel and writes the current FactorPanel CSV schema to panel/"
                    if requested_save
                    and any(example in ("025", "026") for example in selected_examples)
                    else (
                        "no optional 025/026 panel or dataset artifact is requested; factor_values.csv remains required"
                        if any(example in ("025", "026") for example in selected_examples)
                        else "027 has no optional panel/dataset artifact; factor_values.csv remains required"
                    )
                ),
                "comparison_limit": (
                    "the saved data purpose is shared, while storage schema and identity retention intentionally differ; process wall is end-to-end and does not isolate serialization"
                    if requested_save
                    and any(example in ("025", "026") for example in selected_examples)
                    else "no optional panel/dataset serialization is included for the selected examples; measured wall time covers the shared report/evaluation path"
                ),
                "preserve_report_and_evaluation_outputs": True,
                "evaluation_chart_contract": "default 025/026 run exports every PNG named in fincore evaluation manifest.exports; each must be present and non-empty; --no-charts is explicit diagnostic-only mode",
            }
        else:
            payload["output_contract_comparison"] = {
                "shared_outputs": [
                    "factor_values.csv",
                    "summary.json",
                    "factor_report_*.html",
                    "report_semantics.json",
                    "025/026 FactorPanel CSV bundles",
                    "evaluation tables and PNG exports",
                ],
                "factor_mode_by_side": modes,
                "output_api_by_side": {
                    side: {
                        example: sides[side]["entrypoints"][example]["save_mode"]
                        for example in selected_examples
                    }
                    for side in sides
                },
                "reports_and_evaluation_outputs_preserved": True,
                "comparison_limit": REPORT_CAPTURE_NOTE,
            }
        for name, metadata in sides.items():
            if not metadata["source_revision"]:
                raise ValueError(
                    "%s has no git HEAD; pass --%s-revision for its source archive" % (name, name)
                )
        if modes is None:
            differences = {
                example: _config_differences(
                    sides["baseline"]["effective_configs"][example],
                    sides["candidate"]["effective_configs"][example],
                )
                for example in selected_examples
            }
            payload["input_configuration_comparison"] = {
                "equal": not any(differences.values()),
                "differences": differences,
                **_classify_config_differences(differences, args.allow_config_difference),
            }
            if not payload["input_configuration_comparison"]["compatible"]:
                raise ValueError(
                    "effective input configuration has unapproved differences: %s"
                    % json.dumps(
                        payload["input_configuration_comparison"]["unapproved_differences"],
                        ensure_ascii=False,
                    )
                )
        else:
            payload["input_configuration_comparison"] = _mode_config_comparison(
                sides, modes, selected_examples
            )
        for side, metadata in sides.items():
            probe = metadata["module_probe"]
            if probe.get("returncode") != 0 or "modules" not in probe:
                raise RuntimeError("%s module source probe failed" % side)
            modules = probe["modules"]
            for module_name in ("backtrader", "research"):
                module_path = Path(modules[module_name])
                if not _path_inside(module_path, roots[side]):
                    raise RuntimeError(
                        "%s %s imported outside its checkout: %s" % (side, module_name, module_path)
                    )

        if modes is not None:
            input_before = _selected_input_manifest(data_dir, args.symbols)
            mode_input_before = input_before
            payload["input"]["selected_run_input_before"] = input_before

            # Pair each complete warmup before beginning measured groups.
            for example in selected_examples:
                pair_records = {}
                for side in _alternating_order(EXAMPLES.index(example) + 1):
                    run_dir = _run_dir(output, example, "warmup", side, None)
                    record = _run_case(
                        side=side,
                        root=roots[side],
                        example=example,
                        output_dir=run_dir,
                        data_dir=data_dir,
                        symbols=args.symbols,
                        interval_s=args.sample_interval,
                        kind="warmup",
                        group=None,
                        entrypoint=sides[side]["entrypoints"][example],
                        module_origins=sides[side]["module_probe"]["modules"],
                        charts_enabled=True,
                        requested_save=True,
                        factor_mode=modes[side],
                        capture_reports=True,
                    )
                    payload["runs"].append(record)
                    pair_records[side] = record
                    if record["validation"]["status"] != "OK":
                        raise RuntimeError(
                            "%s %s warmup failed: %s"
                            % (side, example, "; ".join(record["validation"]["problems"]))
                        )
                _append_mode_comparison(
                    payload,
                    output=output,
                    example=example,
                    kind="warmup",
                    group=None,
                    baseline=pair_records["baseline"],
                    candidate=pair_records["candidate"],
                )

            for group in range(1, args.groups + 1):
                for example in selected_examples:
                    pair_records = {}
                    for side in _alternating_order(group):
                        run_dir = _run_dir(output, example, "measured", side, group)
                        record = _run_case(
                            side=side,
                            root=roots[side],
                            example=example,
                            output_dir=run_dir,
                            data_dir=data_dir,
                            symbols=args.symbols,
                            interval_s=args.sample_interval,
                            kind="measured",
                            group=group,
                            entrypoint=sides[side]["entrypoints"][example],
                            module_origins=sides[side]["module_probe"]["modules"],
                            charts_enabled=True,
                            requested_save=True,
                            factor_mode=modes[side],
                            capture_reports=True,
                        )
                        payload["runs"].append(record)
                        pair_records[side] = record
                    invalid = {
                        side: record["validation"]["problems"]
                        for side, record in pair_records.items()
                        if record["validation"]["status"] != "OK"
                    }
                    if invalid:
                        raise RuntimeError(
                            "%s measured mode-pair output validation failed: %s"
                            % (example, invalid)
                        )
                    _append_mode_comparison(
                        payload,
                        output=output,
                        example=example,
                        kind="measured",
                        group=group,
                        baseline=pair_records["baseline"],
                        candidate=pair_records["candidate"],
                    )
            input_after = _selected_input_manifest(data_dir, args.symbols)
            payload["input"]["selected_run_input_after"] = input_after
            payload["input"]["selected_run_input_unchanged"] = input_before == input_after
            if input_before != input_after:
                raise RuntimeError("selected run input manifest changed during benchmark")
        else:
            # Legacy revision/performance mode retains its direct command path.
            for example in selected_examples:
                for side in _alternating_order(EXAMPLES.index(example) + 1):
                    run_dir = _run_dir(output, example, "warmup", side, None)
                    record = _run_case(
                        side=side,
                        root=roots[side],
                        example=example,
                        output_dir=run_dir,
                        data_dir=data_dir,
                        symbols=args.symbols,
                        interval_s=args.sample_interval,
                        kind="warmup",
                        group=None,
                        entrypoint=sides[side]["entrypoints"][example],
                        module_origins=sides[side]["module_probe"]["modules"],
                        charts_enabled=not args.no_charts,
                        requested_save=requested_save,
                    )
                    payload["runs"].append(record)
                    if record["validation"]["status"] != "OK":
                        raise RuntimeError(
                            "%s %s warmup failed: %s"
                            % (side, example, "; ".join(record["validation"]["problems"]))
                        )

            for group in range(1, args.groups + 1):
                for example in selected_examples:
                    for side in _alternating_order(group):
                        run_dir = _run_dir(output, example, "measured", side, group)
                        record = _run_case(
                            side=side,
                            root=roots[side],
                            example=example,
                            output_dir=run_dir,
                            data_dir=data_dir,
                            symbols=args.symbols,
                            interval_s=args.sample_interval,
                            kind="measured",
                            group=group,
                            entrypoint=sides[side]["entrypoints"][example],
                            module_origins=sides[side]["module_probe"]["modules"],
                            charts_enabled=not args.no_charts,
                            requested_save=requested_save,
                        )
                        payload["runs"].append(record)

        hashes_after = {name: _source_manifest(root) for name, root in roots.items()}
        payload["source_hashes_after"] = hashes_after
        if modes is not None:
            payload["source_hash_drift"] = {
                name: _source_drift(sides[name]["source_hashes"], hashes_after[name])
                for name in roots
            }
        else:
            payload["source_hash_drift"] = {
                name: {
                    path: [digest, hashes_after[name].get(path)]
                    for path, digest in sides[name]["source_hashes"].items()
                    if hashes_after[name].get(path) != digest
                }
                for name in roots
            }
        if any(payload["source_hash_drift"].values()):
            raise RuntimeError("source hashes changed during benchmark")

        metrics = {}
        for example in selected_examples:
            metrics[example] = {}
            for side in roots:
                records = [
                    record
                    for record in payload["runs"]
                    if record["kind"] == "measured"
                    and record["example"] == example
                    and record["side"] == side
                ]
                metrics[example][side] = _median_stats(records)
            if modes is None:
                metrics[example]["candidate_over_baseline"] = {
                    metric: (
                        metrics[example]["candidate"][metric] / metrics[example]["baseline"][metric]
                        if metrics[example]["baseline"][metric]
                        else None
                    )
                    for metric in ("wall_s", "cpu_tree_s", "peak_rss_tree_bytes")
                }
            else:
                metrics[example]["factor_modes"] = modes
                metrics[example]["build_over_native"] = _mode_cost_ratios(metrics[example], modes)
        payload["summary_stats"] = metrics
        failures = [
            record
            for record in payload["runs"]
            if record.get("validation", {}).get("status") != "OK"
        ]
        if failures:
            raise RuntimeError("one or more measured runs failed validation")
        payload["sample_scope"] = (
            _mode_pair_sample_scope(args.symbols, requested_save, selected_examples)
            if modes is not None
            else _sample_scope(
                args.symbols,
                no_charts=args.no_charts,
                requested_save=requested_save,
                examples=selected_examples,
            )
        )
        payload["status"] = payload["sample_scope"]["run_status"]
    except Exception as exc:
        payload["error"] = "%s: %s" % (type(exc).__name__, exc)
        if mode_profile_requested:
            if (
                mode_data_dir is not None
                and mode_input_before is not None
                and "input" in payload
                and "selected_run_input_after" not in payload["input"]
            ):
                try:
                    input_after = _selected_input_manifest(mode_data_dir, args.symbols)
                    payload["input"]["selected_run_input_after"] = input_after
                    payload["input"]["selected_run_input_unchanged"] = (
                        mode_input_before == input_after
                    )
                except Exception as manifest_exc:
                    payload["input"]["selected_run_input_after_error"] = "%s: %s" % (
                        type(manifest_exc).__name__,
                        manifest_exc,
                    )
            if (
                mode_roots is not None
                and mode_sides is not None
                and "source_hashes_after" not in payload
            ):
                try:
                    hashes_after = {
                        name: _source_manifest(root) for name, root in mode_roots.items()
                    }
                    payload["source_hashes_after"] = hashes_after
                    payload["source_hash_drift"] = {
                        name: _source_drift(mode_sides[name]["source_hashes"], hashes_after[name])
                        for name in mode_roots
                    }
                except Exception as source_exc:
                    payload["source_hashes_after_error"] = "%s: %s" % (
                        type(source_exc).__name__,
                        source_exc,
                    )
    finally:
        if created_output and output.is_dir():
            result_path = output / "benchmark.json"
            result_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print("results: %s" % result_path)
    return 0 if payload["status"] in ("OK", "SMOKE_ONLY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
