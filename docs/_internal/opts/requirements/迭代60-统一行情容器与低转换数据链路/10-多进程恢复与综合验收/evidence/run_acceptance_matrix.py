"""Iteration 60 acceptance matrix: per-repo HEAD, command, raw log, failure set.

Acceptance report P1-7 asks for reproducible, per-repository evidence bound to
the exact commit under test instead of summaries. For every repository this
script records:

* the git HEAD and whether the work tree is clean;
* the interpreter and the import location of each package (editable source
  tree vs. installed copy);
* the exact pytest command, the complete raw log, and the sorted set of
  FAILED/ERROR node ids;
* with ``--baseline DIR``, the per-test difference against an earlier run.

Usage (from the backtrader repository root)::

    python <this file> --out OUT_DIR [--baseline OLD_OUT_DIR] [--python PY] [--only NAME ...]

Only public source trees and tests are read; no private configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[8]  # .../new_projects


def _repos(root: Path) -> dict:
    sdk = root / "bt_api_py"
    return {
        "backtrader": (root / "backtrader", ["tests", "-m", "not slow and not performance"]),
        "bt_api_py": (sdk, ["tests"]),
        "bt_api_base": (sdk / "bt_api" / "bt_api_base", ["tests"]),
        "bt_api_ctp": (sdk / "bt_api" / "bt_api_ctp", ["tests"]),
        "bt_api_okx": (sdk / "bt_api" / "bt_api_okx", ["tests"]),
        "bt_api_binance": (sdk / "bt_api" / "bt_api_binance", ["tests"]),
        "bt_api_execution": (sdk / "bt_api" / "bt_api_execution", ["tests"]),
        "bt_api_gateway": (sdk / "bt_api" / "bt_api_gateway", ["tests"]),
        "bt_api_transport_zmq": (sdk / "bt_api" / "bt_api_transport_zmq", ["tests"]),
    }


def _pythonpath(root: Path, extra: str = "") -> str:
    """Import every package from the source trees under ``root`` (not site-packages)."""
    sdk = root / "bt_api_py"
    parts = [str(root / "backtrader"), str(sdk)]
    parts += [str(path / "src") for path in sorted((sdk / "bt_api").glob("bt_api_*")) if (path / "src").is_dir()]
    if extra:
        parts.insert(0, extra)
    return os.pathsep.join(parts)
PACKAGES = (
    "backtrader",
    "bt_api_py",
    "bt_api_base",
    "bt_api_ctp",
    "bt_api_okx",
    "bt_api_binance",
    "bt_api_execution",
    "bt_api_gateway",
    "bt_api_transport_zmq",
    "msgpack",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def _imports(python: str, env: dict) -> dict[str, str]:
    script = (
        "import importlib, json\n"
        f"names = {list(PACKAGES)!r}\n"
        "out = {}\n"
        "for name in names:\n"
        "    try:\n"
        "        module = importlib.import_module(name)\n"
        "        out[name] = getattr(module, '__file__', None) or 'namespace'\n"
        "    except Exception as error:\n"
        "        out[name] = 'IMPORT_FAILED: ' + type(error).__name__\n"
        "try:\n"
        "    from msgpack import _cmsgpack  # noqa: F401\n"
        "    out['msgpack_backend'] = 'c'\n"
        "except Exception:\n"
        "    out['msgpack_backend'] = 'python'\n"
        "print(json.dumps(out))\n"
    )
    result = subprocess.run(
        [python, "-c", script], capture_output=True, text=True, check=False, env=env
    )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"error": result.stderr[-2000:]}


def _failures(log: str) -> list[str]:
    found = set()
    for line in log.splitlines():
        if line.startswith(("FAILED tests", "ERROR tests")):
            found.add(line.split(" - ", 1)[0].strip())
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--workers", default="8")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--extra-path", default="", help="prepended to PYTHONPATH (e.g. a msgpack overlay)")
    options = parser.parse_args()
    env = dict(os.environ, PYTHONPATH=_pythonpath(options.root, options.extra_path))
    options.out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": subprocess.run(
            [options.python, "-c", "import sys; print(sys.version)"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip(),
        "platform": platform.platform(),
        "root": str(options.root),
        "pythonpath": env["PYTHONPATH"],
        "imports": _imports(options.python, env),
        "repos": {},
    }
    for name, (repo, args) in _repos(options.root).items():
        if options.only and name not in options.only:
            continue
        command = [
            options.python, "-m", "pytest", *args, "-q", "-p", "no:cacheprovider",
            "-n", options.workers, "-rfE",
        ]
        started = time.monotonic()
        result = subprocess.run(
            command, cwd=repo, capture_output=True, text=True, check=False, env=env
        )
        log = result.stdout + result.stderr
        (options.out / f"{name}.log").write_text(log, encoding="utf-8")
        failures = _failures(log)
        (options.out / f"{name}.failures.txt").write_text(
            "".join(f"{item}\n" for item in failures), encoding="utf-8"
        )
        summary = next(
            (line for line in reversed(log.splitlines()) if " passed" in line or " failed" in line),
            "",
        )
        entry = {
            "head": _git(repo, "rev-parse", "HEAD"),
            "dirty": bool(_git(repo, "status", "--porcelain", "--untracked-files=no")),
            "command": command,
            "cwd": str(repo),
            "exit_code": result.returncode,
            "seconds": round(time.monotonic() - started, 1),
            "summary": summary.strip("= "),
            "failure_count": len(failures),
        }
        if options.baseline is not None:
            old_path = options.baseline / f"{name}.failures.txt"
            if old_path.exists():
                old = {line for line in old_path.read_text(encoding="utf-8").splitlines() if line}
                new = set(failures)
                entry["new_failures"] = sorted(new - old)
                entry["fixed_failures"] = sorted(old - new)
        manifest["repos"][name] = entry
        print(f"{name:22s} {entry['summary']}  new={len(entry.get('new_failures', []))}")
    (options.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
